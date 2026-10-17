"""Source-contract tests for the custom-provider WebUI write path.

Pins the frontend half of the custom_providers API contract (plan
custom-provider-webui T2): the Add-custom-provider trigger + modal markup in
static/index.html, the endpoint calls and mutation flow in static/panels.js,
the i18n key set across every locale block in static/i18n.js, the editable
custom-card branch, and the supporting style.css classes.

Same source-contract style as tests/test_custom_providers_in_panel.py;
locale-block extraction reuses the helpers from tests/test_login_locale_parity.py.
"""

from pathlib import Path
import re

import pytest

from tests.test_login_locale_parity import (
    _i18n_locale_block,
    _i18n_top_level_locale_keys,
    _value_of,
)

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


PANELS_JS = _read("static/panels.js")
INDEX_HTML = _read("static/index.html")
STYLE_CSS = _read("static/style.css")

ALL_LOCALES = _i18n_top_level_locale_keys()

NEW_I18N_KEYS = (
    "providers_custom_add",
    "providers_custom_add_title",
    "providers_custom_edit_title",
    "providers_custom_name",
    "providers_custom_name_placeholder",
    "providers_custom_base_url",
    "providers_custom_base_url_placeholder",
    "providers_custom_api_key",
    "providers_custom_key_show",
    "providers_custom_key_hide",
    "providers_custom_key_hint",
    "providers_custom_key_hint_edit_has",
    "providers_custom_key_hint_edit_none",
    "providers_custom_key_configured",
    "providers_custom_key_not_configured",
    "providers_custom_discover_models",
    "providers_custom_remote_models",
    "providers_custom_fetch_models",
    "providers_custom_fetching",
    "providers_custom_fetch_ok",
    "providers_custom_fetch_needs_url",
    "providers_custom_fetch_manual_hint",
    "providers_custom_default_model",
    "providers_custom_default_model_placeholder",
    "providers_custom_manual_models",
    "providers_custom_manual_models_placeholder",
    "providers_custom_manual_models_hint",
    "providers_custom_model_chip_title",
    "providers_custom_name_required",
    "providers_custom_base_url_required",
    "providers_custom_save_failed",
    "providers_custom_created",
    "providers_custom_updated",
    "providers_custom_edit",
    "providers_custom_delete",
    "providers_custom_delete_confirm",
    "providers_custom_deleted",
    "providers_custom_delete_failed",
    "providers_custom_refresh_ok",
)


def _function_body(src: str, name: str) -> str:
    """Return the brace-balanced body of `[async] function <name>(...)` in src."""
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", src, re.M)
    assert m, f"function {name} not found"
    i = src.find("{", m.end())
    assert i >= 0
    depth = 0
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
        j += 1
    raise AssertionError(f"function {name} body never closed")


class TestAddProviderTriggerAndModalMarkup:
    """static/index.html carries the trigger button + kanban-pattern modal."""

    def test_add_trigger_button_in_providers_pane(self):
        pane_start = INDEX_HTML.find('id="settingsPaneProviders"')
        assert pane_start >= 0
        pane_seg = INDEX_HTML[pane_start : pane_start + 1200]
        assert 'id="addCustomProviderBtn"' in pane_seg
        assert 'onclick="openCustomProviderModal()"' in pane_seg
        assert 'data-i18n="providers_custom_add"' in pane_seg

    def test_modal_overlay_dialog_contract(self):
        assert (
            '<div class="kanban-modal-overlay" id="customProviderModal" hidden '
            'onclick="if(event.target===this)closeCustomProviderModal()">'
        ) in INDEX_HTML
        assert (
            '<div class="kanban-modal" role="dialog" aria-modal="true" '
            'aria-labelledby="customProviderModalTitle">'
        ) in INDEX_HTML

    def test_modal_field_ids_present(self):
        for field_id in (
            "customProviderModalMode",
            "customProviderModalOriginalName",
            "customProviderModalName",
            "customProviderModalBaseUrl",
            "customProviderModalApiKey",
            "customProviderModalKeyToggle",
            "customProviderModalKeyHint",
            "customProviderModalDiscover",
            "customProviderModalFetchBtn",
            "customProviderModalProbeStatus",
            "customProviderModalModelChips",
            "customProviderModalModel",
            "customProviderModalModels",
            "customProviderModalError",
            "customProviderModalSubmit",
        ):
            assert f'id="{field_id}"' in INDEX_HTML, f"missing #{field_id}"

    def test_error_and_probe_rows_are_aria_live(self):
        assert 'id="customProviderModalError" aria-live="polite"' in INDEX_HTML
        assert 'id="customProviderModalProbeStatus" aria-live="polite"' in INDEX_HTML

    def test_key_input_is_password_and_not_prefilled(self):
        m = re.search(r'<input[^>]*id="customProviderModalApiKey"[^>]*>', INDEX_HTML)
        assert m, "API key input missing"
        tag = m.group(0)
        assert 'type="password"' in tag
        assert 'autocomplete="new-password"' in tag
        assert "value=" not in tag, "key input must never carry a static value"

    def test_discover_checkbox_defaults_checked(self):
        m = re.search(r'<input[^>]*id="customProviderModalDiscover"[^>]*>', INDEX_HTML)
        assert m, "discover checkbox missing"
        assert "checked" in m.group(0)

    def test_static_labels_use_data_i18n(self):
        for key in (
            "providers_custom_add_title",
            "providers_custom_name",
            "providers_custom_base_url",
            "providers_custom_api_key",
            "providers_custom_discover_models",
            "providers_custom_fetch_models",
            "providers_custom_default_model",
            "providers_custom_manual_models",
            "providers_custom_manual_models_hint",
            "providers_custom_key_show",
        ):
            assert f'data-i18n="{key}"' in INDEX_HTML, f"missing data-i18n={key}"


