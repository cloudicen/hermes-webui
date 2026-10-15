"""Skin pack discovery + manifest validation tests (skin-pack feature, W1).

``api/skinpacks.py`` owns pack discovery over two roots (builtin
``static/skins/``, user ``$HERMES_HOME/skins/``), manifest validation, and
asset resolve/serve. These tests pin the frozen contract W2/W3 build on:

- user packs shadow builtin packs with the same key (re-resolve on removal)
- one invalid pack never breaks discovery of its neighbours
- palette/tweak violations reject the pack; unsafe VALUES drop the token only
- icons/thinking are validated strictly (safe pack-relative subpaths, enum
  thinking modes, clamped size); invalid entries drop the entry, not the pack
- asset resolution is sandboxed to the pack directory (dotfiles, traversal,
  absolute paths and symlink escapes all rejected)
- serving mirrors the repo's ``_serve_static`` / ``serve_extension_static``
  patterns: mime map, ``Cache-Control: no-cache``, weak ETag, If-None-Match
  304, and a path-leak-free 404 JSON body
"""

import json
import shutil

from api.skinpacks import (
    discover_skin_packs,
    normalize_skin_pack_setting,
    normalize_skin_script_consents,
    normalize_skin_tweaks,
    resolve_pack_asset,
)


class FakeHandler:
    """Mirror of the FakeHandler in test_extension_hooks.py, plus configurable
    request headers so If-None-Match can be exercised."""

    def __init__(self, headers=None):
        self.status = None
        self.headers = headers if headers is not None else {}
        self.sent_headers = []
        self.body = bytearray()
        self.wfile = self

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent_headers.append((name, value))

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data)

    def header(self, name):
        for key, value in self.sent_headers:
            if key.lower() == name.lower():
                return value
        return None


def _manifest(**overrides):
    """A fully-populated valid manifest; ``overrides`` replace top-level keys."""
    manifest = {
        "schemaVersion": 1,
        "key": "test-pack",
        "name": "Test Pack",
        "version": "1.0.0",
        "author": "Someone",
        "description": "A test pack",
        "scheme": "auto",
        "preview": {"colors": ["#ff5500", "rgb(10, 20, 30)"]},
        "palette": {
            "light": {"accent": "#0055ff", "pack-radius": "8px"},
            "dark": {"accent": "#3388ff"},
        },
        "extraCss": "extra.css",
        "scripts": ["pack.js"],
        "tweaks": [
            {
                "id": "radius",
                "label": "Radius",
                "type": "range",
                "min": 0,
                "max": 24,
                "step": 1,
                "default": 8,
                "apply": {"var": "pack-radius", "template": "{value}px"},
            }
        ],
        "icons": {"favicon": "icons/favicon.svg", "logoSvg": "icons/logo.svg"},
        "thinking": {"mode": "gif", "gif": "anim/thinking.gif", "size": 28},
        "futureUnknownField": {"ignored": True},
    }
    manifest.update(overrides)
    return manifest


def _write_pack(root, key, manifest, files=None):
    """Create root/<key>/manifest.json plus optional extra files."""
    pack_dir = root / key
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, content in (files or {}).items():
        target = pack_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pack_dir


def _discover(tmp_path, builtin_packs=(), user_packs=()):
    """Build builtin/user roots under tmp_path and discover over both."""
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(exist_ok=True)
    user.mkdir(exist_ok=True)
    for key, manifest, files in builtin_packs:
        _write_pack(builtin, key, manifest, files)
    for key, manifest, files in user_packs:
        _write_pack(user, key, manifest, files)
    return discover_skin_packs(builtin_root=builtin, user_root=user)


def _select_tweak(**overrides):
    tweak = {
        "id": "density",
        "label": "Density",
        "type": "select",
        "options": [
            {"value": "compact", "label": "Compact"},
            {"value": "cozy", "label": "Cozy"},
        ],
        "default": "cozy",
        "apply": {"var": "pack-density"},
    }
    tweak.update(overrides)
    return tweak


