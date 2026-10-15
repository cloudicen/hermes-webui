"""Builtin example skin pack tests (skin-pack feature, W4).

``static/skins/aurora`` is the pack shipped with WebUI: a usable skin and the
reference for pack authors. These tests pin the shipped artifacts:

- the real manifest passes the real validator (``api.skinpacks``) against the
  real ``static/skins/aurora`` directory, and discovery picks it up as a
  script-free builtin pack
- both palette schemes are complete: full accent family + the pack-* tokens
  the tweaks and theme.css depend on
- theme.css exists and consumes the tweak outputs under ``pack:aurora``
  scoping (light + dark)
- the pack UI i18n keys exist in BOTH the en and zh blocks of i18n.js
  (the other locales fall back to en — see the i18n.js header)
"""

import re
from pathlib import Path

from api.skinpacks import _load_and_validate_manifest, discover_skin_packs

REPO_ROOT = Path(__file__).parent.parent
AURORA_DIR = REPO_ROOT / "static" / "skins" / "aurora"
I18N_JS = (REPO_ROOT / "static" / "i18n.js").read_text(encoding="utf-8")

ACCENT_FAMILY = (
    "accent", "accent-hover", "accent-bg", "accent-bg-strong", "accent-text",
    "accent2", "accent3", "accent-contrast", "accent-rgb",
)
PACK_I18N_KEYS = (
    "settings_skins_packs_section",
    "settings_skins_pack_badge_user",
    "settings_skins_pack_badge_builtin",
    "settings_skins_pack_shadow_note",
    "settings_skins_pack_none",
    "settings_skins_pack_tweaks_title",
    "settings_skins_pack_scripts_title",
    "settings_skins_pack_scripts_warning_title",
    "settings_skins_pack_scripts_warning_body",
    "settings_skins_pack_scripts_enable",
    "settings_skins_pack_scripts_skip",
    "settings_skins_pack_scripts_disable",
    "settings_skins_pack_scripts_enabled_chip",
    "settings_skins_pack_scripts_disabled_chip",
)


def _locale_block(locale_key: str) -> str:
    """Slice of i18n.js for one locale block — mirrors the block-extraction
    idiom of tests/test_1560_password_env_var_no_op.py. Locale openers are
    two-space-indented (`  en: {`); block content is indented deeper, so the
    next two-space opener (or end of file) closes the block."""
    opener = f"  '{locale_key}': {{" if "-" in locale_key else f"  {locale_key}: {{"
    start = I18N_JS.index(opener)
    rest = I18N_JS[start + len(opener):]
    next_opener = re.search(r"^  '?[A-Za-z][A-Za-z-]*'?: \{$", rest, re.MULTILINE)
    return rest[: next_opener.start()] if next_opener else rest


def test_shipped_manifest_passes_real_validator(tmp_path):
    normalized, error = _load_and_validate_manifest(AURORA_DIR)
    assert error is None, f"shipped aurora manifest must validate: {error}"
    assert normalized["key"] == "aurora"
    # batch 3: the shipped pack demonstrates the localized name/label form
    assert normalized["name"] == {"en": "Aurora", "zh": "极光"}
    assert normalized["scheme"] == "auto"
    assert normalized["applyMode"] == "pack"
    assert normalized["extraCss"] == "theme.css"
    assert normalized["preview"]["colors"] == ["#22d3ee", "#2dd4bf", "#0e7490"]
    # builtin packs ship script-free by policy
    assert normalized["scripts"] == []
    # operator logo overrides (deliberately not the stock favicon set)
    assert normalized["icons"] == {
        "favicon": "icons/logo-192.png",
        "favicon32": "icons/logo-32.png",
        "favicon192": "icons/logo-192.png",
        "favicon512": "icons/logo-512.png",
        "appleTouch": "icons/logo-512.png",
        "faviconIco": "icons/favicon.ico",
        "logoSvg": "icons/logo-512.png",
    }
    assert normalized["thinking"] == {"mode": "gif", "gif": "anim/thinking.gif", "size": 28}
    # the example demonstrates every control type, incl. image upload
    tweaks = {t["id"]: t for t in normalized["tweaks"]}
    assert set(tweaks) == {
        "glow-strength", "accent-tone", "compact-chips", "accent-color", "corner-image"
    }
    assert tweaks["corner-image"]["type"] == "image"
    assert tweaks["corner-image"]["apply"] == {"var": "pack-corner-image"}
    assert tweaks["glow-strength"]["type"] == "range"
    assert tweaks["glow-strength"]["apply"] == {
        "var": "pack-glow-strength", "template": "{value}%"
    }
    assert tweaks["accent-tone"]["type"] == "select"
    assert tweaks["accent-tone"]["apply"] == {"var": "pack-accent-tone"}
    assert tweaks["compact-chips"]["type"] == "toggle"
    assert tweaks["compact-chips"]["apply"] == {"class": "pack-compact"}
    assert tweaks["accent-color"]["type"] == "color"
    assert tweaks["accent-color"]["apply"] == {"var": "accent"}

    # and the real discovery path picks it up from the real builtin root
    packs = discover_skin_packs(
        builtin_root=REPO_ROOT / "static" / "skins",
        user_root=tmp_path / "no-user-skins",
    )
    assert "aurora" in packs
    assert packs["aurora"]["origin"] == "builtin"
    assert packs["aurora"]["shadows"] is False


def test_both_palette_schemes_complete_with_accent_family_and_pack_tokens():
    normalized, error = _load_and_validate_manifest(AURORA_DIR)
    assert error is None
    for side in ("light", "dark"):
        palette = normalized["palette"][side]
        missing = [token for token in ACCENT_FAMILY if token not in palette]
        assert not missing, f"palette.{side} is missing accent tokens: {missing}"
        # the custom tokens the tweaks and theme.css consume must have defaults
        assert "pack-glow" in palette
        assert "pack-glow-strength" in palette
        assert "pack-accent-tone" in palette


def test_theme_css_scopes_and_consumes_tweak_outputs():
    theme = (AURORA_DIR / "theme.css").read_text(encoding="utf-8")
    # scoped to the pack skin value, both schemes
    assert ':root[data-skin="pack:aurora"]' in theme
    assert ':root.dark[data-skin="pack:aurora"]' in theme
    # consumes the tweak outputs
    assert "var(--pack-glow-strength)" in theme
    assert "var(--pack-accent-tone)" in theme
    assert "html.pack-compact" in theme
    # repo color-mix idiom layered over the palette accent
    assert "color-mix(in srgb,var(--accent)" in theme


def test_pack_i18n_keys_present_in_en_and_zh_blocks():
    for locale in ("en", "zh"):
        block = _locale_block(locale)
        missing = [key for key in PACK_I18N_KEYS if f"{key}:" not in block]
        assert not missing, f"{locale} block is missing pack keys: {missing}"