class TestPanelsJsCustomProviderFlow:
    """static/panels.js implements the endpoint contract + modal/card behavior."""

    def test_endpoint_calls_present(self):
        assert "api('/api/providers/custom',{method:'POST'" in PANELS_JS
        assert (
            "api('/api/providers/custom/delete',{method:'POST',"
            "body:JSON.stringify({name})})"
        ) in PANELS_JS
        # Probe endpoint used in BOTH modes: ad-hoc {base_url[,api_key]} in the
        # modal and named {name} on the card.
        assert PANELS_JS.count("/api/providers/custom/models") >= 2
        fetch_body = _function_body(PANELS_JS, "fetchCustomProviderModels")
        assert "const payload={base_url:baseUrl};" in fetch_body
        assert "if(apiKey) payload.api_key=apiKey;" in fetch_body
        refresh_body_src = re.search(
            r"async function _refreshCustomProviderModels\(entry,btn\)\{.*?\n\}",
            PANELS_JS,
            re.S,
        )
        assert refresh_body_src
        assert "body:JSON.stringify({name})" in refresh_body_src.group(0)

    def test_new_functions_defined(self):
        for fn in (
            "openCustomProviderModal",
            "closeCustomProviderModal",
            "submitCustomProviderModal",
            "fetchCustomProviderModels",
            "toggleCustomProviderKeyVisibility",
            "_deleteCustomProvider",
            "_refreshCustomProviderModels",
            "_buildCustomProviderCardBody",
            "_customProviderModalEsc",
            "_renderCustomProviderModelChips",
            "_setCustomProviderProbeStatus",
        ):
            assert re.search(rf"^(async )?function {re.escape(fn)}\(", PANELS_JS, re.M), (
                f"missing function {fn}"
            )

    def test_modal_focus_trap_and_escape(self):
        open_body = _function_body(PANELS_JS, "openCustomProviderModal")
        assert "_customProviderModalFocusCleanup=_trapModalFocus(modal);" in open_body
        assert "document.addEventListener('keydown',_customProviderModalEsc);" in open_body
        close_body = _function_body(PANELS_JS, "closeCustomProviderModal")
        assert "document.removeEventListener('keydown',_customProviderModalEsc);" in close_body
        esc_body = _function_body(PANELS_JS, "_customProviderModalEsc")
        assert "if(ev.key==='Escape') closeCustomProviderModal();" in esc_body

    def test_submit_payload_contract(self):
        body = _function_body(PANELS_JS, "submitCustomProviderModal")
        # create omits original_name; edit sends the entry's current name
        assert "const payload={name,base_url:baseUrl,discover_models:discover};" in body
        assert "if(mode==='edit'&&originalName) payload.original_name=originalName;" in body
        # key only when the user typed one
        assert "if(apiKey) payload.api_key=apiKey;" in body
        # manual models: split lines, trim, drop empties, dedup; empty → omit
        assert "manualRaw.split('\\n').map(s=>s.trim()).filter(Boolean)" in body
        assert "if(!seen.has(id)){seen.add(id);models.push(id);}" in body
        assert "if(models.length) payload.models=models;" in body
        assert "if(model) payload.model=model;" in body

    def test_key_input_write_only_in_open(self):
        body = _function_body(PANELS_JS, "openCustomProviderModal")
        assert "keyEl.value='';" in body
        # The stored key is never read back into the form: no assignment from
        # the entry besides name/base_url/model/models/discover/has_key.
        assert "keyEl.value=" in body and body.count("keyEl.value=") == 1
        assert "entry.api_key" not in body

    def test_close_clears_key_input(self):
        body = _function_body(PANELS_JS, "closeCustomProviderModal")
        assert "keyEl.value='';" in body

    def test_mutations_reload_panel_and_refresh_dropdowns(self):
        for fn in ("submitCustomProviderModal", "_deleteCustomProvider"):
            body = _function_body(PANELS_JS, fn)
            assert "_refreshModelDropdownsAfterProviderChange();" in body, fn
            assert "await loadProvidersPanel();" in body, fn
        refresh_seg = re.search(
            r"async function _refreshCustomProviderModels\(entry,btn\)\{.*?\n\}",
            PANELS_JS,
            re.S,
        ).group(0)
        assert "_refreshModelDropdownsAfterProviderChange();" in refresh_seg
        assert "await loadProvidersPanel();" in refresh_seg

    def test_delete_uses_confirm_dialog(self):
        body = _function_body(PANELS_JS, "_deleteCustomProvider")
        assert "showConfirmDialog({" in body
        assert "danger:true" in body
        assert "if(!ok) return;" in body

    def test_probe_failure_is_inline_notice_not_crash(self):
        body = _function_body(PANELS_JS, "fetchCustomProviderModels")
        assert "}catch(e){" in body
        assert "_setCustomProviderProbeStatus(_customProviderApiErrorDetail(e),'error');" in body
        fail_msg = _function_body(PANELS_JS, "_customProviderProbeFailureMessage")
        assert "providers_custom_fetch_manual_hint" in fail_msg

    def test_submit_error_shows_detail(self):
        body = _function_body(PANELS_JS, "submitCustomProviderModal")
        assert "(res&&(res.detail||res.error))" in body
        detail_helper = _function_body(PANELS_JS, "_customProviderApiErrorDetail")
        assert "JSON.parse(e.body)" in detail_helper
        assert "j.detail||j.error" in detail_helper

    def test_submit_disables_button_while_posting(self):
        body = _function_body(PANELS_JS, "submitCustomProviderModal")
        assert "submitBtn.disabled=true;" in body
        assert body.count("submitBtn.disabled=false;") >= 2