# ── discovery + manifest validation ────────────────────────────────────────


def test_valid_manifest_parses_fully(tmp_path):
    packs = _discover(
        tmp_path,
        builtin_packs=[("test-pack", _manifest(), {"extra.css": "x", "pack.js": "y"})],
    )
    assert set(packs) == {"test-pack"}
    pack = packs["test-pack"]
    assert pack["key"] == "test-pack"
    assert pack["name"] == "Test Pack"
    assert pack["version"] == "1.0.0"
    assert pack["author"] == "Someone"
    assert pack["description"] == "A test pack"
    assert pack["scheme"] == "auto"
    assert pack["preview"]["colors"] == ["#ff5500", "rgb(10, 20, 30)"]
    assert pack["palette"]["light"] == {"accent": "#0055ff", "pack-radius": "8px"}
    assert pack["palette"]["dark"] == {"accent": "#3388ff"}
    assert pack["extraCss"] == "extra.css"
    assert pack["scripts"] == ["pack.js"]
    assert pack["tweaks"][0]["id"] == "radius"
    assert pack["tweaks"][0]["default"] == 8
    # icons/thinking validated strictly since batch 2: safe subpaths + enum
    # modes; unknown keys are dropped
    assert pack["icons"] == {"favicon": "icons/favicon.svg", "logoSvg": "icons/logo.svg"}
    assert pack["thinking"] == {"mode": "gif", "gif": "anim/thinking.gif", "size": 28}
    # unknown top-level fields are ignored, not preserved
    assert "futureUnknownField" not in pack
    assert pack["origin"] == "builtin"
    assert pack["shadows"] is False
    assert pack["dir"] == tmp_path / "builtin" / "test-pack"


def test_minimal_manifest_gets_documented_defaults(tmp_path):
    manifest = {
        "schemaVersion": 1,
        "key": "minimal",
        "name": "Minimal",
        "version": "0.1",
    }
    packs = _discover(tmp_path, builtin_packs=[("minimal", manifest, None)])
    pack = packs["minimal"]
    assert pack["author"] == ""
    assert pack["description"] == ""
    assert pack["scheme"] == "auto"
    assert pack["preview"] == {"colors": []}
    assert pack["palette"] == {"light": {}, "dark": {}}
    assert pack["extraCss"] is None
    assert pack["scripts"] == []
    assert pack["tweaks"] == []
    assert pack["icons"] == {}
    assert pack["thinking"] == {"mode": "none"}


