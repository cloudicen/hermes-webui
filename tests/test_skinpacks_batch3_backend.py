"""Skin pack batch-3 backend tests: applyMode + localized text fields.

Batch 3 extends the frozen manifest schema in ``api/skinpacks.py`` with:

- ``applyMode``: ``"pack"`` (default) | ``"css-key"`` — how the frontend
  applies a pack. The server validates the enum ONLY and never restricts
  which keys may use ``css-key`` (the frontend owns application). An enum
  violation drops the field to the default, not the pack.
- localized text: ``name``, ``description``, ``tweaks[].label`` and
  ``tweaks[].options[].label`` accept either the plain string form or a
  ``{"<locale>": "<text>"}`` object (1-8 entries, locale
  ``^[a-z]{2}(-[A-Za-z0-9]{2,8})?$``, values within the field's length
  limit). The RAW form is preserved for the frontend to resolve per locale.
  Invalid locale keys and over-length values drop just that entry; an object
  left empty falls back to the field's absence behaviour (name rejects the
  pack, description becomes "", a tweak label drops the tweak, an option
  label drops the option).

Plus the ``GET /api/skins`` projection: ``applyMode`` rides along and the
localized objects survive JSON serialization.
"""

import json
from types import SimpleNamespace

from api.skinpacks import discover_skin_packs


class FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
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


def _manifest(**overrides):
    manifest = {
        "schemaVersion": 1,
        "key": "batch3",
        "name": "Batch Three",
        "version": "1.0.0",
        "author": "Someone",
        "description": "A batch-3 pack",
        "scheme": "auto",
    }
    manifest.update(overrides)
    return manifest


def _write_pack(root, key, manifest):
    pack_dir = root / key
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack_dir


def _discover(tmp_path, manifests):
    builtin = tmp_path / "builtin"
    builtin.mkdir(exist_ok=True)
    for key, manifest in manifests:
        _write_pack(builtin, key, manifest)
    return discover_skin_packs(builtin_root=builtin, user_root=tmp_path / "no-user")


_TOGGLE = {
    "id": "glow", "label": "Glow", "type": "toggle",
    "default": True, "apply": {"class": "pack-glow"},
}


# ── applyMode ───────────────────────────────────────────────────────────────


def test_apply_mode_validated_and_defaulted(tmp_path):
    packs = _discover(
        tmp_path,
        [
            ("explicit", _manifest(key="explicit", applyMode="css-key")),
            ("absent", _manifest(key="absent")),
            ("violation", _manifest(key="violation", applyMode="blue")),
            ("wrong-type", _manifest(key="wrong-type", applyMode=True)),
            # the frontend owns application: a non-builtin key may declare css-key
            ("custom-css", _manifest(key="custom-css", applyMode="css-key")),
        ],
    )
    assert packs["explicit"]["applyMode"] == "css-key"
    assert packs["absent"]["applyMode"] == "pack"
    # an enum violation drops the FIELD to the default, never the pack
    assert packs["violation"]["applyMode"] == "pack"
    assert packs["wrong-type"]["applyMode"] == "pack"
    # css-key is never key-restricted server-side
    assert packs["custom-css"]["applyMode"] == "css-key"


# ── localized text fields ───────────────────────────────────────────────────


def test_localized_fields_survive_normalization_raw(tmp_path):
    manifest = _manifest(
        key="loc",
        name={"en": "Localized", "zh": "本地化", "zh-Hant": "本地化"},
        description={"en": "A localized pack", "zh": "一个本地化皮肤包"},
        tweaks=[
            {
                **_TOGGLE,
                "label": {"en": "Glow", "zh": "发光"},
            },
            {
                "id": "tone",
                "label": "Tone",
                "type": "select",
                "default": "cyan",
                "options": [
                    {"value": "cyan", "label": {"en": "Cyan", "zh": "青色"}},
                    {"value": "teal", "label": "Teal"},
                ],
                "apply": {"var": "pack-tone"},
            },
        ],
    )
    packs = _discover(tmp_path, [("loc", manifest)])
    pack = packs["loc"]
    # the raw object form is preserved verbatim — the frontend resolves it
    assert pack["name"] == {"en": "Localized", "zh": "本地化", "zh-Hant": "本地化"}
    assert pack["description"] == {"en": "A localized pack", "zh": "一个本地化皮肤包"}
    assert pack["tweaks"][0]["label"] == {"en": "Glow", "zh": "发光"}
    assert pack["tweaks"][1]["options"][0]["label"] == {"en": "Cyan", "zh": "青色"}
    # plain-string neighbours keep their plain form
    assert pack["tweaks"][1]["label"] == "Tone"
    assert pack["tweaks"][1]["options"][1]["label"] == "Teal"


def test_bad_locale_key_drops_only_that_entry(tmp_path):
    packs = _discover(
        tmp_path,
        [
            (
                "badloc",
                _manifest(
                    key="badloc",
                    name={"en": "Fine", "EN": "dropped", "zh_CN": "dropped", "e": "dropped"},
                ),
            )
        ],
    )
    assert packs["badloc"]["name"] == {"en": "Fine"}


