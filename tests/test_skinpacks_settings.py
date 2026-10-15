"""Skin pack settings keys (skin-pack feature, W2).

`api/config.py` owns three pack-aware settings — `skin_pack`,
`skin_tweaks`, `skin_script_consents` — validated against the packs
`api.skinpacks.discover_skin_packs()` finds, on both the load path and the
save path. These tests pin:

- the keys exist in `_SETTINGS_DEFAULTS` and land in
  `_SETTINGS_ALLOWED_KEYS` via its defaults-derived construction
- valid values round-trip save_settings -> settings.json -> load_settings
- invalid values never reach the returned dict or disk: unknown pack keys,
  unknown tweak ids, out-of-range ranges, non-option selects, non-bool
  consents, and non-hex colours are dropped or coerced by the frozen
  `api.skinpacks` normalizers
- the per-pack tweak/consent maps deep-merge on save, so writing one pack's
  tweaks preserves another pack's stored entries
- settings loading/saving stay unconditionally robust: a broken pack
  discovery can never raise out of load_settings or save_settings, and a
  discovery failure during save keeps the values already on disk
"""

import json
from pathlib import Path

import pytest

import api.config as config
from api import skinpacks


def _fixture_packs() -> dict:
    """Two packs in the normalized shape discover_skin_packs() returns:
    aurora carries one tweak of each type; borealis exists so the deep-merge
    tests have a second pack key."""
    return {
        "aurora": {
            "key": "aurora",
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
                },
                {
                    "id": "density",
                    "label": "Density",
                    "type": "select",
                    "options": [
                        {"value": "cozy", "label": "Cozy"},
                        {"value": "roomy", "label": "Roomy"},
                    ],
                    "default": "cozy",
                    "apply": {"var": "pack-density"},
                },
                {
                    "id": "glow",
                    "label": "Glow",
                    "type": "toggle",
                    "default": False,
                    "apply": {"class": "pack-glow"},
                },
                {
                    "id": "accent",
                    "label": "Accent",
                    "type": "color",
                    "default": "#3388ff",
                    "apply": {"var": "accent"},
                },
            ],
        },
        "borealis": {
            "key": "borealis",
            "tweaks": [
                {
                    "id": "radius",
                    "label": "Radius",
                    "type": "range",
                    "min": 0,
                    "max": 10,
                    "step": 1,
                    "default": 4,
                    "apply": {"var": "pack-radius", "template": "{value}px"},
                },
            ],
        },
    }