def test_invalid_manifest_skips_pack_but_neighbours_survive(tmp_path):
    """One bad pack must never break discovery of the others."""
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_pack(builtin, "good-pack", _manifest(key="good-pack"))

    # Each case gets a UNIQUE directory so every payload is actually present
    # at discovery time (shared names would overwrite each other). dirname
    # equals the manifest key except for the two intentional mismatches.
    range_tweak = _manifest()["tweaks"][0]
    toggle_tweak = {
        "id": "glow",
        "label": "Glow",
        "type": "toggle",
        "default": True,
        "apply": {"class": "pack-glow"},
    }
    too_big = '{"pad":"' + "a" * 65530 + '"}'
    cases = {
        "bad-json": ("bad-json", "{not json"),
        "root-not-object": ("root-not-object", "[1, 2, 3]"),
        "manifest-over-64kb": ("too-big", too_big),
        "schema-version-2": ("sv2", {**_manifest(key="sv2"), "schemaVersion": 2}),
        "schema-version-string": ("svstr", {**_manifest(key="svstr"), "schemaVersion": "1"}),
        "key-mismatch": ("key-mismatch", _manifest(key="other-name")),
        "key-bad-format": ("Bad_Key", _manifest(key="Bad_Key")),
        "name-missing": (
            "name-missing",
            {k: v for k, v in _manifest(key="name-missing").items() if k != "name"},
        ),
        "name-empty": ("name-empty", _manifest(key="name-empty", name="")),
        "name-too-long": ("name-long", _manifest(key="name-long", name="x" * 41)),
        "version-bad": ("version-bad", _manifest(key="version-bad", version="1.0 beta")),
        "author-too-long": ("author-long", _manifest(key="author-long", author="x" * 61)),
        "scheme-invalid": ("scheme-bad", _manifest(key="scheme-bad", scheme="blue")),
        "palette-not-object": ("palette-bad", _manifest(key="palette-bad", palette="nope")),
        "extra-css-absolute": ("css-abs", _manifest(key="css-abs", extraCss="/etc/passwd")),
        "extra-css-traversal": ("css-trav", _manifest(key="css-trav", extraCss="../x.css")),
        "extra-css-backslash": ("css-bs", _manifest(key="css-bs", extraCss="a\\b.css")),
        "scripts-traversal": ("js-trav", _manifest(key="js-trav", scripts=["../evil.js"])),
        "scripts-too-many": (
            "js-many",
            _manifest(key="js-many", scripts=["a.js", "b.js", "c.js", "d.js", "e.js"]),
        ),
        "tweaks-13-entries": (
            "tw13",
            _manifest(
                key="tw13",
                tweaks=[{**range_tweak, "id": f"t{i}"} for i in range(13)],
            ),
        ),
        "range-min-gt-max": (
            "tw-minmax",
            _manifest(key="tw-minmax", tweaks=[{**range_tweak, "min": 30, "max": 10}]),
        ),
        "range-step-zero": (
            "tw-step",
            _manifest(key="tw-step", tweaks=[{**range_tweak, "step": 0}]),
        ),
        "range-default-non-numeric": (
            "tw-def",
            _manifest(key="tw-def", tweaks=[{**range_tweak, "default": "big"}]),
        ),
        "select-default-not-option": (
            "tw-seldef",
            _manifest(key="tw-seldef", tweaks=[_select_tweak(default="ultra")]),
        ),
        "select-empty-options": (
            "tw-selopt",
            _manifest(key="tw-selopt", tweaks=[_select_tweak(options=[])]),
        ),
        "toggle-default-non-bool": (
            "tw-toggle",
            _manifest(key="tw-toggle", tweaks=[{**toggle_tweak, "default": "yes"}]),
        ),
        "color-default-not-hex": (
            "tw-color",
            _manifest(
                key="tw-color",
                tweaks=[
                    {
                        "id": "hint",
                        "label": "Hint",
                        "type": "color",
                        "default": "red",
                        "apply": {"var": "accent"},
                    }
                ],
            ),
        ),
        "class-apply-on-range": (
            "tw-classrange",
            _manifest(
                key="tw-classrange",
                tweaks=[{**range_tweak, "apply": {"class": "pack-wide"}}],
            ),
        ),
        "class-apply-bad-format": (
            "tw-classbad",
            _manifest(key="tw-classbad", tweaks=[{**toggle_tweak, "apply": {"class": "Wide"}}]),
        ),
        "template-missing-value": (
            "tw-tplvalue",
            _manifest(
                key="tw-tplvalue",
                tweaks=[
                    {**range_tweak, "apply": {"var": "pack-radius", "template": "9px"}}
                ],
            ),
        ),
        "template-bad-charset": (
            "tw-tplcharset",
            _manifest(
                key="tw-tplcharset",
                tweaks=[
                    {
                        **range_tweak,
                        "apply": {"var": "pack-radius", "template": "{value}px; color:red"},
                    }
                ],
            ),
        ),
        "template-url": (
            "tw-tplurl",
            _manifest(
                key="tw-tplurl",
                tweaks=[
                    {**range_tweak, "apply": {"var": "pack-radius", "template": "url({value})"}}
                ],
            ),
        ),
        "apply-var-and-class": (
            "tw-varclass",
            _manifest(
                key="tw-varclass",
                tweaks=[
                    {
                        **range_tweak,
                        "apply": {"var": "pack-radius", "class": "pack-x"},
                    }
                ],
            ),
        ),
        "apply-var-unknown-token": (
            "tw-vartoken",
            _manifest(
                key="tw-vartoken",
                tweaks=[{**range_tweak, "apply": {"var": "not-a-token"}}],
            ),
        ),
        "apply-missing": (
            "tw-noapply",
            _manifest(
                key="tw-noapply",
                tweaks=[{k: v for k, v in range_tweak.items() if k != "apply"}],
            ),
        ),
        "tweak-duplicate-id": (
            "tw-dupid",
            _manifest(key="tw-dupid", tweaks=[range_tweak, _select_tweak(id="radius")]),
        ),
    }

    for dirname, payload in cases.values():
        pack_dir = builtin / dirname
        pack_dir.mkdir()
        if isinstance(payload, str):
            (pack_dir / "manifest.json").write_text(payload, encoding="utf-8")
        else:
            (pack_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    packs = discover_skin_packs(builtin_root=builtin, user_root=tmp_path / "missing")
    assert set(packs) == {"good-pack"}, (
        "every invalid pack above must be skipped without affecting its neighbours"
    )


def test_palette_unsafe_values_drop_token_but_keep_pack(tmp_path):
    manifest = _manifest(
        key="values",
        palette={
            "light": {
                "accent": "url(javascript:alert(1))",
                "border": "10px; } body { display:none",
                "text": "x" * 65,
                "surface": "rgb(1, 2, 3)",
                "muted": "#abc",
            }
        },
    )
    packs = _discover(tmp_path, builtin_packs=[("values", manifest, None)])
    light = packs["values"]["palette"]["light"]
    assert "accent" not in light
    assert "border" not in light
    assert "text" not in light
    assert light["surface"] == "rgb(1, 2, 3)"
    assert light["muted"] == "#abc"
    # the lone light palette is mirrored to dark, minus the dropped tokens
    assert packs["values"]["palette"]["dark"] == {"surface": "rgb(1, 2, 3)", "muted": "#abc"}


def test_lenient_fields_drop_bad_parts_not_the_pack(tmp_path):
    manifest = _manifest(
        key="lenient",
        palette={
            "light": {"not-a-token": "#fff", "pack-radius": "6px", "accent2": "#123456"}
        },
        icons={"favicon": "../evil.svg", "logoSvg": "icons/logo.svg", "weight": 2},
        thinking={"mode": "sparkle", "gif": "anim/thinking.gif"},
    )
    packs = _discover(tmp_path, builtin_packs=[("lenient", manifest, None)])
    pack = packs["lenient"]
    # unknown palette token keys are dropped; custom pack-* tokens survive
    assert pack["palette"]["light"] == {"pack-radius": "6px", "accent2": "#123456"}
    # icons/thinking drop the invalid ENTRY, never the pack: an unsafe icon
    # value and unknown icon keys vanish while the safe value survives, and
    # an unknown thinking mode collapses to the none default
    assert pack["icons"] == {"logoSvg": "icons/logo.svg"}
    assert pack["thinking"] == {"mode": "none"}


def test_single_palette_side_mirrors_to_both(tmp_path):
    dark_only = _manifest(key="mirror-a", palette={"dark": {"accent": "#222222"}})
    packs = _discover(tmp_path, builtin_packs=[("mirror-a", dark_only, None)])
    assert packs["mirror-a"]["palette"]["light"] == {"accent": "#222222"}
    assert packs["mirror-a"]["palette"]["dark"] == {"accent": "#222222"}


def test_user_pack_shadows_builtin_and_re_resolve(tmp_path):
    builtin_pack = _manifest(key="shared", name="Builtin Shared")
    user_pack = _manifest(key="shared", name="User Shared")
    packs = _discover(
        tmp_path,
        builtin_packs=[("shared", builtin_pack, None)],
        user_packs=[("shared", user_pack, None), ("extra", _manifest(key="extra"), None)],
    )
    assert packs["shared"]["origin"] == "user"
    assert packs["shared"]["name"] == "User Shared"
    assert packs["shared"]["shadows"] is True
    assert packs["extra"]["origin"] == "user"
    assert packs["extra"]["shadows"] is False

    # removing the user pack re-resolves the builtin one on the next call
    shutil.rmtree(tmp_path / "user" / "shared")
    packs_again = _discover(
        tmp_path,
        builtin_packs=[("shared", builtin_pack, None)],
        user_packs=[("extra", _manifest(key="extra"), None)],
    )
    assert packs_again["shared"]["origin"] == "builtin"
    assert packs_again["shared"]["name"] == "Builtin Shared"
    assert packs_again["shared"]["shadows"] is False


def test_missing_or_empty_roots_return_empty(tmp_path):
    assert discover_skin_packs(
        builtin_root=tmp_path / "nope", user_root=tmp_path / "nada"
    ) == {}
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "not-a-dir.json").write_text("{}", encoding="utf-8")
    (empty / "no-manifest").mkdir()
    assert discover_skin_packs(builtin_root=empty, user_root=tmp_path / "nope") == {}