def test_invalid_localized_value_drops_entry(tmp_path):
    packs = _discover(
        tmp_path,
        [
            (
                "badval",
                _manifest(
                    key="badval",
                    name={"en": 42, "zh": "好"},
                    description={"en": "y" * 201, "zh": "描述"},
                ),
            )
        ],
    )
    # over-length and non-string values drop the entry, not the field/pack
    assert packs["badval"]["name"] == {"zh": "好"}
    assert packs["badval"]["description"] == {"zh": "描述"}


def test_localized_name_emptied_rejects_pack(tmp_path):
    packs = _discover(
        tmp_path,
        [
            ("dropped-name", _manifest(key="dropped-name", name={"EN": "gone"})),
            ("empty-name", _manifest(key="empty-name", name={})),
            ("neighbour", _manifest(key="neighbour")),
        ],
    )
    assert set(packs) == {"neighbour"}


def test_localized_description_emptied_defaults_to_empty_string(tmp_path):
    packs = _discover(
        tmp_path,
        [
            ("desc", _manifest(key="desc", description={"EN": "gone"})),
            ("empty-desc", _manifest(key="empty-desc", description={})),
        ],
    )
    assert packs["desc"]["description"] == ""
    assert packs["empty-desc"]["description"] == ""


def test_localized_tweak_label_emptied_drops_tweak_not_pack(tmp_path):
    packs = _discover(
        tmp_path,
        [
            (
                "tw",
                _manifest(
                    key="tw",
                    tweaks=[
                        {**_TOGGLE, "id": "gone", "label": {"EN": "x"}},
                        {**_TOGGLE, "id": "kept", "label": {"en": "Kept"}},
                    ],
                ),
            )
        ],
    )
    assert [t["id"] for t in packs["tw"]["tweaks"]] == ["kept"]
    assert packs["tw"]["tweaks"][0]["label"] == {"en": "Kept"}


def test_localized_option_label_emptied_drops_option(tmp_path):
    select = {
        "id": "tone",
        "label": "Tone",
        "type": "select",
        "default": "keep",
        "options": [
            {"value": "drop", "label": {"EN": "x"}},
            {"value": "keep", "label": {"en": "Keep", "zh": "保留"}},
        ],
        "apply": {"var": "pack-tone"},
    }
    packs = _discover(tmp_path, [("sel", _manifest(key="sel", tweaks=[select]))])
    options = packs["sel"]["tweaks"][0]["options"]
    assert options == [{"value": "keep", "label": {"en": "Keep", "zh": "保留"}}]

    # dropping the option that carried the default rejects the pack loudly:
    # the select default must remain one of the surviving option values
    orphaned = _discover(
        tmp_path,
        [
            (
                "orphan",
                _manifest(key="orphan", tweaks=[{**select, "default": "drop"}]),
            )
        ],
    )
    assert "orphan" not in orphaned


def test_locale_map_caps_at_eight_entries(tmp_path):
    nine = {
        locale: "x"
        for locale in ("en", "zh", "de", "fr", "es", "ja", "ko", "ru", "it")
    }
    packs = _discover(tmp_path, [("nine", _manifest(key="nine", name=nine))])
    assert packs["nine"]["name"] == {
        "en": "x", "zh": "x", "de": "x", "fr": "x", "es": "x", "ja": "x",
        "ko": "x", "ru": "x",
    }


def test_localized_wrong_type_keeps_existing_severity(tmp_path):
    # a non-string, non-object name still rejects the pack (frozen W1 rule)
    packs = _discover(tmp_path, [("num", _manifest(key="num", name=42))])
    assert set(packs) == set()


# ── GET /api/skins projection ───────────────────────────────────────────────


def _get_listing(tmp_path, monkeypatch, manifests):
    import api.skinpacks as skinpacks
    from api import routes

    builtin = tmp_path / "builtin"
    builtin.mkdir(exist_ok=True)
    for key, manifest in manifests:
        _write_pack(builtin, key, manifest)
    monkeypatch.setattr(skinpacks, "_default_builtin_root", lambda: builtin)
    monkeypatch.setattr(skinpacks, "_default_user_root", lambda: tmp_path / "user")

    handler = FakeHandler()
    handled = routes.handle_get(
        handler, SimpleNamespace(path="/api/skins", query="")
    )
    assert handled is not False
    listing = json.loads(bytes(handler.body).decode("utf-8"))["packs"]
    return {pack["key"]: pack for pack in listing}


def test_skins_listing_projects_apply_mode_and_localized_fields(
    tmp_path, monkeypatch
):
    listing = _get_listing(
        tmp_path,
        monkeypatch,
        [
            ("cssy", _manifest(key="cssy", applyMode="css-key",
                               name={"en": "Cssy", "zh": "键"})),
            ("plain", _manifest(key="plain")),
        ],
    )
    assert listing["cssy"]["applyMode"] == "css-key"
    # the localized object survives JSON serialization untouched
    assert listing["cssy"]["name"] == {"en": "Cssy", "zh": "键"}
    assert listing["plain"]["applyMode"] == "pack"
    assert listing["plain"]["name"] == "Batch Three"