class TestCustomCardBranch:
    """is_custom cards render editable affordances; other branches untouched."""

    def test_read_only_hint_removed(self):
        assert "Custom provider loaded from config.yaml / hermes model" not in PANELS_JS

    def test_build_provider_card_routes_is_custom(self):
        assert "}else if(p.is_custom){" in PANELS_JS
        assert "body.appendChild(_buildCustomProviderCardBody(p));" in PANELS_JS
        # non-custom unmanaged providers keep their hint
        assert "Provider is managed outside the WebUI." in PANELS_JS

    def test_other_branches_untouched(self):
        assert "filter(p=>p.configurable||p.is_oauth||p.is_custom||p.is_plugin_provider||p.is_self_hosted)" in PANELS_JS
        assert "if(p.configurable){" in PANELS_JS
        assert "if(p.is_self_hosted){" in PANELS_JS
        assert "if(isOauth){" in PANELS_JS

    def test_card_has_edit_and_delete_affordances(self):
        body = _function_body(PANELS_JS, "_buildCustomProviderCardBody")
        assert "editBtn.onclick=()=>openCustomProviderModal(p);" in body
        assert "deleteBtn.onclick=()=>_deleteCustomProvider(p.name,deleteBtn);" in body
        assert "provider-card-btn-danger" in body

    def test_card_shows_key_status_but_never_the_key(self):
        body = _function_body(PANELS_JS, "_buildCustomProviderCardBody")
        assert "providers_custom_key_configured" in body
        assert "providers_custom_key_not_configured" in body
        assert "p.has_key" in body
        assert "api_key" not in body
        assert "key_env" not in body
        assert "base_url" in body  # URL is not a secret and is shown

    def test_card_refresh_wired_to_named_mode(self):
        assert "refreshBtn.onclick=p.is_custom" in PANELS_JS
        assert "()=>_refreshCustomProviderModels(p,refreshBtn)" in PANELS_JS
        assert "()=>_refreshProviderModels(p.id, refreshBtn)" in PANELS_JS

    def test_fetched_models_render_as_clickable_chips(self):
        body = _function_body(PANELS_JS, "_renderCustomProviderModelChips")
        assert "custom-provider-model-chip" in body
        assert "chip.onclick=()=>{" in body
        assert "modelInput.value=id;" in body