# ── settings normalisation ─────────────────────────────────────────────────


def test_normalize_skin_pack_setting(tmp_path):
    packs = _discover(tmp_path, builtin_packs=[("alpha", _manifest(key="alpha"), None)])
    assert normalize_skin_pack_setting("alpha", packs) == "alpha"
    assert normalize_skin_pack_setting("ghost", packs) == ""
    assert normalize_skin_pack_setting(None, packs) == ""
    assert normalize_skin_pack_setting(123, packs) == ""


def _tweak_pack(key):
    """One pack exercising every tweak type."""
    return key, _manifest(
        key=key,
        tweaks=[
            {
                "id": "radius",
                "label": "Radius",
                "type": "range",
                "min": 0,
                "max": 24,
                "step": 1,
                "default": 8,
                "apply": {"var": "pack-radius", "template": "{value}px"},
            },
            _select_tweak(),
            {
                "id": "glow",
                "label": "Glow",
                "type": "toggle",
                "default": False,
                "apply": {"class": "pack-glow"},
            },
            {
                "id": "hint",
                "label": "Hint",
                "type": "color",
                "default": "#aabbcc",
                "apply": {"var": "accent"},
            },
            {
                "id": "ratio",
                "label": "Ratio",
                "type": "range",
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "default": 0.5,
                "apply": {"var": "pack-ratio"},
            },
        ],
    ), None


