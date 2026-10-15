"""Skin pack frontend contract tests (skin-pack feature, W5).

W5 lands the frontend core in the classic no-build scripts:

- ``static/boot.js`` — pack list fetch (GET /api/skins), pack apply/remove,
  tweak resolution, script loading, picker merge, and the boot reconcile
- ``static/index.html`` — pre-paint pack replay, the hidden ``skin_pack``
  input, and the W6/W7 containers
- ``static/commands.js`` — ``/theme pack:<key>`` routing
- ``static/style.css`` — pack tile + tweak row chrome

These tests pin the SOURCE-LEVEL contract the follow-up work items depend
on: function names, element ids, localStorage key names and formats, and
route wiring. ``tests/test_skinpacks_routes.py`` (W3) pins the HTTP side;
``tests/test_skinpacks_discovery.py`` (W1) the manifest/sandbox side.

W6/W7 extend the same contract into ``static/panels.js``: the per-pack tweak
panel (live apply + autosave + server-clamp re-sync) and the script-consent
flow (confirm dialog on explicit selection, silent consented boot loads).
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COMMANDS_JS = (ROOT / "static" / "commands.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
MESSAGES_JS = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
AURORA_MANIFEST = json.loads(
    (ROOT / "static" / "skins" / "aurora" / "manifest.json").read_text(encoding="utf-8")
)
AURORA_THEME = (ROOT / "static" / "skins" / "aurora" / "theme.css").read_text(encoding="utf-8")


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


# ── index.html: containers + pre-paint ─────────────────────────────────────


def test_index_html_declares_pack_settings_containers():
    for element_id in ("settingsSkinPack", "skinPackTweaks", "skinPackScripts"):
        assert f'id="{element_id}"' in INDEX_HTML, element_id
    assert '<input type="hidden" id="settingsSkinPack" value="">' in INDEX_HTML


def test_index_html_prepaint_reads_pack_marker_and_palette_cache():
    head_scripts = re.findall(r"<script>\(function\(\)\{try\{.*?\}\)\(\)</script>", INDEX_HTML[:6000])
    assert head_scripts, "pre-paint inline scripts not found near <head>"
    appearance_script = next((s for s in head_scripts if "hermes-skin" in s), None)
    assert appearance_script is not None, "appearance pre-paint script not found"
    # pack marker: dataset.skin='pack:<key>' when localStorage carries a pack
    assert "localStorage.getItem('hermes-skin-pack')" in appearance_script
    assert "dataset.skin='pack:'+pk" in appearance_script
    # palette replay: cached per-scheme map applied as inline custom properties
    assert "localStorage.getItem('hermes-skin-pack-palette')" in appearance_script
    assert "classList.contains('dark')?pm.dark:pm.light" in appearance_script
    assert "setProperty(ptok,String(pv[ptok]))" in appearance_script


def test_index_html_prepaint_script_documents_boot_js_sync_contract():
    # The pre-paint must declare the keep-in-sync note naming the boot.js
    # writers of the cache it replays (same comment convention as the
    # sidebar-collapse pre-paint above it).
    head = INDEX_HTML[:6000]
    assert "hermes-skin-pack-palette" in head
    assert re.search(r"Keep the skin-pack tail of this pre-paint script in sync with", head)
    assert "_applySkinPack" in head and "_applyPackTweakValues" in head


# ── boot.js: pack module functions + fetch ─────────────────────────────────


def test_boot_js_defines_pack_module_functions():
    for fn in (
        "_fetchSkinPacks",
        "_applySkinPack",
        "_removeSkinPack",
        "_pickSkinPack",
        "_applyPackTweakValues",
        "_loadPackScripts",
        "_findSkinPack",
    ):
        assert re.search(rf"function\s+{fn}\(", BOOT_JS), fn


def test_boot_js_fetches_pack_list_from_api_skins_via_api_wrapper():
    block = _function_block(BOOT_JS, "_fetchSkinPacks")
    assert "api('/api/skins')" in block
    # a failed fetch must NOT read as "no packs installed" (keeps pack state)
    assert "throw e" in block
    assert "window._SKIN_PACKS=_SKIN_PACKS" in BOOT_JS


def test_boot_js_apply_skin_pack_manages_palette_extra_css_and_skin_attr():
    block = _function_block(BOOT_JS, "_applySkinPack")
    assert "getElementById(_PACK_PALETTE_STYLE_ID)" in block
    assert "getElementById(_PACK_EXTRA_CSS_ID)" in block
    assert ':root[data-skin="${skinKey}"]' in block
    assert ':root.dark[data-skin="${skinKey}"]' in block
    assert "document.documentElement.dataset.skin=skinKey" in block
    assert "_setResolvedTheme(_resolvedThemeBaseDark)" in block
    assert "_packAssetUrl(pack,pack.extraCss)" in block
    # fallback: a token missing from one scheme resolves from the other
    palette_map = _function_block(BOOT_JS, "_packPaletteVarMap")
    assert "Object.keys(own).concat(Object.keys(other))" in palette_map


def test_boot_js_active_skin_scheme_consults_packs_for_pack_prefixed_keys():
    block = _function_block(BOOT_JS, "_activeSkinScheme")
    assert "startsWith('pack:')" in block
    assert "_findSkinPack" in block


def test_boot_js_pick_skin_entry_persists_and_autosaves():
    # Batch 3: _pickSkinEntry is THE picker click handler; the legacy
    # _pickSkinPack/_pickSkin names remain as thin shims delegating to it.
    block = _function_block(BOOT_JS, "_pickSkinEntry")
    assert "localStorage.setItem('hermes-skin-pack',packKey)" in block
    assert "_applySkinEntry(isExtSkin?rawKey:packKey)" in block
    assert "$('settingsSkinPack')" in block
    assert "_syncSkinPicker(marker)" in block
    assert "typeof _scheduleAppearanceAutosave==='function'" in block
    assert "_syncSkinPackSettingsUi" in block
    for shim in ("_pickSkin", "_pickSkinPack"):
        shim_block = _function_block(BOOT_JS, shim)
        assert "_pickSkinEntry(" in shim_block, shim


def test_boot_js_pick_skin_entry_clears_pack_state_when_choosing_default():
    # The Default tile (key '') clears the pack axis: pack styles, the cached
    # pre-paint palette and the pack marker all go together via the unified
    # apply, which owns pack-chrome removal.
    block = _function_block(BOOT_JS, "_pickSkinEntry")
    assert "localStorage.setItem('hermes-skin-pack',packKey)" in block
    apply_entry = _function_block(BOOT_JS, "_applySkinEntry")
    assert "_removeSkinPack()" in apply_entry
    assert "$('settingsSkinPack')" in block


def test_boot_js_remove_skin_pack_restores_builtin_skin_and_drops_cache():
    block = _function_block(BOOT_JS, "_removeSkinPack")
    for element_id in ("_PACK_PALETTE_STYLE_ID", "_PACK_EXTRA_CSS_ID", "_PACK_TWEAKS_STYLE_ID"):
        assert f"getElementById({element_id})" in block, element_id
    assert "localStorage.removeItem(_PACK_PREPAINT_CACHE_KEY)" in block
    assert "_applySkin(localStorage.getItem('hermes-skin')||'default')" in block


def test_boot_js_apply_pack_tweak_values_covers_var_template_class_and_cache():
    block = _function_block(BOOT_JS, "_applyPackTweakValues")
    assert "classList.toggle(cls,!!value)" in block
    assert "apply.template.split('{value}').join(String(value))" in block
    assert "tweak.default" in block
    # tweaks style sits after the palette element so tweaks win the cascade
    assert "insertBefore(tweakStyle,paletteStyle.nextSibling)" in block
    assert "_writePackPrepaintCache(pack,tweakVars)" in block
    cache_writer = _function_block(BOOT_JS, "_writePackPrepaintCache")
    assert "_PACK_PREPAINT_CACHE_MAX" in cache_writer
    assert "removeItem(_PACK_PREPAINT_CACHE_KEY)" in cache_writer


def test_boot_js_load_pack_scripts_appends_manifest_order_scripts():
    block = _function_block(BOOT_JS, "_loadPackScripts")
    assert "document.createElement('script')" in block
    assert "script.src=src" in block
    assert "script.defer=true" in block
    assert "_packAssetUrl(pack,rel)" in block


def test_boot_js_build_skin_picker_renders_unified_grid_with_dom_construction():
    # Batch 3: ONE grid — Default tile + pack tiles (+ extension skins).
    # The old builtin _SKINS loop and the "Skin packs" section divider are
    # gone; builtin skins render as css-key pack tiles.
    block = _function_block(BOOT_JS, "_buildSkinPicker")
    tiles = _function_block(BOOT_JS, "_appendSkinPackTiles")
    assert "_appendSkinPackTiles(grid)" in block
    assert "_appendExtensionSkinTiles(grid)" in block
    assert "dataset.skinVal='default'" in block
    assert "_pickSkinEntry('')" in block
    assert "for(const skin of _SKINS)" not in block
    assert "settings_skins_packs_section" not in tiles
    assert "settings_skins_pack_none" not in tiles
    # XSS discipline: pack data is user-controlled manifest content
    assert "innerHTML" not in tiles
    assert "createElement" in tiles and "textContent" in tiles
    # css-key packs tile with their bare key, managed packs with pack: prefix
    assert "pack.applyMode==='css-key'" in tiles
    assert "_pickSkinEntry(key)" in tiles
    assert "resolvePackText(pack.name)" in tiles
    # user-origin badge survives unification
    assert "settings_skins_pack_badge_user" in tiles
    assert "settings_skins_pack_shadow_note" in tiles


# ── boot.js: reconcile semantics ───────────────────────────────────────────


def test_boot_js_settings_reconcile_mirrors_explicit_preference_for_packs():
    # Locate the GET /api/settings handler's skin reconcile, then assert the
    # pack mirror sits directly after it (same handler, same semantics).
    skin_push_back = BOOT_JS.index("body:JSON.stringify({theme,skin})")
    pack_zone = BOOT_JS[skin_push_back : skin_push_back + 5000]
    assert "localStorage.getItem('hermes-skin-pack')" in pack_zone
    assert "s.skin_pack" in pack_zone
    assert "body:JSON.stringify({skin_pack:lsPackKey})" in pack_zone
    # uninstalled pack → default-look fallback + correction POST (batch 3:
    # routed through _applySkinEntry, which owns pack-chrome removal)
    assert "body:JSON.stringify({skin_pack:''" in pack_zone
    assert "_applySkinEntry('')" in pack_zone
    assert "_fetchSkinPacks()" in pack_zone
    # batch-3 migration: a pre-unification builtin skin adopted as a pack
    # (once) with a corrective POST, then applied through the unified entry
    assert "migrateLegacySkinKey" in pack_zone
    assert "body:JSON.stringify({skin_pack:bootPackKey})" in pack_zone
    assert "_applySkinEntry(pack.key)" in pack_zone


# ── panels.js: W6 tweak panel + W7 script consent ──────────────────────────


def test_panels_js_renders_per_pack_tweak_panel_with_dom_construction():
    block = _function_block(PANELS_JS, "_renderSkinPackTweaks")
    assert "$('skinPackTweaks')" in block
    assert "settings_skins_pack_tweaks_title" in block
    # XSS discipline: pack data is user-controlled manifest content
    assert "innerHTML" not in block
    assert "createElement" in block and "textContent" in block
    # wiring: control changes write the shared state, live-apply through the
    # boot.js helper, then ride the debounced appearance autosave
    wiring = _function_block(PANELS_JS, "_buildPackTweakControl")
    assert "window._skinTweaksState" in wiring
    assert "_applyPackTweakValues" in wiring
    assert "_scheduleAppearanceAutosave()" in wiring


def test_panels_js_appearance_payload_carries_pack_settings():
    block = _function_block(PANELS_JS, "_appearancePayloadFromUi")
    assert "skin_pack" in block and "settingsSkinPack" in block
    assert "window._skinTweaksState" in block
    assert "window._skinScriptConsents" in block
    # settings-open hydration mirrors the server pack state before rendering
    hydrate = _function_block(PANELS_JS, "loadSettingsPanel")
    assert "skin_tweaks" in hydrate and "skin_script_consents" in hydrate
    assert "_fetchSkinPacks" in hydrate
    assert "_syncSkinPackSettingsUi" in hydrate
    # autosave response re-syncs the server-normalized values
    assert "_syncPackSettingsFromServerResponse(saved)" in PANELS_JS


def test_panels_js_script_consent_dialog_and_chip():
    dialog = _function_block(PANELS_JS, "_requestSkinPackScriptConsent")
    assert "showConfirmDialog" in dialog
    assert "settings_skins_pack_scripts_warning_title" in dialog
    assert "settings_skins_pack_scripts_warning_body" in dialog
    assert "settings_skins_pack_scripts_enable" in dialog
    assert "settings_skins_pack_scripts_skip" in dialog
    # consent → persist + load (skip leaves the pack applied without scripts)
    assert "_loadPackScripts(pack)" in dialog
    assert "window._skinScriptConsents[pack.key]=true" in dialog
    chip = _function_block(PANELS_JS, "_renderSkinPackScripts")
    assert "$('skinPackScripts')" in chip
    assert "settings_skins_pack_scripts_enabled_chip" in chip
    assert "settings_skins_pack_scripts_disabled_chip" in chip
    assert "settings_skins_pack_scripts_disable" in chip
    # loaded scripts cannot be unloaded: disable persists, then reloads
    assert "location.reload()" in PANELS_JS


def test_boot_js_boot_and_picker_paths_gate_scripts_on_consent():
    # boot apply path: a consented pack loads its scripts silently after the
    # unified entry apply (the dialog never runs during boot)
    idx = BOOT_JS.index("_applySkinEntry(pack.key)")
    zone = BOOT_JS[idx : idx + 1500]
    assert "window._skinScriptConsents" in zone
    assert "_loadPackScripts(pack)" in zone
    # tweak re-apply rides the unified apply itself (managed packs)
    apply_entry = _function_block(BOOT_JS, "_applySkinEntry")
    assert "_applySkinPack(" in apply_entry
    assert "_applyPackTweakValues" in apply_entry
    # picker path: explicit selection without prior consent asks through the
    # panels.js dialog helper, and re-renders the pack sections for the new pack
    pick = _function_block(BOOT_JS, "_pickSkinEntry")
    assert "_requestSkinPackScriptConsent" in pick
    assert "_syncSkinPackSettingsUi" in pick


# ── commands.js + style.css ────────────────────────────────────────────────


def test_commands_js_theme_routes_pack_keys_via_window_skin_packs():
    block = _function_block(COMMANDS_JS, "cmdTheme")
    assert "window._SKIN_PACKS" in block
    assert "startsWith('pack:')" in block
    assert "_pickSkinEntry(packKey)" in block
    assert "{skin_pack:packKey}" in block
    # batch 3: theme names route through _pickTheme (never touching the skin
    # axis) and the usage hint lists themes + the pack count
    assert "_pickTheme(val)" in block
    assert "_applySkin(" not in block
    assert "packList.length" in block


def test_style_css_declares_pack_tile_and_tweak_row_chrome():
    for cls in (
        "skin-pack-section-label",
        "skin-pack-tile",
        "skin-pack-dot",
        "skin-pack-name",
        "skin-pack-badge",
        "skin-pack-badge-user",
        "skin-pack-tweak-row",
        "skin-pack-tweak-control",
    ):
        assert f".{cls}" in STYLE_CSS, cls
    # batch 3: the unified picker's shared tile chrome mirrors the old
    # builtin skin-pick-btn cards (the Default tile wears the same class)
    tile = STYLE_CSS.split(".skin-pack-tile", 1)[1][:400]
    assert "border:1px solid var(--border2)" in tile
    # the dead empty-state note rule is gone with the removed section divider
    assert ".skin-pack-none-note" not in STYLE_CSS


# ── Icons, thinking animation and logo swap (batch 2 surfaces) ──────────────


def test_boot_js_apply_skin_pack_applies_all_batch2_surfaces():
    # The helpers live INSIDE _applySkinPack so every apply path (picker,
    # boot reconcile, /theme pack:<key>) adopts thinking/icons/logo together.
    block = _function_block(BOOT_JS, "_applySkinPack")
    for call in ("_applyPackThinking(pack)", "_applyPackIcons(pack)", "_applyPackLogo(pack)"):
        assert call in block, call


def test_boot_js_remove_skin_pack_clears_batch2_chrome():
    block = _function_block(BOOT_JS, "_removeSkinPack")
    assert "getElementById(_PACK_THINKING_ID)" in block
    # _applyPackIcons(null) is the shared clear path (pack without icons and
    # pack removal go through the same delete).
    assert "_applyPackIcons(null)" in block
    assert "_restorePackLogos()" in block


# ── boot.js: thinking indicator ─────────────────────────────────────────────


def test_boot_js_thinking_manages_style_or_link_element_by_mode():
    block = _function_block(BOOT_JS, "_applyPackThinking")
    assert "getElementById(_PACK_THINKING_ID)" in block
    # css mode → <link rel="stylesheet"> pointing at the pack stylesheet
    assert "document.createElement('link')" in block
    assert "link.rel='stylesheet'" in block
    assert "_packAssetUrl(pack,thinking.css)" in block
    # gif mode → <style> with composed, pack-scoped textContent
    assert "document.createElement('style')" in block
    assert "styleEl.id=_PACK_THINKING_ID" in block
    assert "_packAssetUrl(pack,thinking.gif)" in block
    # mode none / missing / unsafe path → the element is removed
    assert "if(existing) existing.remove();" in block


def test_boot_js_thinking_gif_css_hides_dots_and_paints_gif_scoped_to_pack():
    block = _function_block(BOOT_JS, "_applyPackThinking")
    assert '[data-skin="${skinKey}"] #thinkingRow .thinking .dot{display:none}' in block
    assert (
        '#thinkingRow .thinking{background:url("${href}") center / contain no-repeat;'
        'min-width:${size}px;min-height:${size}px;}'
    ) in block
    # the compact worklog "Thinking" label is documented as out of scope
    assert "separate surface" in block


def test_boot_js_thinking_size_mirrors_the_server_clamp():
    block = _function_block(BOOT_JS, "_applyPackThinking")
    assert "Number(thinking.size)" in block
    assert "Math.min(128,Math.max(8," in block


def test_boot_js_thinking_paths_pass_a_css_url_guard_before_textcontent():
    # The GIF href is the one manifest value interpolated into CSS text, so
    # both css/gif paths must pass the strict path guard first.
    block = _function_block(BOOT_JS, "_applyPackThinking")
    guard = _function_block(BOOT_JS, "_isSafePackCssUrlPath")
    assert "_isSafePackCssUrlPath(thinking.css)" in block
    assert "_isSafePackCssUrlPath(thinking.gif)" in block
    assert "_PACK_CSS_URL_PATH_RE" in guard
    # first char class: a path segment can never start with '/', '.', '...'
    assert "const _PACK_CSS_URL_PATH_RE=/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,127}" in BOOT_JS


# ── boot.js: notification-icon global ───────────────────────────────────────


def test_boot_js_icons_global_carries_only_declared_notification_keys():
    block = _function_block(BOOT_JS, "_applyPackIcons")
    # URLs are composed from assetsBase + the manifest path, never raw JSON
    assert "window.__HERMES_SKIN_ICONS__=out" in block
    assert "_packAssetUrl(pack,icons.favicon192)" in block
    assert "_packAssetUrl(pack,icons.favicon32)" in block
    # absent / nothing declared → the global is cleared, not left stale
    assert "delete window.__HERMES_SKIN_ICONS__" in block


# ── boot.js: logo swap + originals restore ──────────────────────────────────


def test_boot_js_logo_swap_targets_both_brand_marks_with_cached_originals():
    assert "_PACK_LOGO_SELECTORS=['.app-titlebar-icon','.empty-logo']" in BOOT_JS
    assert "_PACK_LOGO_ORIGINALS=new WeakMap()" in BOOT_JS
    swap = _function_block(BOOT_JS, "_applyPackLogo")
    assert "document.querySelector(selector)" in swap
    # cache-once guard: a repeated apply must never cache the swapped <img>
    # markup as the "original"
    assert "if(!_PACK_LOGO_ORIGINALS.has(el)) _PACK_LOGO_ORIGINALS.set(el,el.innerHTML)" in swap
    assert "el.innerHTML=''" in swap
    assert "document.createElement('img')" in swap
    assert "swapped.className='skin-logo-img'" in swap


def test_boot_js_logo_removal_restores_cached_originals():
    restore = _function_block(BOOT_JS, "_restorePackLogos")
    assert "_PACK_LOGO_ORIGINALS.has(el)" in restore
    assert "el.innerHTML=_PACK_LOGO_ORIGINALS.get(el)" in restore
    assert "_PACK_LOGO_ORIGINALS.delete(el)" in restore


def test_boot_js_batch2_never_interpolates_manifest_content_as_html():
    # The logo <img> swap is the only innerHTML writer among the batch-2
    # helpers, and its src is built from assetsBase + the manifest path
    # (_packAssetUrl), never from raw manifest JSON.
    for fn in ("_applyPackThinking", "_applyPackIcons"):
        assert "innerHTML" not in _function_block(BOOT_JS, fn), fn
    swap = _function_block(BOOT_JS, "_applyPackLogo")
    assert "_packAssetUrl(pack,logoRel)" in swap
    assert "JSON.stringify" not in swap


# ── messages.js + style.css ─────────────────────────────────────────────────


def test_messages_js_notifications_prefer_pack_icons_with_stock_fallback():
    block = _function_block(MESSAGES_JS, "_notificationOptions")
    assert (
        "window.__HERMES_SKIN_ICONS__&&window.__HERMES_SKIN_ICONS__.icon192"
        ")||'static/favicon-192.png'"
    ) in block
    assert (
        "window.__HERMES_SKIN_ICONS__&&window.__HERMES_SKIN_ICONS__.icon32"
        ")||'static/favicon-32.png'"
    ) in block


def test_style_css_sizes_swapped_logo_img_to_the_existing_tiles():
    assert ".skin-logo-img{width:100%;height:100%;display:block;object-fit:contain;}" in STYLE_CSS
    # deterministic tile sizes for both swapped surfaces
    assert ".app-titlebar-icon .skin-logo-img{width:16px;height:16px;}" in STYLE_CSS
    assert ".empty-logo .skin-logo-img{width:88px;height:88px;" in STYLE_CSS


# ── Image upload tweak (batch 4) ────────────────────────────────────────────


def _image_branch() -> str:
    # The image branch sits between its `tweak.type==='image'` guard and the
    # generic var/template composition that follows it (its `const token=`
    # preamble; the branch itself binds `const imgToken=`).
    block = _function_block(BOOT_JS, "_applyPackTweakValues")
    start = block.index("tweak.type==='image'")
    return block[start : block.index("const token=", start)]


def test_boot_js_validates_upload_filenames_with_regex():
    # The ONLY shape allowed into the composed url(): a 64-char sha256 hex
    # name with one of the four served extensions. Anything else must miss
    # and omit the token.
    assert "_PACK_UPLOAD_FILE_RE" in BOOT_JS
    assert (
        re.search(r"const _PACK_UPLOAD_FILE_RE=/\^\[a-f0-9\]\{64\}\\\.\(png\|jpg\|jpeg\|gif\|webp\)\$/", BOOT_JS)
        is not None
    )


def test_boot_js_image_branch_composes_server_shaped_url():
    # The image branch sets the token to url('/api/skins/<key>/uploads/<file>')
    # — the fixed prefix plus the regex-validated filename, nothing else.
    # It must NOT route through _sanitizePackCssValue (which rejects url());
    # the bypass is safe BY CONSTRUCTION because the guard precedes the write.
    branch = _image_branch()
    assert "_PACK_UPLOAD_FILE_RE.test(fileName)" in branch
    assert "url('/api/skins/${encodeURIComponent(pack.key)}/uploads/${fileName}')" in branch
    # no sanitizer CALL — the bypass is the branch's whole safety story
    assert "_sanitizePackCssValue(" not in branch
    assert "if(_PACK_UPLOAD_FILE_RE.test(fileName)){" in branch
    assert branch.index("_PACK_UPLOAD_FILE_RE.test(fileName)") < branch.index("tweakVars[imgToken]=")


def test_boot_js_image_tweak_omits_token_without_valid_value():
    # No stored value (image tweaks carry no default) or a regex miss must
    # omit the token entirely — the branch null-safe-reads the value, adds
    # nothing to tweakVars on a miss, and terminates in its own `continue`
    # so it never falls through to the template/default composition below.
    branch = _image_branch()
    assert "String(value==null?'':value)" in branch
    assert "\n      continue;\n    }" in branch
    assert "tweakVars[" not in branch.replace("tweakVars[imgToken]=", "")


def test_boot_js_image_url_flows_into_prepaint_cache_untouched():
    # The composed url() rides the SAME writer as every other tweak value —
    # no separate image path that could skip the cache (or dodge the
    # over-4KB drop).
    block = _function_block(BOOT_JS, "_applyPackTweakValues")
    assert "_writePackPrepaintCache(pack,tweakVars)" in block


# ── panels.js: the image control ─────────────────────────────────────────────


def test_panels_js_image_control_posts_raw_file_to_upload_route():
    # Mirrors the attachment upload convention (ui.js): base-relative URL,
    # credentials:'include', the File as the raw body, its MIME type as the
    # Content-Type. The global fetch wrapper adds the CSRF header.
    control = _function_block(PANELS_JS, "_buildPackTweakControl")
    assert "case 'image':" in control
    img_case = control[control.index("case 'image':") :]
    assert "api/skins/${encodeURIComponent(pack.key)}/upload" in img_case
    assert "method:'POST',credentials:'include',body:file" in img_case
    assert "'Content-Type':file.type" in img_case


def test_panels_js_image_control_validates_before_posting():
    # Client-side pre-check: the four accepted MIME types and the 2MB cap,
    # with the dedicated invalid-file toast — never a POST on violation.
    assert "_PACK_IMAGE_MIME_TYPES" in PANELS_JS
    assert "_PACK_IMAGE_MAX_BYTES=2*1024*1024" in PANELS_JS
    control = _function_block(PANELS_JS, "_buildPackTweakControl")
    img_case = control[control.index("case 'image':") :]
    assert "_PACK_IMAGE_MIME_TYPES.has(file.type)" in img_case
    assert "file.size>_PACK_IMAGE_MAX_BYTES" in img_case
    assert "settings_skins_pack_tweak_upload_invalid" in img_case
    assert "settings_skins_pack_tweak_upload_failed" in img_case


def test_panels_js_image_upload_commits_through_shared_chain():
    # The uploaded filename commits through the SAME commit closure every
    # other control uses (state → _applyPackTweakValues → autosave), and
    # the row re-renders so the preview appears.
    control = _function_block(PANELS_JS, "_buildPackTweakControl")
    commit = control[control.index("const commit=value=>{") : control.index("const commit=value=>{") + 600]
    assert "window._skinTweaksState[pack.key][tweak.id]=value" in commit
    assert "_applyPackTweakValues(pack.key,window._skinTweaksState[pack.key])" in commit
    assert "_scheduleAppearanceAutosave()" in commit
    img_case = control[control.index("case 'image':") :]
    assert "commit(data.file)" in img_case
    assert "_renderSkinPackTweaks(pack)" in img_case


def test_panels_js_image_remove_flow_drops_state_and_rerenders():
    # Remove deletes the stored state entry, re-applies (boot.js then omits
    # the token), autosaves, and re-renders so the preview disappears.
    control = _function_block(PANELS_JS, "_buildPackTweakControl")
    img_case = control[control.index("case 'image':") :]
    remove_zone = img_case[img_case.index("settings_skins_pack_tweaks_remove") :]
    assert "delete window._skinTweaksState[pack.key][tweak.id]" in remove_zone
    assert "_applyPackTweakValues(pack.key," in remove_zone
    assert "_scheduleAppearanceAutosave()" in remove_zone
    assert "_renderSkinPackTweaks(pack)" in remove_zone
    # preview: img only when the stored value matches the filename regex
    assert "_PACK_TWEAK_UPLOAD_FILE_RE.test(current)" in img_case
    assert "skin-pack-tweak-preview" in img_case
    assert "src=`/api/skins/${encodeURIComponent(pack.key)}/uploads/${storedFileName}`" in img_case


def test_panels_js_render_filter_includes_image_type():
    # The tweak list filter must admit the new type or the control never
    # renders; the four existing types stay.
    block = _function_block(PANELS_JS, "_renderSkinPackTweaks")
    assert "['range','select','toggle','color','image'].includes(tweak.type)" in block


# ── i18n + chrome ────────────────────────────────────────────────────────────


def test_i18n_declares_image_tweak_strings_in_en_and_zh():
    for key, en, zh in (
        ("settings_skins_pack_tweaks_upload", "Upload image", "上传图片"),
        ("settings_skins_pack_tweaks_remove", "Remove", "移除"),
        ("settings_skins_pack_tweak_upload_failed", "Upload failed", "上传失败"),
        (
            "settings_skins_pack_tweak_upload_invalid",
            "Only PNG/JPEG/GIF/WebP up to 2MB",
            "仅支持 PNG/JPEG/GIF/WebP，最大 2MB",
        ),
    ):
        assert f"{key}: '{en}'" in I18N_JS, key
        assert f"{key}: '{zh}'" in I18N_JS, key


def test_style_css_declares_image_control_chrome():
    assert ".skin-pack-tweak-image" in STYLE_CSS
    preview = STYLE_CSS.split(".skin-pack-tweak-preview", 1)[1][:300]
    assert "width:64px;height:64px" in preview
    assert "object-fit:contain" in preview
    assert "border-radius" in preview and "border:" in preview


# ── aurora demo pack ─────────────────────────────────────────────────────────


def test_aurora_manifest_declares_corner_image_tweak():
    tweaks = {t["id"]: t for t in AURORA_MANIFEST.get("tweaks", [])}
    tweak = tweaks.get("corner-image")
    assert tweak is not None, "corner-image tweak missing"
    assert tweak["type"] == "image"
    assert tweak["label"] == {"en": "Corner image", "zh": "角落图片"}
    assert tweak["apply"] == {"var": "pack-corner-image"}
    # image tweaks carry no default/template/class
    assert "default" not in tweak and "template" not in tweak
    assert "class" not in tweak["apply"]
    # the four pre-existing tweak types are untouched
    assert {"glow-strength", "accent-tone", "compact-chips", "accent-color"} <= set(tweaks)
    # the icons block is untouched
    assert AURORA_MANIFEST["icons"]["logoSvg"] == "icons/logo-512.png"


def test_aurora_theme_consumes_corner_image_token_with_none_fallback():
    # The consumption rule: var(--pack-corner-image, none) so an absent
    # token paints nothing; scoped to the pack skin key, inert to pointer
    # events, and mirrored for dark mode with its own opacity.
    assert 'var(--pack-corner-image,none)' in AURORA_THEME or 'var(--pack-corner-image, none)' in AURORA_THEME
    assert re.search(
        r':root\[data-skin="pack:aurora"\] \.messages-shell::after\{[^}]*var\(--pack-corner-image, ?none\)',
        AURORA_THEME,
    )
    assert "pointer-events:none" in AURORA_THEME
    assert re.search(
        r':root\.dark\[data-skin="pack:aurora"\] \.messages-shell::after\{[^}]*opacity',
        AURORA_THEME,
    )
