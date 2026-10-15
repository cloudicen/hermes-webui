"""Skin system unification contract tests (batch 3).

Batch 3 collapses the two parallel look axes (builtin skins vs skin packs)
into ONE unified entry axis:

- ``static/boot.js`` — ``_applySkinEntry``/``_pickSkinEntry`` (THE apply /
  picker handlers), the ``hermes-skin-applied`` pre-paint key, the
  legacy-axis sync owned by the entry apply, the ``_pickTheme`` fix (theme
  switches re-apply the active entry instead of stomping the skin axis),
  the unified picker grid (Default tile + css-key builtin packs + managed
  packs, no section divider), the legacy builtin-skin → pack migration in
  the boot reconcile, and ``resolvePackText`` localized manifest strings
- ``static/index.html`` — the pre-paint ``hermes-skin-applied`` override
- ``static/panels.js`` — hydration derived from the unified axis,
  localized tweak/option labels, and the live language-switch re-render
- ``static/commands.js`` — ``/theme`` routes pack keys through
  ``_pickSkinEntry`` and theme names through ``_pickTheme``

These tests pin the source-level contract in the idiom of
``tests/test_skinpacks_frontend_contract.py`` (batch 1).
"""

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COMMANDS_JS = (ROOT / "static" / "commands.js").read_text(encoding="utf-8")


def _function_block(src: str, name: str) -> str:
    marker = re.search(rf"(^|\n)(?:async\s+)?function\s+{re.escape(name)}\(", src)
    assert marker is not None, f"{name}() not found"
    start = marker.start()
    next_marker = re.search(r"\n(?:function\s+\w+\(|async\s+function\s+\w+\()", src[start + 1 :])
    if next_marker:
        end = start + 1 + next_marker.start()
    else:
        end = len(src)
    return src[start:end]


def _prepait_script() -> str:
    head_scripts = re.findall(r"<script>\(function\(\)\{try\{.*?\}\)\(\)</script>", INDEX_HTML[:6000])
    appearance_script = next((s for s in head_scripts if "hermes-skin" in s), None)
    assert appearance_script is not None, "appearance pre-paint script not found"
    return appearance_script


# ── boot.js: the unified entry functions ────────────────────────────────────


def test_boot_js_defines_unified_entry_functions():
    for fn in ("_applySkinEntry", "_pickSkinEntry", "_writeAppliedSkinKey", "_setLegacySkinAxis"):
        assert re.search(rf"function\s+{fn}\(", BOOT_JS), fn


def test_pick_theme_never_moves_the_skin_axis():
    # The verdigris regression: switching Theme (light/dark/system) used to
    # call _applySkin(appearance.skin), resetting the look to the last-used
    # builtin skin and killing an active pack. It must re-apply the ACTIVE
    # entry through _applySkinEntry and own neither the legacy skin write
    # nor the hidden #settingsSkin input (the entry apply owns both).
    block = _function_block(BOOT_JS, "_pickTheme")
    assert "_applySkinEntry(" in block
    assert "_applySkin(" not in block
    assert "localStorage.setItem('hermes-skin'" not in block
    assert "$('settingsSkin')" not in block
    assert "hermes-skin-pack" in block


def test_apply_skin_entry_writes_applied_key_for_every_mode():
    # '' → '', css-key pack → its bare key, managed pack → 'pack:<key>' —
    # the exact dataset.skin value the index.html pre-paint replays.
    block = _function_block(BOOT_JS, "_applySkinEntry")
    assert "_writeAppliedSkinKey(bareKey==='default'?'':bareKey)" in block
    assert "_writeAppliedSkinKey(_packSkinKey(pack))" in block
    writer = _function_block(BOOT_JS, "_writeAppliedSkinKey")
    assert "localStorage.setItem('hermes-skin-applied'" in writer


def test_apply_skin_entry_owns_the_legacy_axis():
    # hermes-skin + hidden #settingsSkin = (css-key ? key : 'default'), so
    # legacy consumers and the appearance payload stay consistent.
    block = _function_block(BOOT_JS, "_applySkinEntry")
    assert "_setLegacySkinAxis('default')" in block
    assert "_setLegacySkinAxis(bareKey)" in block
    axis = _function_block(BOOT_JS, "_setLegacySkinAxis")
    assert "localStorage.setItem('hermes-skin'" in axis
    assert "$('settingsSkin')" in axis


def test_apply_skin_entry_routes_by_apply_mode():
    # css-key packs: bare dataset.skin, no managed styles (their CSS already
    # lives in style.css); managed packs: the full _applySkinPack chrome plus
    # tweak re-apply from the shared runtime state.
    block = _function_block(BOOT_JS, "_applySkinEntry")
    assert "pack.applyMode!=='css-key'" in block
    assert "_applySkinPack(" in block
    assert "_applyPackTweakValues(" in block
    assert "_removeSkinPack()" in block


def test_index_html_prepaint_reads_applied_key():
    script = _prepait_script()
    assert "localStorage.getItem('hermes-skin-applied')" in script
    # key EXISTS (even empty string) → it wins over the legacy map; absent
    # key → legacy behavior (fresh migration path)
    assert "if(apk!==null)" in script
    assert "document.documentElement.dataset.skin=apk" in script
    assert "delete document.documentElement.dataset.skin" in script
    # the palette-cache application stays after the override for pack: entries
    assert script.index("hermes-skin-applied") < script.index("hermes-skin-pack-palette")