def test_normalize_skin_tweaks_clamps_coerces_drops(tmp_path):
    packs = _discover(tmp_path, builtin_packs=[_tweak_pack("tw")])
    raw = {
        "tw": {
            "radius": 500,  # clamped into [0, 24]
            "ratio": -3,  # clamped into [0.0, 1.0]
            "density": "ultra",  # not an option → coerced to the tweak default
            "glow": 1,  # coerced to bool True
            "hint": "#aabbcc",  # valid colour passes through
            "unknown-id": 5,  # unknown tweak id dropped
        },
        "ghost": {"radius": 3},  # unknown pack dropped
        "strange": "not-a-dict",  # malformed pack entry dropped
    }
    assert normalize_skin_tweaks(raw, packs) == {
        "tw": {
            "radius": 24,
            "ratio": 0.0,
            "density": "cozy",
            "glow": True,
            "hint": "#aabbcc",
        }
    }

    bad_values = {
        "tw": {"radius": "big", "hint": "#zzzzzz", "glow": 0},
        None: {},  # non-str pack key dropped
    }
    out = normalize_skin_tweaks(bad_values, packs)
    assert out == {"tw": {"glow": False}}
    assert normalize_skin_tweaks(None, packs) == {}
    assert normalize_skin_tweaks(["nope"], packs) == {}