class TestI18nKeys:
    """providers_custom_* keys exist in every locale block (parity-safe)."""

    @pytest.mark.parametrize("loc", ALL_LOCALES)
    def test_keys_present_in_locale(self, loc):
        block = _i18n_locale_block(loc)
        missing = [k for k in NEW_I18N_KEYS if _value_of(block, k) is None]
        assert not missing, f"locale {loc!r} missing keys: {missing}"

    @pytest.mark.parametrize("loc", ALL_LOCALES)
    def test_keys_not_duplicated_in_locale(self, loc):
        block = _i18n_locale_block(loc)
        dups = [
            k
            for k in NEW_I18N_KEYS
            if len(re.findall(rf"^\s*{re.escape(k)}:", block, re.M)) != 1
        ]
        assert not dups, f"locale {loc!r} duplicate/absent keys: {dups}"

    def test_keys_present_in_en_and_zh(self):
        for loc in ("en", "zh"):
            block = _i18n_locale_block(loc)
            for k in NEW_I18N_KEYS:
                assert _value_of(block, k) is not None, f"{loc}:{k} missing"

    @pytest.mark.parametrize("loc", ["zh", "zh-Hant", "ja", "ko", "cs", "pl", "tr"])
    def test_core_keys_are_translated_not_english(self, loc):
        en_block = _i18n_locale_block("en")
        block = _i18n_locale_block(loc)
        leaks = []
        for k in (
            "providers_custom_add",
            "providers_custom_name",
            "providers_custom_delete",
            "providers_custom_fetch_models",
            "providers_custom_default_model",
        ):
            en_val = _value_of(en_block, k)
            loc_val = _value_of(block, k)
            if loc_val is not None and en_val and loc_val == en_val:
                leaks.append(f"{k}={loc_val!r}")
        assert not leaks, f"locale {loc!r} leaks English: {leaks}"

    @pytest.mark.parametrize("loc", ALL_LOCALES)
    def test_placeholders_preserved(self, loc):
        block = _i18n_locale_block(loc)
        for k, placeholder in (
            ("providers_custom_fetch_ok", "{0}"),
            ("providers_custom_refresh_ok", "{0}"),
            ("providers_custom_delete_confirm", "{name}"),
        ):
            val = _value_of(block, k)
            assert val is not None and placeholder in val, f"{loc}:{k} lost {placeholder}"


class TestStyles:
    """style.css carries the card + modal classes referenced by JS/markup."""

    @pytest.mark.parametrize(
        "selector",
        [
            ".providers-add-custom-btn{",
            ".provider-card-custom{",
            ".provider-card-custom-url{",
            ".provider-card-custom-keystatus{",
            ".provider-card-custom-keystatus.has-key{",
            ".custom-provider-key-row{",
            ".custom-provider-key-row input{",
            ".custom-provider-checkbox-label input[type=\"checkbox\"]{",
            ".custom-provider-probe-status{",
            ".custom-provider-probe-status-ok{",
            ".custom-provider-probe-status-error{",
            ".custom-provider-model-chips{",
            ".custom-provider-model-chip{",
            ".custom-provider-model-chip.selected{",
        ],
    )
    def test_selector_present(self, selector):
        assert selector in STYLE_CSS

    def test_new_rules_use_css_variables(self):
        seg = STYLE_CSS[STYLE_CSS.find(".custom-provider-key-row{") :]
        seg = seg[: seg.find(".kanban-empty{")]
        assert "var(--" in seg
        chip = STYLE_CSS[STYLE_CSS.find(".custom-provider-model-chip{") :]
        chip = chip[: chip.find("}")]
        assert "var(--border)" in chip
