"""Skin packs: discovery, manifest validation, and asset serving (feature W1).

A skin pack is a directory containing a validated ``manifest.json`` that layers
extra CSS, scripts, palette tokens and UI tweaks on top of the builtin skins.
Two roots are discovered:

- builtin: ``static/skins/`` under the repo static root (ships with WebUI)
- user: ``$HERMES_HOME/skins/`` for the active profile (resolved read-only)

A user pack with the same ``key`` as a builtin pack SHADOWS the builtin pack.

DESIGN INVARIANT — packs never touch the builtin ``skin`` setting allowlists.
``_SETTINGS_SKIN_VALUES`` in ``api/config.py`` and the other hardcoded builtin
skin lists on the client enumerate the shipped skin families and are divergent
from pack keys BY DESIGN. A pack is selected through the separate
``skin_pack`` setting and applied in the DOM as ``pack:<key>``, never as a
``skin`` value. Nothing in this module reads or extends those allowlists.
Batch 3 adds one carve-out, ``applyMode: "css-key"``: a pack whose styling
already ships in the main stylesheet (the generated builtin skin packs under
``static/skins/``) is applied by the frontend as the bare
``data-skin="<key>"``. The server validates the enum only and never
key-restricts it — whether a key's CSS exists is owned by the frontend and
``static/style.css``, and this module still never reads the allowlists.

Import discipline: no ``api.*`` import at module scope. ``api.config``,
``api.profiles`` and ``api.helpers`` are imported lazily inside the functions
that need them, so importing this module stays cheap and side-effect free.

Batch 4 adds image tweaks: a pack declares ``{"type": "image"}`` with ``apply``
exactly ``{"var": <token>}``; the user uploads an image through the tweak UI,
the server stores it under ``<STATE_DIR>/skin_uploads/<pack_key>/`` and serves
it same-origin, and the stored tweak value is the server-generated
``<sha256>.<ext>`` filename. Uploads accept png/jpeg/gif/webp only — SVG is
deliberately excluded from the UPLOAD path: pack assets are admin-trust
(pack authors) while uploads come from any authenticated user, and an uploaded
SVG served as a directly-navigated same-origin document is a stored-XSS
surface the asset route deliberately does not have.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── limits ──────────────────────────────────────────────────────────────────
_MANIFEST_MAX_BYTES = 64 * 1024
_VALUE_MAX_CHARS = 64
_MAX_PREVIEW_COLORS = 3
_MAX_SCRIPTS = 4
_MAX_TWEAKS = 12
_NAME_MAX = 40
_AUTHOR_MAX = 60
_DESCRIPTION_MAX = 200
_TEMPLATE_MAX = 128
_SELECT_MAX_OPTIONS = 8
_RESULT_MAX_PACKS = 32
_RESULT_MAX_TWEAKS_PER_PACK = 32
_RESULT_MAX_JSON_BYTES = 16 * 1024

# batch 4 image-tweak upload limits
_UPLOAD_MIN_BYTES = 64
_UPLOAD_MAX_BYTES = 2 * 1024 * 1024
_UPLOAD_MAX_FILES_PER_PACK = 32

# ── schema regexes ──────────────────────────────────────────────────────────
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,32}$")
_TWEAK_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")
_SELECT_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_CLASS_RE = re.compile(r"^pack-[a-z0-9-]{1,32}$")
_PACK_TOKEN_RE = re.compile(r"^pack-[a-z0-9-]{1,32}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
# Template body: everything around the ``{value}`` placeholder. The class
# deliberately excludes ``;``, ``{`` and ``}`` so a template can only compose
# one declaration value, never inject a second rule.
_TEMPLATE_BODY_RE = re.compile(r"^[A-Za-z0-9 #%(),./-]*$")
# Safe CSS value (port of the client sanitizer semantics): hex colour,
# rgb()/rgba()/hsl()/hsla() with benign paren content, a bare "r, g, b"
# number triple, a CSS colour keyword, or a number with an optional unit.
_SAFE_VALUE_RE = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}"
    r"|(?:rgb|hsl)a?\(\s*[0-9a-zA-Z.,%/ ]+\s*\)"
    r"|-?[0-9]+(?:\.[0-9]+)?\s*,\s*-?[0-9]+(?:\.[0-9]+)?\s*,\s*-?[0-9]+(?:\.[0-9]+)?"
    r"|[a-zA-Z]{3,20}"
    r"|-?[0-9.]+[a-z%]{0,4})$"
)

# Stored image-tweak value / upload filename (batch 4): the server-generated
# sha256 name. Saves only ever produce png/jpg/gif/webp; the read-side regex
# additionally tolerates the legacy-equivalent "jpeg" spelling.
_UPLOAD_FILENAME_RE = re.compile(r"^[a-f0-9]{64}\.(png|jpg|jpeg|gif|webp)$")

# Palette/apply token names allowed without the ``--`` prefix: the accent
# family, the documented design tokens, and pack-scoped ``pack-*`` customs.
_DESIGN_TOKENS = frozenset({
    "accent", "accent-hover", "accent-bg", "accent-bg-strong", "accent-text",
    "accent2", "accent3", "accent-contrast", "accent-rgb",
    "bg", "surface", "surface2", "surface-subtle", "text", "text2", "muted",
    "border", "border2", "hover-bg", "code-bg", "code-text",
    "sidebar", "sidebar-text", "user-bubble", "assistant-bubble",
    "success", "warning", "danger", "info", "link",
})

# MIME map for pack assets (subset of routes._STATIC_MIME per the contract).
_MIME = {
    "css": "text/css",
    "js": "application/javascript",
    "json": "application/json",
    "svg": "image/svg+xml",
    "png": "image/png",
    "ico": "image/x-icon",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff2": "font/woff2",
}
_TEXT_MIME = {"text/css", "application/javascript", "image/svg+xml"}

_SCHEMES = ("auto", "light", "dark")
# batch 4: "image" tweaks carry a server-generated upload filename as their
# value (no min/max/step/options/default — the upload IS the value source).
_TWEAK_TYPES = ("range", "select", "toggle", "color", "image")
# batch 3: how the frontend applies a pack. "pack" (default) layers the pack's
# palette/CSS under data-skin="pack:<key>"; "css-key" marks a pack whose
# styling already ships in the main stylesheet keyed by
# :root[data-skin="<key>"] — the frontend then sets data-skin="<key>"
# directly. The server validates the enum ONLY: which keys have CSS is a
# frontend/frontend-stylesheet concern, deliberately not key-restricted here.
_APPLY_MODES = ("pack", "css-key")
# batch 3: localized text objects {"<locale>": "<text>"} — e.g. en, zh,
# zh-Hant. Locale keys must match this regex; at most 8 entries are kept.
_LOCALE_RE = re.compile(r"^[a-z]{2}(-[A-Za-z0-9]{2,8})?$")
_MAX_LOCALE_ENTRIES = 8


class _ManifestError(Exception):
    """A manifest violated the schema; the pack is skipped with a warning."""


# ── shared field validators ─────────────────────────────────────────────────


def _is_valid_token(name) -> bool:
    return isinstance(name, str) and (
        name in _DESIGN_TOKENS or _PACK_TOKEN_RE.fullmatch(name) is not None
    )


def _is_safe_css_value(value) -> bool:
    """Palette/preview colour value gate. Unsafe values drop the TOKEN, not
    the pack — mirrors the client sanitizer this is a port of."""
    if not isinstance(value, str) or not value or len(value) > _VALUE_MAX_CHARS:
        return False
    if "url(" in value.lower() or any(ch in value for ch in ";{}"):
        return False
    return _SAFE_VALUE_RE.fullmatch(value) is not None


def _is_safe_manifest_subpath(rel) -> bool:
    """Relative subpath inside a pack dir: no leading '/', no absolute, no
    '..'/'.' or empty segment, no backslash, no NUL. (Manifest subpath rules;
    asset serving additionally rejects dotfiles.)"""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
        return False
    if rel.startswith("/") or Path(rel).is_absolute():
        return False
    return all(segment not in ("", ".", "..") for segment in rel.split("/"))


def _is_safe_asset_subpath(rel) -> bool:
    """_is_safe_manifest_subpath plus the dotfile rule: a hidden file must
    never become reachable through the asset route."""
    if not _is_safe_manifest_subpath(rel):
        return False
    return all(not segment.startswith(".") for segment in rel.split("/"))


def _normalize_locale_map(raw, max_len: int) -> dict | None:
    """Localized-text object form: ``{"<locale>": "<text>"}`` (batch 3).

    Returns the kept entries — possibly ``{}`` when every entry was invalid —
    or ``None`` when ``raw`` is not an object, in which case the caller
    applies its existing plain-string rules. Per-entry dropping mirrors the
    module's other lenient fields: a locale key must match
    ``^[a-z]{2}(-[A-Za-z0-9]{2,8})?$`` and its value must be a non-empty
    string within the field's length limit; entries beyond the 8-entry cap
    drop like invalid ones (insertion order, deterministic)."""
    if not isinstance(raw, dict):
        return None
    kept: dict[str, str] = {}
    for locale, text in raw.items():
        if len(kept) >= _MAX_LOCALE_ENTRIES:
            logger.warning(
                "skin pack localized entries beyond %d dropped", _MAX_LOCALE_ENTRIES
            )
            break
        if not isinstance(locale, str) or _LOCALE_RE.fullmatch(locale) is None:
            logger.warning(
                "skin pack localized entry %r dropped: locale must match"
                " ^[a-z]{2}(-[A-Za-z0-9]{2,8})?$",
                locale,
            )
            continue
        if not isinstance(text, str) or not 1 <= len(text) <= max_len:
            logger.warning(
                "skin pack localized entry %r dropped: value must be a string"
                " of 1-%d characters",
                locale,
                max_len,
            )
            continue
        kept[locale] = text
    return kept


# ── manifest loading + validation ───────────────────────────────────────────


def _load_and_validate_manifest(pack_dir: Path) -> tuple[dict | None, str | None]:
    """Read and validate ``pack_dir/manifest.json``.

    Returns ``(normalized_pack_dict, None)`` on success or ``(None, reason)``
    when the pack must be skipped. Never raises for bad content — the caller
    logs the reason and moves on to the next candidate directory.
    """
    manifest_path = pack_dir / "manifest.json"
    try:
        if manifest_path.stat().st_size > _MANIFEST_MAX_BYTES:
            return None, "manifest.json exceeds the 64KB limit"
        raw = manifest_path.read_bytes()
    except OSError as exc:
        return None, f"manifest.json unreadable: {exc}"
    if len(raw) > _MANIFEST_MAX_BYTES:
        return None, "manifest.json exceeds the 64KB limit"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"manifest.json is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "manifest root must be a JSON object"
    try:
        return _normalize_manifest(data, pack_dir.name), None
    except _ManifestError as exc:
        return None, str(exc)


def _normalize_manifest(data: dict, dirname: str) -> dict:
    schema_version = data.get("schemaVersion")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
        raise _ManifestError("schemaVersion must be the integer 1")
    key = data.get("key")
    if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
        raise _ManifestError("key must match ^[a-z0-9][a-z0-9-]{0,31}$")
    if key != dirname:
        raise _ManifestError(f"key {key!r} must equal the pack directory name {dirname!r}")
    raw_name = data.get("name")
    name_map = _normalize_locale_map(raw_name, _NAME_MAX)
    if name_map is not None:
        if not name_map:
            # a localized name whose every entry was dropped behaves like a
            # missing/invalid name: the pack is rejected
            raise _ManifestError("name localized object has no valid entries")
        name = name_map
    else:
        name = _required_text(data, "name", _NAME_MAX)
    version = data.get("version")
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise _ManifestError("version must match ^[0-9A-Za-z.+-]{1,32}$")
    scheme = data.get("scheme", "auto")
    if scheme not in _SCHEMES:
        raise _ManifestError("scheme must be one of auto|light|dark")
    apply_mode = data.get("applyMode", "pack")
    if apply_mode not in _APPLY_MODES:
        logger.warning(
            "skin pack applyMode %r dropped: must be one of pack|css-key", apply_mode
        )
        apply_mode = "pack"
    description_map = _normalize_locale_map(data.get("description"), _DESCRIPTION_MAX)
    if description_map is not None:
        # a localized description emptied by entry drops falls back to the
        # field's absence behaviour ("")
        description: str | dict = description_map or ""
    else:
        description = _optional_text(data, "description", _DESCRIPTION_MAX)
    return {
        "key": key,
        "name": name,
        "version": version,
        "author": _optional_text(data, "author", _AUTHOR_MAX),
        "description": description,
        "scheme": scheme,
        "applyMode": apply_mode,
        "preview": _normalize_preview(data.get("preview")),
        "palette": _normalize_palette(data.get("palette")),
        "extraCss": _normalize_extra_css(data.get("extraCss")),
        "scripts": _normalize_scripts(data.get("scripts")),
        "tweaks": _normalize_tweaks(data.get("tweaks")),
        "icons": _normalize_icons(data.get("icons")),
        "thinking": _normalize_thinking(data.get("thinking")),
    }


def _required_text(data: dict, field: str, max_len: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        raise _ManifestError(f"{field} must be a string of 1-{max_len} characters")
    return value


def _optional_text(data: dict, field: str, max_len: int) -> str:
    value = data.get(field)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > max_len:
        raise _ManifestError(f"{field} must be a string of at most {max_len} characters")
    return value


def _normalize_preview(raw) -> dict:
    if raw is None:
        return {"colors": []}
    if not isinstance(raw, dict):
        raise _ManifestError("preview must be an object")
    colors = raw.get("colors")
    if colors is None:
        return {"colors": []}
    if not isinstance(colors, list):
        raise _ManifestError("preview.colors must be a list")
    safe = [c for c in colors if _is_safe_css_value(c)]
    return {"colors": safe[:_MAX_PREVIEW_COLORS]}


def _normalize_palette(raw) -> dict:
    if raw is None:
        return {"light": {}, "dark": {}}
    if not isinstance(raw, dict):
        raise _ManifestError("palette must be an object")
    light = _normalize_palette_side(raw.get("light"), "palette.light")
    dark = _normalize_palette_side(raw.get("dark"), "palette.dark")
    if not light and dark:
        light = dict(dark)
    elif not dark and light:
        dark = dict(light)
    return {"light": light, "dark": dark}


def _normalize_palette_side(raw, field: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _ManifestError(f"{field} must be an object")
    side = {}
    for token, value in raw.items():
        # Unknown token keys and unsafe values drop the token, never the pack.
        if _is_valid_token(token) and _is_safe_css_value(value):
            side[token] = value
    return side


def _normalize_extra_css(raw):
    if raw is None:
        return None
    if not _is_safe_manifest_subpath(raw):
        raise _ManifestError("extraCss must be a safe relative path inside the pack")
    return raw


def _normalize_scripts(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > _MAX_SCRIPTS:
        raise _ManifestError(f"scripts must be an array of at most {_MAX_SCRIPTS} relative paths")
    for item in raw:
        if not _is_safe_manifest_subpath(item):
            raise _ManifestError("scripts entries must be safe relative paths inside the pack")
    return list(raw)


def _normalize_tweaks(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _ManifestError("tweaks must be an array")
    if len(raw) > _MAX_TWEAKS:
        raise _ManifestError(f"tweaks accepts at most {_MAX_TWEAKS} entries")
    tweaks = []
    seen_ids: set[str] = set()
    for entry in raw:
        tweak = _normalize_tweak(entry, seen_ids)
        if tweak is None:
            continue
        seen_ids.add(tweak["id"])
        tweaks.append(tweak)
    return tweaks


def _normalize_tweak(entry, seen_ids: set) -> dict | None:
    """One tweak, or ``None`` when the tweak is dropped (batch 3: a localized
    label whose every entry was invalid — the pack survives without it)."""
    if not isinstance(entry, dict):
        raise _ManifestError("each tweak must be an object")
    tweak_id = entry.get("id")
    if not isinstance(tweak_id, str) or _TWEAK_ID_RE.fullmatch(tweak_id) is None:
        raise _ManifestError("tweak id must match ^[a-z0-9-]{1,32}$")
    if tweak_id in seen_ids:
        raise _ManifestError(f"duplicate tweak id {tweak_id!r}")
    raw_label = entry.get("label")
    label_map = _normalize_locale_map(raw_label, _NAME_MAX)
    if label_map is not None:
        if not label_map:
            logger.warning(
                "skin pack tweak %r dropped: label localized object has no valid entries",
                tweak_id,
            )
            return None
        label: str | dict = label_map
    else:
        if not isinstance(raw_label, str) or not 1 <= len(raw_label) <= _NAME_MAX:
            raise _ManifestError("tweak label must be a string of 1-40 characters")
        label = raw_label
    tweak_type = entry.get("type")
    if tweak_type not in _TWEAK_TYPES:
        raise _ManifestError("tweak type must be one of range|select|toggle|color|image")
    if tweak_type == "image":
        return _normalize_image_tweak(entry, tweak_id, label)
    tweak = {
        "id": tweak_id,
        "label": label,
        "type": tweak_type,
        "apply": _normalize_tweak_apply(entry.get("apply"), tweak_type),
    }
    match tweak_type:
        case "range":
            tweak.update(_range_fields(entry))
        case "select":
            tweak.update(_select_fields(entry))
        case "toggle":
            default = entry.get("default")
            if not isinstance(default, bool):
                raise _ManifestError("toggle tweak default must be a boolean")
            tweak["default"] = default
        case "color":
            default = entry.get("default")
            if not isinstance(default, str) or _HEX_COLOR_RE.fullmatch(default) is None:
                raise _ManifestError("color tweak default must match ^#[0-9a-fA-F]{3,8}$")
            tweak["default"] = default
    return tweak


def _normalize_image_tweak(entry: dict, tweak_id: str, label) -> dict | None:
    """Image tweak (batch 4), or ``None`` when the tweak is dropped.

    ``apply`` must be exactly ``{"var": <token>}``: the value is a
    server-generated upload filename the frontend consumes whole, so the
    template (CSS composition) and class forms are meaningless for images —
    any other shape drops the tweak with a warning, never the pack. The
    range/select/toggle fields (min/max/step/options) and ``default`` are not
    part of the image contract; ``default`` is tolerated-and-ignored when
    present (an image tweak has no default — an absent value means no image).
    """
    raw_apply = entry.get("apply")
    if (
        not isinstance(raw_apply, dict)
        or frozenset(raw_apply) != {"var"}
        or not _is_valid_token(raw_apply["var"])
    ):
        logger.warning(
            "skin pack image tweak %r dropped: apply must be exactly"
            ' {"var": <token>}',
            tweak_id,
        )
        return None
    return {
        "id": tweak_id,
        "label": label,
        "type": "image",
        "apply": {"var": raw_apply["var"]},
    }


def _range_fields(entry: dict) -> dict:
    numbers = {}
    for field in ("min", "max", "step", "default"):
        value = entry.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _ManifestError(f"range tweak {field} must be a number")
        numbers[field] = value
    low, high, step, default = (numbers[f] for f in ("min", "max", "step", "default"))
    if not low < high:
        raise _ManifestError("range tweak requires min < max")
    if step <= 0:
        raise _ManifestError("range tweak requires step > 0")
    return {"min": low, "max": high, "step": step, "default": min(max(default, low), high)}


def _select_fields(entry: dict) -> dict:
    raw_options = entry.get("options")
    if not isinstance(raw_options, list) or not 1 <= len(raw_options) <= _SELECT_MAX_OPTIONS:
        raise _ManifestError(f"select tweak options must be a list of 1-{_SELECT_MAX_OPTIONS} entries")
    options = []
    values = set()
    for option in raw_options:
        if not isinstance(option, dict):
            raise _ManifestError("select tweak options must be objects")
        value, raw_label = option.get("value"), option.get("label")
        if not isinstance(value, str) or _SELECT_VALUE_RE.fullmatch(value) is None:
            raise _ManifestError("select option value must match ^[A-Za-z0-9._-]{1,32}$")
        label_map = _normalize_locale_map(raw_label, _NAME_MAX)
        if label_map is not None:
            if not label_map:
                # batch 3: an emptied localized label drops the option (the
                # pack survives); if that option was the default, the select
                # default check below rejects the pack loudly
                logger.warning(
                    "skin pack select option %r dropped: label localized object"
                    " has no valid entries",
                    value,
                )
                continue
            label: str | dict = label_map
        else:
            if not isinstance(raw_label, str) or not raw_label:
                raise _ManifestError("select option label must be a non-empty string")
            label = raw_label
        values.add(value)
        options.append({"value": value, "label": label})
    default = entry.get("default")
    if default not in values:
        raise _ManifestError("select tweak default must be one of the option values")
    return {"options": options, "default": default}


def _normalize_tweak_apply(raw, tweak_type: str) -> dict:
    """``apply`` is exactly one of ``{var}``, ``{var, template}`` or — for
    toggle tweaks only — ``{class}``; key-set dispatch rejects every other
    shape including combined forms."""
    if not isinstance(raw, dict):
        raise _ManifestError("tweak apply must be an object")
    keys = frozenset(raw)
    if keys == {"class"}:
        if tweak_type != "toggle":
            raise _ManifestError("class apply is allowed only on toggle tweaks")
        css_class = raw["class"]
        if not isinstance(css_class, str) or _CLASS_RE.fullmatch(css_class) is None:
            raise _ManifestError("apply class must match ^pack-[a-z0-9-]{1,32}$")
        return {"class": css_class}
    token = raw.get("var")
    if not _is_valid_token(token):
        raise _ManifestError("apply var must be a valid palette token name")
    if keys == {"var"}:
        return {"var": token}
    if keys != {"var", "template"}:
        raise _ManifestError(
            "tweak apply must be exactly one of {var}, {var, template} or {class}"
        )
    template = raw["template"]
    if not isinstance(template, str) or len(template) > _TEMPLATE_MAX:
        raise _ManifestError(f"apply template must be a string of at most {_TEMPLATE_MAX} characters")
    if "{value}" not in template:
        raise _ManifestError("apply template must contain {value}")
    body = template.replace("{value}", "")
    if _TEMPLATE_BODY_RE.fullmatch(body) is None or "url(" in template.lower():
        raise _ManifestError("apply template contains disallowed characters")
    return {"var": token, "template": template}


# icons keys (skin-pack batch 2): every value is a relative subpath inside
# the pack dir, served same-origin under /api/skins/<key>/assets/<rel>.
_ICON_KEYS = (
    "favicon",
    "favicon32",
    "favicon192",
    "favicon512",
    "appleTouch",
    "faviconIco",
    "logoSvg",
)
_THINKING_MODES = ("gif", "css", "none")
_THINKING_SIZE_MIN = 8
_THINKING_SIZE_MAX = 128


def _normalize_icons(raw) -> dict:
    """icons: known keys only, each a safe relative subpath inside the pack
    (the extraCss rules plus the dotfile rule the asset route enforces, so a
    validated value is always servable). An invalid entry drops that ENTRY
    with a warning — never the pack."""
    if not isinstance(raw, dict):
        return {}
    icons = {}
    for icon_key in _ICON_KEYS:
        value = raw.get(icon_key)
        if value is None:
            continue
        if _is_safe_asset_subpath(value):
            icons[icon_key] = value
        else:
            logger.warning(
                "skin pack icons.%s dropped: must be a safe relative path inside the pack",
                icon_key,
            )
    return icons


def _normalize_thinking(raw) -> dict:
    """thinking: mode enum-checked (gif|css|none, default none).

    The asset path the mode requires must itself be a safe subpath; without
    it the mode is unusable, so the thinking replacement collapses to
    ``{"mode": "none"}`` (the mode entry is the invalid one — keeping
    ``mode: gif`` with no reachable gif would ship a broken indicator).
    ``size`` (gif mode only) must be an int and is clamped into 8..128.
    Unknown keys are dropped."""
    if not isinstance(raw, dict):
        return {"mode": "none"}
    mode = raw.get("mode", "none")
    if mode not in _THINKING_MODES:
        logger.warning(
            "skin pack thinking.mode %r dropped: must be one of gif|css|none", mode
        )
        mode = "none"
    if mode == "none":
        return {"mode": "none"}
    asset_key = "gif" if mode == "gif" else "css"
    asset = raw.get(asset_key)
    if not _is_safe_asset_subpath(asset):
        logger.warning(
            "skin pack thinking mode=%s dropped: %s must be a safe relative path inside the pack",
            mode,
            asset_key,
        )
        return {"mode": "none"}
    thinking = {"mode": mode, asset_key: asset}
    if mode == "gif":
        size = raw.get("size")
        if size is None:
            pass
        elif isinstance(size, bool) or not isinstance(size, int):
            logger.warning("skin pack thinking.size dropped: must be an integer")
        else:
            thinking["size"] = min(max(size, _THINKING_SIZE_MIN), _THINKING_SIZE_MAX)
    return thinking


# ── discovery ───────────────────────────────────────────────────────────────
# allow: SIZE_OK — single-module contract frozen by the skin-pack feature plan
# (W1 public API + manifest schema); splitting it would move the contract.


def _default_builtin_root() -> Path:
    from api.config import get_static_root  # lazy: no api.* at module scope

    return get_static_root() / "skins"


def _default_user_root() -> Path:
    from api.profiles import get_active_profile_name, get_hermes_home_for_profile

    return get_hermes_home_for_profile(get_active_profile_name()) / "skins"


def _iter_packs_from_root(root: Path, origin: str):
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        normalized, error = _load_and_validate_manifest(entry)
        if normalized is None:
            logger.warning("skin pack %s skipped: %s", entry, error)
            continue
        normalized["origin"] = origin
        normalized["dir"] = entry
        normalized["shadows"] = False
        yield normalized


def discover_skin_packs(builtin_root=None, user_root=None) -> dict[str, dict]:
    """Discover skin packs across the two roots, key → normalized pack dict.

    ``None`` roots resolve lazily to the real locations (repo ``static/skins``
    and the active profile's ``$HERMES_HOME/skins``). Invalid packs are
    skipped with a warning; a user pack shadows the builtin pack with the
    same key.
    """
    builtin = Path(builtin_root) if builtin_root is not None else _default_builtin_root()
    user = Path(user_root) if user_root is not None else _default_user_root()
    packs: dict[str, dict] = {}
    for pack in _iter_packs_from_root(builtin, "builtin"):
        packs[pack["key"]] = pack
    for pack in _iter_packs_from_root(user, "user"):
        existing = packs.get(pack["key"])
        if existing is not None and existing["dir"] == pack["dir"]:
            continue  # both roots point at the same directory
        if existing is not None:
            pack["shadows"] = True
        packs[pack["key"]] = pack
    return packs


# ── settings normalisation (frozen contract for W2/W3) ─────────────────────


def normalize_skin_pack_setting(raw, packs: dict) -> str:
    """The selected pack key, or "" when it is not a discovered pack."""
    if isinstance(raw, str) and raw in packs:
        return raw
    return ""


def active_skin_pack(settings, packs: dict) -> dict | None:
    """The pack selected by the ``skin_pack`` setting, or None.

    ``settings`` is a loaded settings dict (``api.config.load_settings()``).
    The stored key is normalized against the discovered packs, so a stale
    key — pack removed, renamed, or never valid — resolves to None instead
    of a ghost entry. Callers serving pre-auth traffic wrap this in their
    own fail-safe (settings/discovery errors are theirs to swallow)."""
    raw = settings.get("skin_pack") if isinstance(settings, dict) else None
    key = normalize_skin_pack_setting(raw, packs)
    return packs.get(key) if key else None


def pack_dir_keys(builtin_root=None, user_root=None) -> set:
    """Keys whose pack DIRECTORY exists in either root, manifest validity aside.

    ``normalize_skin_tweaks`` uses this to tell a pack that was uninstalled
    (directory gone → stored tweaks are dropped) from one whose manifest
    merely fails validation right now (directory present → tweaks are kept
    verbatim so a transient failure cannot erase the user's data). Never
    raises; an unreadable root simply contributes no keys.
    """
    keys: set = set()
    try:
        builtin = Path(builtin_root) if builtin_root is not None else _default_builtin_root()
        user = Path(user_root) if user_root is not None else _default_user_root()
    except Exception:
        return keys
    for root in (builtin, user):
        try:
            for entry in os.scandir(root):
                if entry.is_dir():
                    keys.add(entry.name)
        except OSError:
            continue
    return keys


def normalize_skin_tweaks(raw, packs: dict, dir_keys=None) -> dict:
    """Sanitize stored ``skin_pack_tweaks`` against the discovered packs.

    Unknown packs and tweak ids are dropped; range values are clamped into
    [min, max]; select values are coerced to an option value (falling back to
    the tweak default); toggles are coerced to bool; colour values must match
    the hex regex. Results over 32 packs, over 32 tweaks in one pack, or over
    16KB serialized are rejected wholesale by returning {}.

    A pack missing from ``packs`` whose directory still exists (listed in
    ``dir_keys``) keeps its stored values VERBATIM: a manifest that
    transiently fails validation (mid-edit, validator regression) must not
    erase the user's tweak data — only a pack whose directory is gone drops
    its entries. The active ``skin_pack`` key itself is NOT preserved this
    way (an undiscoverable pack cannot be applied), but the tweaks survive
    for the moment the pack validates again.
    """
    if not isinstance(raw, dict):
        return {}
    preserved = dir_keys if isinstance(dir_keys, (set, frozenset)) else None
    result: dict[str, dict] = {}
    for pack_key, tweak_values in raw.items():
        if not isinstance(tweak_values, dict):
            continue
        pack = packs.get(pack_key) if isinstance(pack_key, str) else None
        if pack is None:
            if (
                preserved is not None
                and isinstance(pack_key, str)
                and pack_key in preserved
            ):
                result[pack_key] = dict(tweak_values)
            continue
        known = {t["id"]: t for t in pack.get("tweaks", [])}
        kept = {}
        for tweak_id, value in tweak_values.items():
            tweak = known.get(tweak_id) if isinstance(tweak_id, str) else None
            if tweak is None:
                continue
            ok, normalized_value = _normalize_tweak_value(tweak, value)
            if ok:
                kept[tweak_id] = normalized_value
        if kept:
            result[pack_key] = kept
    if len(result) > _RESULT_MAX_PACKS or any(
        len(values) > _RESULT_MAX_TWEAKS_PER_PACK for values in result.values()
    ):
        return {}
    if len(json.dumps(result)) > _RESULT_MAX_JSON_BYTES:
        return {}
    return result


def _normalize_tweak_value(tweak: dict, value) -> tuple[bool, object]:
    match tweak["type"]:
        case "range":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False, None
            return True, min(max(value, tweak["min"]), tweak["max"])
        case "select":
            if isinstance(value, str) and value in {o["value"] for o in tweak["options"]}:
                return True, value
            return True, tweak["default"]
        case "toggle":
            return True, bool(value)
        case "color":
            if isinstance(value, str) and _HEX_COLOR_RE.fullmatch(value):
                return True, value
            return False, None
        case "image":
            # only a server-generated upload filename is a valid stored
            # value; anything else (empty/None included) drops the entry —
            # absent simply means "no image uploaded"
            if isinstance(value, str) and _UPLOAD_FILENAME_RE.fullmatch(value):
                return True, value
            return False, None


def normalize_skin_script_consents(raw, packs: dict) -> dict:
    """Booleans only, for discovered packs; everything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and key in packs and isinstance(value, bool)
    }


# ── asset resolution + serving ──────────────────────────────────────────────


def resolve_pack_asset(packs: dict, key, rel) -> tuple[Path, dict] | None:
    """Resolve ``rel`` inside the pack's directory → (path, pack), or None.

    ``rel`` must be a safe relative subpath (no leading '/', no '..' segment,
    no backslash, no dotfiles). The final ``resolve()`` plus
    ``relative_to(pack_dir)`` containment check also rejects symlinks and
    absolute escapes; only real files resolve.
    """
    if not isinstance(key, str) or not isinstance(rel, str):
        return None
    pack = packs.get(key)
    if pack is None:
        return None
    if not _is_safe_asset_subpath(rel):
        return None
    pack_dir = Path(pack["dir"]).resolve()
    try:
        path = (pack_dir / rel).resolve()
        path.relative_to(pack_dir)
    except (OSError, RuntimeError, ValueError):
        return None
    if not path.is_file():
        return None
    return path, pack


def serve_pack_asset(handler, packs: dict, key, rel_path) -> bool:
    """Serve a pack asset on ``handler``; always True (handled or 404).

    Mirrors ``api.routes._serve_static`` / ``api.extensions.serve_extension_static``:
    mime map, ``Cache-Control: no-cache``, weak ETag from (size, mtime_ns),
    If-None-Match → 304, and a path-leak-free JSON 404 on any failure.
    """
    from api.helpers import _security_headers, j  # lazy: mirrors api.extensions

    resolved = resolve_pack_asset(packs, key, rel_path)
    if resolved is None:
        j(handler, {"error": "not found"}, status=404)
        return True
    path, _pack = resolved
    try:
        st = path.stat()
        raw = path.read_bytes()
    except OSError:
        j(handler, {"error": "not found"}, status=404)
        return True
    mime = _MIME.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    content_type = f"{mime}; charset=utf-8" if mime in _TEXT_MIME else mime
    etag = f'W/"{st.st_size:x}-{st.st_mtime_ns:x}"'
    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        return True
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", "no-cache")
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(raw)
    return True


# ── image-tweak uploads (batch 4) ────────────────────────────────────────────

# Accepted upload content types → the extension the stored filename carries.
# SVG is deliberately absent (see the module docstring: uploaded SVG served
# same-origin as a directly-navigated document is a stored-XSS surface the
# admin-trust pack-asset route does not have).
_UPLOAD_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_UPLOAD_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _upload_magic_matches(data: bytes, content_type: str) -> bool:
    match content_type:
        case "image/png":
            return data[:8] == b"\x89PNG\r\n\x1a\n"
        case "image/jpeg":
            return data[:3] == b"\xff\xd8\xff"
        case "image/gif":
            return data[:6] in (b"GIF87a", b"GIF89a")
        case "image/webp":
            return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _skin_upload_root(pack_key) -> Path:
    """The per-pack upload directory ``<STATE_DIR>/skin_uploads/<pack_key>``.

    Raises ``ValueError`` unless ``pack_key`` matches the pack key regex —
    callers translate that into their own error convention (a save reason or
    a resolve None) so a bad key can never reach path building.
    """
    from api.config import STATE_DIR  # lazy: no api.* at module scope

    if not isinstance(pack_key, str) or _KEY_RE.fullmatch(pack_key) is None:
        raise ValueError("pack key must match ^[a-z0-9][a-z0-9-]{0,31}$")
    return Path(STATE_DIR) / "skin_uploads" / pack_key


def _evict_oldest_uploads(root: Path, cap: int = _UPLOAD_MAX_FILES_PER_PACK) -> None:
    """Delete the oldest files (by mtime, name as tiebreak) until ``root``
    holds at most ``cap`` regular files. Best effort: an unlink failure is
    logged and skipped, never raised."""
    try:
        files = [entry for entry in root.iterdir() if entry.is_file()]
    except OSError:
        return
    if len(files) <= cap:
        return
    ranked = sorted(files, key=lambda entry: (entry.stat().st_mtime, entry.name))
    for entry in ranked[: len(files) - cap]:
        try:
            entry.unlink()
        except OSError:
            logger.warning("skin upload eviction failed for %s", entry)


def save_skin_pack_upload(pack_key, data: bytes, content_type: str) -> tuple[str | None, str | None]:
    """Store an uploaded tweak image for ``pack_key``.

    Returns ``(filename, None)`` on success or ``(None, reason)`` on
    rejection. The filename is ``<sha256hex>.<ext>`` of the bytes, so repeat
    uploads dedupe to the same name (the atomic rewrite refreshes its mtime,
    keeping a still-referenced image recent for eviction). Validation: the
    content type must be one of png/jpeg/gif/webp, the payload's magic bytes
    must match the declared type, and the size must be 64B..2MB. The per-pack
    directory is capped at 32 files; the oldest are evicted to stay under it.
    """
    ext = (
        _UPLOAD_CONTENT_TYPES.get(content_type)
        if isinstance(content_type, str)
        else None
    )
    if ext is None:
        return None, "content type must be one of image/png, image/jpeg, image/gif, image/webp"
    payload = bytes(data) if isinstance(data, (bytes, bytearray)) else None
    if payload is None or len(payload) < _UPLOAD_MIN_BYTES:
        return None, f"upload too small (min {_UPLOAD_MIN_BYTES} bytes)"
    if len(payload) > _UPLOAD_MAX_BYTES:
        return None, f"upload too large (max {_UPLOAD_MAX_BYTES} bytes)"
    if not _upload_magic_matches(payload, content_type):
        return None, "uploaded bytes do not match the declared content type"
    try:
        root = _skin_upload_root(pack_key)
    except ValueError:
        return None, "invalid pack key"
    filename = f"{hashlib.sha256(payload).hexdigest()}.{ext}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=root, prefix=".tmp-upload-")
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(payload)
            os.replace(tmp_name, root / filename)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.warning("skin pack upload store failed for %r: %s", pack_key, exc)
        return None, "upload could not be stored"
    _evict_oldest_uploads(root)
    return filename, None


def resolve_skin_upload(pack_key, filename) -> Path | None:
    """Resolve a stored upload filename → its path, or None.

    ``filename`` must match the server-generated sha256-name regex; the final
    ``resolve()`` plus ``relative_to()`` containment (mirroring
    ``resolve_pack_asset``) rejects symlink and traversal escapes. Only real
    files resolve.
    """
    if not isinstance(filename, str) or _UPLOAD_FILENAME_RE.fullmatch(filename) is None:
        return None
    try:
        root = _skin_upload_root(pack_key).resolve()
    except ValueError:
        return None
    try:
        path = (root / filename).resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not path.is_file():
        return None
    return path


def serve_skin_upload(handler, pack_key, filename) -> bool:
    """Serve a stored skin-pack upload on ``handler``; always True (handled
    or 404).

    Mirrors ``serve_pack_asset`` semantics exactly: ``Cache-Control:
    no-cache``, weak ETag from (size, mtime_ns), If-None-Match → 304, the
    correct Content-Type from the extension, and a uniform path-leak-free
    JSON 404 on any failure. Only uploadable types can ever resolve — SVG
    is not among them (see ``_UPLOAD_CONTENT_TYPES``).
    """
    from api.helpers import _security_headers, j  # lazy: mirrors serve_pack_asset

    path = resolve_skin_upload(pack_key, filename)
    if path is None:
        j(handler, {"error": "not found"}, status=404)
        return True
    try:
        st = path.stat()
        raw = path.read_bytes()
    except OSError:
        j(handler, {"error": "not found"}, status=404)
        return True
    mime = _UPLOAD_MIME.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    etag = f'W/"{st.st_size:x}-{st.st_mtime_ns:x}"'
    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        return True
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", "no-cache")
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(raw)
    return True