def test_normalize_skin_tweaks_enforces_pack_and_tweak_caps(tmp_path):
    # 33 KNOWN packs exceeds the 32-pack cap → whole result rejected
    packs = _discover(
        tmp_path,
        builtin_packs=[(f"pack{i:02d}", _manifest(key=f"pack{i:02d}"), None) for i in range(33)],
    )
    assert len(packs) == 33
    raw = {key: {"radius": 5} for key in packs}
    assert normalize_skin_tweaks(raw, packs) == {}

    # a synthetic pack with 33 tweak ids exceeds the per-pack cap → rejected
    synthetic = {
        "big": {
            "tweaks": [
                {
                    "id": f"t{i}",
                    "label": "T",
                    "type": "toggle",
                    "default": False,
                    "apply": {"class": "pack-x"},
                }
                for i in range(33)
            ]
        }
    }
    raw = {"big": {f"t{i}": True for i in range(33)}}
    assert normalize_skin_tweaks(raw, synthetic) == {}


def test_normalize_skin_tweaks_enforces_serialized_size_cap(tmp_path):
    """32 packs x 12 max-length select tweaks serializes well over 16KB."""
    tweaks = []
    for i in range(12):
        value = "v" * 32
        tweaks.append(
            {
                "id": ("t%d" % i).ljust(32, "x"),
                "label": "T",
                "type": "select",
                "options": [{"value": value, "label": "L"}],
                "default": value,
                "apply": {"var": f"pack-t{i}"},
            }
        )
    builtin_packs = [
        (f"pack{i:02d}", _manifest(key=f"pack{i:02d}", tweaks=tweaks), None)
        for i in range(32)
    ]
    packs = _discover(tmp_path, builtin_packs=builtin_packs)
    assert len(packs) == 32
    raw = {
        key: {t["id"]: "v" * 32 for t in pack["tweaks"]}
        for key, pack in packs.items()
    }
    # the kept result would serialize above 16KB, so the normaliser returns {}
    assert len(json.dumps(raw)) > 16 * 1024
    assert normalize_skin_tweaks(raw, packs) == {}


def test_normalize_skin_script_consents(tmp_path):
    packs = _discover(
        tmp_path,
        builtin_packs=[("sc", _manifest(key="sc"), None), ("other", _manifest(key="other"), None)],
    )
    raw = {"sc": True, "other": "yes", "ghost": False}
    assert normalize_skin_script_consents(raw, packs) == {"sc": True}
    assert normalize_skin_script_consents(None, packs) == {}
    assert normalize_skin_script_consents("nope", packs) == {}


# ── asset resolution + serving ─────────────────────────────────────────────


def test_resolve_pack_asset_sandbox(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_pack(
        builtin,
        "assets",
        _manifest(key="assets"),
        files={"extra.css": "body{}", "sub/deep.js": "ok", ".hidden": "s"},
    )
    outside = tmp_path / "outside.css"
    outside.write_text("outside", encoding="utf-8")
    (builtin / "assets" / "link.css").symlink_to(outside)

    packs = discover_skin_packs(builtin_root=builtin, user_root=tmp_path / "user")
    path, pack = resolve_pack_asset(packs, "assets", "extra.css")
    assert path.name == "extra.css"
    assert path.is_file()
    assert pack is packs["assets"]
    assert resolve_pack_asset(packs, "assets", "sub/deep.js") is not None

    # traversal, absolute, dotfile, encoded-traversal, backslash, symlink escape
    assert resolve_pack_asset(packs, "assets", "../outside.css") is None
    assert resolve_pack_asset(packs, "assets", "/etc/passwd") is None
    assert resolve_pack_asset(packs, "assets", ".hidden") is None
    assert resolve_pack_asset(packs, "assets", "sub/.env") is None
    assert resolve_pack_asset(packs, "assets", "..%2fout.css") is None
    assert resolve_pack_asset(packs, "assets", "sub\\deep.js") is None
    assert resolve_pack_asset(packs, "assets", "link.css") is None  # symlink escape
    # unknown pack, unknown file, non-string inputs
    assert resolve_pack_asset(packs, "ghost", "extra.css") is None
    assert resolve_pack_asset(packs, "assets", "missing.css") is None
    assert resolve_pack_asset(packs, None, "extra.css") is None
    assert resolve_pack_asset(packs, "assets", None) is None