@pytest.fixture()
def pack_env(tmp_path, monkeypatch):
    """Isolated SETTINGS_FILE + deterministic fixture packs (monkeypatch
    patterns mirror test_atomic_settings_writes.py and
    test_settings_appearance_defaults_honoured.py)."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)
    packs = _fixture_packs()
    monkeypatch.setattr(skinpacks, "discover_skin_packs", lambda: packs)
    return settings_file


def _read_disk(settings_file: Path) -> dict:
    return json.loads(settings_file.read_text(encoding="utf-8"))


# ── defaults + allow-list ──────────────────────────────────────────────────


def test_fresh_load_has_pack_defaults(pack_env):
    assert not pack_env.exists()
    s = config.load_settings()
    assert s["skin_pack"] == ""
    assert s["skin_tweaks"] == {}
    assert s["skin_script_consents"] == {}


def test_pack_keys_are_save_allowed():
    # _SETTINGS_ALLOWED_KEYS derives from the defaults keys minus an
    # exclusion set; the pack keys must land in it without a manual entry.
    assert {
        "skin_pack",
        "skin_tweaks",
        "skin_script_consents",
    } <= config._SETTINGS_ALLOWED_KEYS


# ── save round-trip ────────────────────────────────────────────────────────


def test_valid_pack_settings_round_trip(pack_env):
    tweaks = {"aurora": {"radius": 12, "density": "roomy", "glow": True, "accent": "#ff5500"}}
    saved = config.save_settings(
        {
            "skin_pack": "aurora",
            "skin_tweaks": tweaks,
            "skin_script_consents": {"aurora": True},
        }
    )
    assert saved["skin_pack"] == "aurora"
    assert saved["skin_tweaks"] == tweaks
    assert saved["skin_script_consents"] == {"aurora": True}
    assert _read_disk(pack_env)["skin_pack"] == "aurora"
    loaded = config.load_settings()
    assert loaded["skin_pack"] == "aurora"
    assert loaded["skin_tweaks"] == tweaks
    assert loaded["skin_script_consents"] == {"aurora": True}


# ── invalid values never reach disk ────────────────────────────────────────


def test_unknown_pack_key_on_write_normalizes_to_empty(pack_env):
    saved = config.save_settings({"skin_pack": "ghost"})
    assert saved["skin_pack"] == ""
    assert _read_disk(pack_env)["skin_pack"] == ""


def test_unknown_tweak_id_dropped_on_save(pack_env):
    saved = config.save_settings({"skin_tweaks": {"aurora": {"radius": 5, "nope": 1}}})
    assert saved["skin_tweaks"] == {"aurora": {"radius": 5}}


@pytest.mark.parametrize("raw,expected", [(999, 24), (-5, 0)])
def test_range_value_clamped_on_save(pack_env, raw, expected):
    saved = config.save_settings({"skin_tweaks": {"aurora": {"radius": raw}}})
    assert saved["skin_tweaks"]["aurora"]["radius"] == expected


def test_select_value_coerced_to_default_on_save(pack_env):
    saved = config.save_settings({"skin_tweaks": {"aurora": {"density": "huge"}}})
    assert saved["skin_tweaks"]["aurora"]["density"] == "cozy"


@pytest.mark.parametrize("raw,expected", [("yes", True), (0, False), (1, True)])
def test_toggle_value_coerced_to_bool_on_save(pack_env, raw, expected):
    saved = config.save_settings({"skin_tweaks": {"aurora": {"glow": raw}}})
    assert saved["skin_tweaks"]["aurora"]["glow"] is expected


def test_invalid_color_dropped_on_save(pack_env):
    # "orange" is a valid CSS colour keyword but not a hex value — the color
    # tweak regex (^#[0-9a-fA-F]{3,8}$) must reject it, and an empty kept-map
    # drops the pack entry entirely.
    saved = config.save_settings({"skin_tweaks": {"aurora": {"accent": "orange"}}})
    assert saved["skin_tweaks"] == {}


def test_consents_keep_bools_for_known_packs_only(pack_env):
    saved = config.save_settings(
        {"skin_script_consents": {"aurora": True, "borealis": False, "ghost": True, "aurora-2": "yes"}}
    )
    assert saved["skin_script_consents"] == {"aurora": True, "borealis": False}


# ── deep-merge preserves other packs' entries ──────────────────────────────


def test_saving_pack_b_tweaks_preserves_pack_a_tweaks(pack_env):
    config.save_settings({"skin_tweaks": {"aurora": {"radius": 12}}})
    saved = config.save_settings({"skin_tweaks": {"borealis": {"radius": 6}}})
    assert saved["skin_tweaks"] == {"aurora": {"radius": 12}, "borealis": {"radius": 6}}
    assert config.load_settings()["skin_tweaks"] == {
        "aurora": {"radius": 12},
        "borealis": {"radius": 6},
    }


# ── load-side normalization of stored values ───────────────────────────────


def test_load_normalizes_stored_pack_settings(pack_env):
    pack_env.write_text(
        json.dumps(
            {
                "skin_pack": "ghost",
                "skin_tweaks": {"aurora": {"radius": 999, "nope": 1}, "ghost": {"x": 1}},
                "skin_script_consents": {"ghost": True, "aurora": "yes"},
            }
        ),
        encoding="utf-8",
    )
    s = config.load_settings()
    assert s["skin_pack"] == ""
    assert s["skin_tweaks"] == {"aurora": {"radius": 24}}
    assert s["skin_script_consents"] == {}


# ── robustness: broken pack discovery never breaks settings ────────────────


def test_load_survives_broken_pack_discovery(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)
    settings_file.write_text(json.dumps({"skin_pack": "aurora"}), encoding="utf-8")

    def _boom():
        raise RuntimeError("broken pack directory")

    monkeypatch.setattr(skinpacks, "discover_skin_packs", _boom)

    s = config.load_settings()  # must not raise
    assert s["skin_pack"] == ""
    assert s["skin_tweaks"] == {}
    assert s["skin_script_consents"] == {}
    # Load is read-side only: the file keeps the raw stored values.
    assert _read_disk(settings_file)["skin_pack"] == "aurora"


def test_save_survives_broken_pack_discovery(pack_env, monkeypatch):
    config.save_settings({"skin_pack": "aurora", "skin_tweaks": {"aurora": {"radius": 12}}})

    def _boom():
        raise RuntimeError("broken pack directory")

    monkeypatch.setattr(skinpacks, "discover_skin_packs", _boom)

    saved = config.save_settings({"theme": "light"})  # must not raise
    assert saved["theme"] == "light"
    # Unvalidatable pack writes are rejected and the stored values kept.
    assert saved["skin_pack"] == "aurora"
    assert saved["skin_tweaks"] == {"aurora": {"radius": 12}}
    assert _read_disk(pack_env)["skin_pack"] == "aurora"


# ── atomic write behavior unaffected ───────────────────────────────────────


def test_pack_settings_save_routes_through_atomic_writer(pack_env, monkeypatch):
    calls = []
    real = config._atomic_write_settings_text

    def _spy(path, text):
        calls.append(Path(path))
        return real(path, text)

    monkeypatch.setattr(config, "_atomic_write_settings_text", _spy)

    config.save_settings({"skin_pack": "aurora"})

    assert pack_env in calls, "save_settings must use the atomic writer"


# ── transiently-invalid packs keep their tweak data ───────────────────────


def test_skin_tweaks_preserved_for_transiently_invalid_pack(pack_env, monkeypatch):
    # A pack whose directory exists but whose manifest currently fails
    # validation is absent from discover_skin_packs() — its stored tweaks
    # must survive verbatim (dir present), or a transient validation failure
    # erases the user's data.
    packs = _fixture_packs()
    packs.pop("aurora")
    monkeypatch.setattr(skinpacks, "discover_skin_packs", lambda: packs)
    monkeypatch.setattr(skinpacks, "pack_dir_keys", lambda: {"aurora", "borealis"})

    config.save_settings(
        {"skin_tweaks": {"aurora": {"radius": 12, "anything": "kept verbatim"}}}
    )
    loaded = config.load_settings()

    assert loaded["skin_tweaks"]["aurora"] == {
        "radius": 12,
        "anything": "kept verbatim",
    }, "dir-present pack keeps stored tweaks untouched through save+load"


def test_skin_tweaks_dropped_when_pack_dir_gone(pack_env, monkeypatch):
    # Directory gone (pack truly uninstalled) → the stored tweaks are
    # dropped, matching the original cleanup semantics.
    packs = _fixture_packs()
    packs.pop("aurora")
    monkeypatch.setattr(skinpacks, "discover_skin_packs", lambda: packs)
    monkeypatch.setattr(skinpacks, "pack_dir_keys", lambda: set())

    config.save_settings({"skin_tweaks": {"aurora": {"radius": 12}}})
    loaded = config.load_settings()

    assert "aurora" not in loaded["skin_tweaks"]


def test_normalize_skin_tweaks_dir_keys_unit():
    packs = _fixture_packs()
    raw = {
        "aurora": {"radius": 9},
        "ghost": {"x": 1},
    }
    # ghost's dir exists → preserved verbatim (no schema to validate against)
    kept = skinpacks.normalize_skin_tweaks(raw, packs, dir_keys={"ghost"})
    assert kept["ghost"] == {"x": 1}
    assert kept["aurora"] == {"radius": 9}
    # no dir → dropped
    dropped = skinpacks.normalize_skin_tweaks(raw, packs, dir_keys=set())
    assert "ghost" not in dropped
    # legacy call shape (no dir_keys) → dropped, back-compat
    legacy = skinpacks.normalize_skin_tweaks(raw, packs)
    assert "ghost" not in legacy