def test_build_skin_picker_default_tile_and_no_builtin_section():
    block = _function_block(BOOT_JS, "_buildSkinPicker")
    # ONE grid: a Default tile (marker 'default'), then the pack tiles —
    # the _SKINS-driven builtin tiles and the "Skin packs" divider are gone.
    assert "dataset.skinVal='default'" in block
    assert "_pickSkinEntry('')" in block
    assert "for(const skin of _SKINS)" not in block
    assert "skin-pack-section-label" not in block
    assert "skin-pack-section-label" not in _function_block(BOOT_JS, "_appendSkinPackTiles")
    # css-key builtins tile with their bare key (no pack: prefix)
    tiles = _function_block(BOOT_JS, "_appendSkinPackTiles")
    assert "pack.applyMode==='css-key'" in tiles
    assert "isCssKey?key:('pack:'+key)" in tiles


def test_resolve_pack_text_localizes_manifest_strings():
    # exists in boot.js + exposed globally; resolves string OR localized
    # object per the current WebUI locale with en/first-value fallbacks
    assert re.search(r"function\s+resolvePackText\(", BOOT_JS)
    assert "window.resolvePackText=resolvePackText" in BOOT_JS
    block = _function_block(BOOT_JS, "resolvePackText")
    assert "typeof value==='string'" in block
    assert "value['en']" in block or "value.en" in block
    # current locale: setLocale persists the resolved locale to 'hermes-lang'
    locale = _function_block(BOOT_JS, "_currentLocale")
    assert "localStorage.getItem('hermes-lang')" in locale


def test_render_skin_pack_tweaks_uses_resolve_pack_text():
    # tweak labels + select option labels localize per the active locale
    tweaks = _function_block(PANELS_JS, "_renderSkinPackTweaks")
    assert "resolvePackText" in tweaks
    control = _function_block(PANELS_JS, "_buildPackTweakControl")
    assert "resolvePackText" in control


def test_panels_language_change_re_renders_pack_ui():
    # the language select onchange re-renders the tweak panel + script chip
    # and rebuilds the picker so pack names/labels follow the new locale
    marker = PANELS_JS.index("langSel.addEventListener('change'")
    zone = PANELS_JS[marker : marker + 700]
    assert "setLocale(this.value)" in zone
    assert "_syncSkinPackSettingsUi" in zone
    assert "_buildSkinPicker" in zone


def test_panels_hydration_derives_hidden_inputs_from_unified_axis():
    hydrate = _function_block(PANELS_JS, "loadSettingsPanel")
    # skin_pack = ls hermes-skin-pack || settings.skin_pack || migrated
    # settings.skin (non-default + exists as a pack)
    assert "localStorage.getItem('hermes-skin-pack')" in hydrate
    assert "settings.skin_pack" in hydrate
    assert "_findSkinPack(legacySkin)" in hydrate
    # legacy skin hidden = css-key ? key : 'default'
    assert "applyMode==='css-key'" in hydrate
    assert "skinSel.value=skinVal" in hydrate
    assert "packHiddenInput.value=packVal" in hydrate


def test_boot_reconcile_adopts_legacy_builtin_skin_as_pack():
    # migration: skin_pack=='' + a non-default legacy skin that exists in the
    # fetched pack list → adopt skin_pack=<key> + one corrective POST
    skin_push_back = BOOT_JS.index("body:JSON.stringify({theme,skin})")
    pack_zone = BOOT_JS[skin_push_back : skin_push_back + 5000]
    assert "migrateLegacySkinKey" in pack_zone
    assert "_findSkinPack(migrateLegacySkinKey)" in pack_zone
    assert "localStorage.setItem('hermes-skin-pack',bootPackKey)" in pack_zone
    assert "body:JSON.stringify({skin_pack:bootPackKey})" in pack_zone


def test_pack_tweaks_style_emits_both_schemes():
    # Dark-mode cascade pin: the palette style carries a higher-specificity
    # :root.dark[data-skin=…] block, so a plain :root[data-skin=…] tweak rule
    # loses the cascade in dark mode and palette tokens silently win. The
    # tweak style must mirror both schemes (it sits after the palette
    # element, so document order settles equal specificity).
    start = BOOT_JS.index("function _applyPackTweakValues")
    body = BOOT_JS[start : start + 5000]
    assert ':root[data-skin="${skinKey}"]{${decls}}' in body
    assert ':root.dark[data-skin="${skinKey}"]{${decls}}' in body


def test_pack_tweaks_reset_button_contract():
    # Reset-to-defaults: clears the pack's stored tweak state, re-applies with
    # the empty map (every tweak falls back to its default), re-renders the
    # controls, and persists through the appearance autosave. The server's
    # per-pack shallow merge ({**current, **incoming}) replaces the whole pack
    # entry, so {pack:{}} genuinely clears stored values.
    start = PANELS_JS.index("function _renderSkinPackTweaks")
    body = PANELS_JS[start : start + 3000]
    assert "settings_skins_pack_tweaks_reset" in body
    assert "_applyPackTweakValues(pack.key,{})" in body
    assert "window._skinTweaksState[pack.key]={}" in body
    assert "_renderSkinPackTweaks(pack)" in body
    assert "_scheduleAppearanceAutosave()" in body
    i18n = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "settings_skins_pack_tweaks_reset: 'Reset to defaults'" in i18n
    assert "settings_skins_pack_tweaks_reset: '恢复默认设置'" in i18n
