"""Tests for the WebUI custom-provider write path (plan custom-provider-webui T1).

Covers the three POST endpoints' logic in api/providers.py plus the
``GET /api/providers`` custom-entry field extensions:

  - ``save_custom_provider``          (POST /api/providers/custom)
  - ``delete_custom_provider``        (POST /api/providers/custom/delete)
  - ``refresh_custom_provider_models``(POST /api/providers/custom/models)

In-process tests run against an isolated tmp HERMES home (config.yaml + .env)
with the network probe mocked (conftest blocks outbound by default). One
HTTP-level test drives create → GET → delete through the real route with a
same-origin Origin header, following test_provider_mismatch.py conventions.

API keys in these tests are fake; assertions check presence/absence and
derived shapes only, never echo key material.
"""
import json
import os
import urllib.error
import urllib.request

import pytest

from tests._pytest_port import BASE

from api import yaml_compat as yaml

CUSTOM_CREATE_PATH = "/api/providers/custom"
CUSTOM_DELETE_PATH = "/api/providers/custom/delete"
CUSTOM_MODELS_PATH = "/api/providers/custom/models"


# ── Fixtures / helpers ────────────────────────────────────────────────────


@pytest.fixture
def custom_home(monkeypatch, tmp_path):
    """Isolated HERMES home: patched config path + hermes home for one test."""
    from api import config as config_mod
    from api import providers as prov

    home = tmp_path / "hermes-home"
    home.mkdir(parents=True)
    config_path = home / "config.yaml"

    real_get_config_path = config_mod._get_config_path
    monkeypatch.setattr(config_mod, "_get_config_path", lambda: config_path)
    monkeypatch.setattr(prov, "_get_hermes_home", lambda: home)

    env_keys_before = set(os.environ.keys())
    yield home
    # _write_env_file mutates os.environ directly; drop vars this test created.
    for key in set(os.environ.keys()) - env_keys_before:
        if key.startswith("CUSTOM_") and key.endswith("_API_KEY"):
            os.environ.pop(key, None)
    # Re-point the config cache at the conftest-isolated path before monkeypatch
    # teardown, so later in-process tests never read this tmp config.
    config_mod._get_config_path = real_get_config_path
    try:
        config_mod.reload_config()
    except Exception:
        pass


def _seed_config(home, config: dict) -> None:
    (home / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _read_config(home) -> dict:
    loaded = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _env_var_names(home) -> set[str]:
    env_path = home / ".env"
    if not env_path.exists():
        return set()
    names = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            names.add(stripped.split("=", 1)[0].strip())
    return names


def _quiet_providers_catalog(monkeypatch):
    """Patch api.providers for offline get_providers() (dict_models convention)."""
    import sys
    import types

    fake_pkg = types.ModuleType("hermes_cli")
    fake_pkg.__path__ = []
    fake_models = types.ModuleType("hermes_cli.models")
    fake_models.list_available_providers = lambda: []
    fake_models.provider_model_ids = lambda _pid: []
    fake_auth = types.ModuleType("hermes_cli.auth")
    fake_auth.get_auth_status = lambda _pid: {}
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.models", fake_models)
    monkeypatch.setitem(sys.modules, "hermes_cli.auth", fake_auth)

    from api import providers as prov

    monkeypatch.setattr(prov, "_PROVIDER_DISPLAY", {})
    monkeypatch.setattr(prov, "_PROVIDER_MODELS", {})
    monkeypatch.setattr(prov, "_OAUTH_PROVIDERS", frozenset())
    monkeypatch.setattr(prov, "plugin_model_provider_ids", lambda: set())
    return prov


def _mock_probe(monkeypatch, result: dict, capture: list | None = None):
    """Replace api.onboarding.probe_provider_endpoint with a canned result."""
    from api import onboarding

    def _fake_probe(provider, base_url, api_key=None, timeout=5.0):
        if capture is not None:
            capture.append({"provider": provider, "base_url": base_url, "api_key": api_key})
        return result

    monkeypatch.setattr(onboarding, "probe_provider_endpoint", _fake_probe)


def _http_post(path: str, body: dict, origin: str | None = None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
        headers["Host"] = origin.split("://", 1)[1]
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read()), exc.code
        except Exception:
            return {}, exc.code


def _http_get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        return json.loads(resp.read())


FAKE_KEY = "sk-test-0123456789abcdef"


# ── save_custom_provider: create ──────────────────────────────────────────


class TestCreateCustomProvider:
    def test_create_writes_entry_key_env_and_env_file(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {"provider": "openrouter"}})
        result = save_custom_provider(
            {
                "name": "My Gateway",
                "base_url": "https://gw.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert result == {
            "ok": True,
            "provider": {"id": "custom:my-gateway", "name": "My Gateway"},
            "action": "created",
        }
        cfg = _read_config(custom_home)
        entries = cfg["custom_providers"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "My Gateway"
        assert entry["base_url"] == "https://gw.example/v1"
        assert entry["key_env"] == "CUSTOM_MY_GATEWAY_API_KEY"
        assert "api_key" not in entry
        assert "models_discovered" not in entry
        assert "discover_models" not in entry
        assert _env_var_names(custom_home) == {"CUSTOM_MY_GATEWAY_API_KEY"}
        env_value = (custom_home / ".env").read_text(encoding="utf-8")
        assert "CUSTOM_MY_GATEWAY_API_KEY=" in env_value
        assert len(env_value.split("=", 1)[1].strip()) >= 8

    def test_create_keyless_entry(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        result = save_custom_provider(
            {"name": "Local Box", "base_url": "http://127.0.0.1:8080/v1"}
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert "key_env" not in entry
        assert not (custom_home / ".env").exists() or not _env_var_names(custom_home)

    def test_create_with_manual_models(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {})
        result = save_custom_provider(
            {
                "name": "Manual",
                "base_url": "https://manual.example",
                "models": ["b-model", "a-model", "a-model", "  "],
                "model": "a-model",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["models"] == ["b-model", "a-model"]
        assert entry["model"] == "a-model"
        assert "models_discovered" not in entry

    def test_create_with_discover_models_false(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {})
        result = save_custom_provider(
            {
                "name": "Pinned",
                "base_url": "https://pinned.example/v1",
                "discover_models": False,
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["discover_models"] is False

    def test_create_duplicate_name_rejected(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {"name": "My Gateway", "base_url": "https://other.example/v1"}
                ]
            },
        )
        result = save_custom_provider(
            {"name": "MY  gateway", "base_url": "https://gw.example/v1"}
        )
        assert result["ok"] is False
        assert result["error"] == "duplicate_name"
        assert result["detail"]
        assert len(_read_config(custom_home)["custom_providers"]) == 1

    def test_create_duplicate_base_url_rejected(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {"name": "First", "base_url": "https://gw.example/v1"}
                ]
            },
        )
        result = save_custom_provider(
            {"name": "Second", "base_url": "https://gw.example/v1/"}
        )
        assert result["ok"] is False
        assert result["error"] == "duplicate_base_url"

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "", "base_url": "https://x.example"},
            {"name": "x" * 65, "base_url": "https://x.example"},
            {"name": "bad:name", "base_url": "https://x.example"},
            {"name": "bad\nname", "base_url": "https://x.example"},
            {"name": "!!!", "base_url": "https://x.example"},
            {"name": "Ok Name", "base_url": ""},
            {"name": "Ok Name", "base_url": "ftp://x.example"},
            {"name": "Ok Name", "base_url": "http://"},
            {"name": "Ok Name", "base_url": "http://a b.example"},
            {"name": "Ok Name", "base_url": "https://x.example", "api_key": "short"},
            {"name": "Ok Name", "base_url": "https://x.example", "api_key": "ab\ncd"},
            {"name": "Ok Name", "base_url": "https://x.example", "models": "a,b"},
            {"name": "Ok Name", "base_url": "https://x.example", "models": [123]},
            {"name": "Ok Name", "base_url": "https://x.example", "models": ["x" * 201]},
            {"name": "Ok Name", "base_url": "https://x.example", "discover_models": "yes"},
        ],
    )
    def test_create_invalid_payloads_rejected(self, custom_home, payload):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {})
        result = save_custom_provider(payload)
        assert result["ok"] is False
        assert result["error"].startswith("invalid_")
        assert result["detail"]
        assert "custom_providers" not in _read_config(custom_home) or not _read_config(
            custom_home
        )["custom_providers"]

    def test_create_too_many_models_rejected(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {})
        result = save_custom_provider(
            {
                "name": "Big",
                "base_url": "https://big.example",
                "models": [f"model-{i}" for i in range(201)],
            }
        )
        assert result["ok"] is False
        assert result["error"] == "invalid_models"


# ── save_custom_provider: update ──────────────────────────────────────────


class TestUpdateCustomProvider:
    def _seeded(self, custom_home):
        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {
                        "name": "Old Name",
                        "base_url": "https://old.example/v1",
                        "key_env": "CUSTOM_OLD_NAME_API_KEY",
                        "model": "old-model",
                        "models": ["old-model", "old-extra"],
                    }
                ]
            },
        )
        (custom_home / ".env").write_text(
            "CUSTOM_OLD_NAME_API_KEY=sk-old-test-1234\n", encoding="utf-8"
        )

    def test_update_rename_preserves_key_when_omitted(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "New Name",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
            }
        )
        assert result == {
            "ok": True,
            "provider": {"id": "custom:new-name", "name": "New Name"},
            "action": "updated",
        }
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["name"] == "New Name"
        # The stored key VALUE survives the rename, migrated to the new
        # owned env var (key_env == CUSTOM_<CURRENT_SLUG>_API_KEY).
        assert entry["key_env"] == "CUSTOM_NEW_NAME_API_KEY"
        assert entry["model"] == "old-model"
        assert entry["models"] == ["old-model", "old-extra"]
        env_text = (custom_home / ".env").read_text(encoding="utf-8")
        assert "CUSTOM_NEW_NAME_API_KEY=sk-old-test-1234" in env_text
        assert "CUSTOM_OLD_NAME_API_KEY" not in env_text

    def test_update_empty_api_key_clears_key_and_env(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "Old Name",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
                "api_key": "",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert "key_env" not in entry
        assert "CUSTOM_OLD_NAME_API_KEY" not in _env_var_names(custom_home)

    def test_update_new_api_key_rewrites_env(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "Old Name",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
                "api_key": "sk-new-test-98765432",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["key_env"] == "CUSTOM_OLD_NAME_API_KEY"
        env_text = (custom_home / ".env").read_text(encoding="utf-8")
        assert env_text.count("CUSTOM_OLD_NAME_API_KEY=") == 1
        assert "sk-old-test-1234" not in env_text

    def test_update_rename_with_new_key_retires_old_owned_env(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "Renamed",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
                "api_key": "sk-fresh-test-abcdef01",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["key_env"] == "CUSTOM_RENAMED_API_KEY"
        assert _env_var_names(custom_home) == {"CUSTOM_RENAMED_API_KEY"}

    def test_update_not_found(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {})
        result = save_custom_provider(
            {
                "name": "Whatever",
                "original_name": "Ghost",
                "base_url": "https://x.example/v1",
            }
        )
        assert result["ok"] is False
        assert result["error"] == "not_found"

    def test_update_rename_to_colliding_slug(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {"name": "Alpha", "base_url": "https://alpha.example/v1"},
                    {"name": "Beta", "base_url": "https://beta.example/v1"},
                ]
            },
        )
        result = save_custom_provider(
            {
                "name": "beta",
                "original_name": "Alpha",
                "base_url": "https://alpha.example/v1",
            }
        )
        assert result["ok"] is False
        assert result["error"] == "duplicate_name"
        assert len(_read_config(custom_home)["custom_providers"]) == 2

    def test_update_models_overwrite_clears_models_discovered(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {
                        "name": "Curated",
                        "base_url": "https://curated.example/v1",
                        "models": ["stale-model"],
                        "models_discovered": True,
                    }
                ]
            },
        )
        result = save_custom_provider(
            {
                "name": "Curated",
                "original_name": "Curated",
                "base_url": "https://curated.example/v1",
                "models": ["hand-a", "hand-b"],
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["models"] == ["hand-a", "hand-b"]
        assert "models_discovered" not in entry

    def test_update_empty_models_keeps_existing(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "Old Name",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
                "models": [],
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["models"] == ["old-model", "old-extra"]

    def test_update_discover_models_false_written(self, custom_home):
        from api.providers import save_custom_provider

        self._seeded(custom_home)
        result = save_custom_provider(
            {
                "name": "Old Name",
                "original_name": "Old Name",
                "base_url": "https://old.example/v1",
                "discover_models": False,
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["discover_models"] is False


# ── delete_custom_provider ────────────────────────────────────────────────


class TestDeleteCustomProvider:
    def test_delete_removes_entry_and_owned_env_var(self, custom_home):
        from api.providers import delete_custom_provider

        _seed_config(
            custom_home,
            {
                "model": {"provider": "custom:gone"},
                "custom_providers": [
                    {
                        "name": "Gone Soon",
                        "base_url": "https://gone.example/v1",
                        "key_env": "CUSTOM_GONE_SOON_API_KEY",
                    },
                    {"name": "Stays", "base_url": "https://stays.example/v1"},
                ],
            },
        )
        (custom_home / ".env").write_text(
            "# owned by webui\nCUSTOM_GONE_SOON_API_KEY=sk-gone-test-1234\n"
            "USER_OTHER_VAR=keep-me\n",
            encoding="utf-8",
        )
        result = delete_custom_provider({"name": "gone soon"})
        assert result == {
            "ok": True,
            "provider": {"id": "custom:gone-soon"},
            "action": "deleted",
        }
        cfg = _read_config(custom_home)
        assert [e["name"] for e in cfg["custom_providers"]] == ["Stays"]
        assert cfg["model"] == {"provider": "custom:gone"}
        names = _env_var_names(custom_home)
        assert "CUSTOM_GONE_SOON_API_KEY" not in names
        assert "USER_OTHER_VAR" in names
        env_text = (custom_home / ".env").read_text(encoding="utf-8")
        assert "# owned by webui" in env_text

    def test_delete_not_found(self, custom_home):
        from api.providers import delete_custom_provider

        _seed_config(custom_home, {"custom_providers": []})
        result = delete_custom_provider({"name": "Nope"})
        assert result["ok"] is False
        assert result["error"] == "not_found"

    def test_delete_missing_name_is_not_found(self, custom_home):
        from api.providers import delete_custom_provider

        result = delete_custom_provider({})
        assert result["ok"] is False
        assert result["error"] == "not_found"

    def test_delete_preserves_user_authored_env_var(self, custom_home):
        from api.providers import delete_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {
                        "name": "Custom Env",
                        "base_url": "https://ce.example/v1",
                        "key_env": "MY_OWN_TOKEN",
                    }
                ]
            },
        )
        (custom_home / ".env").write_text(
            "MY_OWN_TOKEN=sk-user-own-12345678\n", encoding="utf-8"
        )
        result = delete_custom_provider({"name": "Custom Env"})
        assert result["ok"] is True
        assert _read_config(custom_home)["custom_providers"] == []
        assert "MY_OWN_TOKEN" in _env_var_names(custom_home)


# ── refresh_custom_provider_models ────────────────────────────────────────


class TestRefreshCustomProviderModels:
    def _seed_named(self, custom_home):
        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {
                        "name": "Probe Me",
                        "base_url": "https://probe.example/v1",
                        "key_env": "CUSTOM_PROBE_ME_API_KEY",
                    }
                ]
            },
        )
        (custom_home / ".env").write_text(
            "CUSTOM_PROBE_ME_API_KEY=sk-probe-test-1234\n", encoding="utf-8"
        )

    def test_named_mode_success_persists_models(self, custom_home, monkeypatch):
        from api.providers import refresh_custom_provider_models

        self._seed_named(custom_home)
        capture: list[dict] = []
        _mock_probe(
            monkeypatch,
            {"ok": True, "models": [{"id": "m-1", "label": "m-1"}, {"id": "m-2", "label": "m-2"}], "status": 200},
            capture,
        )
        result = refresh_custom_provider_models({"name": "Probe Me"})
        assert result["ok"] is True
        assert result["persisted"] is True
        assert result["count"] == 2
        assert result["models"] == [{"id": "m-1"}, {"id": "m-2"}]
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["models"] == ["m-1", "m-2"]
        assert entry["models_discovered"] is True
        assert len(capture) == 1
        assert capture[0]["base_url"] == "https://probe.example/v1"
        assert capture[0]["api_key"] == "sk-probe-test-1234"

    def test_named_mode_failure_leaves_config_unchanged(self, custom_home, monkeypatch):
        from api.providers import refresh_custom_provider_models

        self._seed_named(custom_home)
        _mock_probe(
            monkeypatch,
            {"ok": False, "error": "unreachable", "detail": "no route to host"},
        )
        before = (custom_home / "config.yaml").read_text(encoding="utf-8")
        result = refresh_custom_provider_models({"name": "Probe Me"})
        assert result == {
            "ok": False,
            "error": "unreachable",
            "detail": "no route to host",
        }
        assert (custom_home / "config.yaml").read_text(encoding="utf-8") == before

    def test_named_mode_auth_error_mapping(self, custom_home, monkeypatch):
        from api.providers import refresh_custom_provider_models

        self._seed_named(custom_home)
        _mock_probe(
            monkeypatch,
            {"ok": False, "error": "http_4xx", "detail": "HTTP 401", "status": 401},
        )
        result = refresh_custom_provider_models({"name": "Probe Me"})
        assert result["ok"] is False
        assert result["error"] == "auth"

    @pytest.mark.parametrize(
        ("probe_error", "expected"),
        [
            ("timeout", "timeout"),
            ("http_5xx", "http_5xx"),
            ("parse", "parse"),
            ("dns", "unreachable"),
            ("connect_refused", "unreachable"),
            ("invalid_url", "unreachable"),
        ],
    )
    def test_probe_error_mapping(self, custom_home, monkeypatch, probe_error, expected):
        from api.providers import refresh_custom_provider_models

        self._seed_named(custom_home)
        _mock_probe(monkeypatch, {"ok": False, "error": probe_error, "detail": "x"})
        result = refresh_custom_provider_models({"name": "Probe Me"})
        assert result["error"] == expected

    def test_named_mode_not_found(self, custom_home):
        from api.providers import refresh_custom_provider_models

        _seed_config(custom_home, {"custom_providers": []})
        result = refresh_custom_provider_models({"name": "Ghost"})
        assert result["ok"] is False
        assert result["error"] == "not_found"

    def test_probe_url_normalization(self, custom_home, monkeypatch):
        from api.providers import refresh_custom_provider_models

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {"name": "No V1", "base_url": "https://nov1.example"},
                    {"name": "With V1", "base_url": "https://withv1.example/v1"},
                ]
            },
        )
        capture: list[dict] = []
        _mock_probe(monkeypatch, {"ok": True, "models": [], "status": 200}, capture)
        refresh_custom_provider_models({"name": "No V1"})
        refresh_custom_provider_models({"name": "With V1"})
        assert [c["base_url"] for c in capture] == [
            "https://nov1.example/v1",
            "https://withv1.example/v1",
        ]

    def test_adhoc_mode_no_persistence(self, custom_home, monkeypatch):
        from api.providers import refresh_custom_provider_models

        _seed_config(custom_home, {})
        capture: list[dict] = []
        _mock_probe(
            monkeypatch,
            {"ok": True, "models": [{"id": "x", "label": "x"}], "status": 200},
            capture,
        )
        result = refresh_custom_provider_models(
            {"base_url": "https://adhoc.example/v1", "api_key": "sk-adhoc-test-1234"}
        )
        assert result["ok"] is True
        assert result["persisted"] is False
        assert result["count"] == 1
        assert "custom_providers" not in _read_config(custom_home)
        assert capture[0]["api_key"] == "sk-adhoc-test-1234"
        assert capture[0]["base_url"] == "https://adhoc.example/v1"

    def test_adhoc_mode_invalid_base_url(self, custom_home):
        from api.providers import refresh_custom_provider_models

        result = refresh_custom_provider_models({"base_url": "not-a-url"})
        assert result["ok"] is False
        assert result["error"] == "invalid_base_url"

    def test_missing_name_and_base_url(self, custom_home):
        from api.providers import refresh_custom_provider_models

        result = refresh_custom_provider_models({})
        assert result["ok"] is False
        assert result["error"] == "invalid_request"


# ── GET /api/providers custom-entry fields ────────────────────────────────


class TestGetProvidersCustomFields:
    def test_custom_entry_exposes_management_fields(self, custom_home, monkeypatch):
        prov = _quiet_providers_catalog(monkeypatch)
        monkeypatch.setattr(
            prov,
            "get_config",
            lambda: {
                "model": {"provider": "custom:managed"},
                "custom_providers": [
                    {
                        "name": "Managed",
                        "base_url": "https://managed.example/v1",
                        "key_env": "CUSTOM_MANAGED_API_KEY",
                        "model": "best-model",
                        "models": ["best-model", "other-model"],
                        "models_discovered": True,
                        "discover_models": False,
                    }
                ],
            },
        )
        (custom_home / ".env").write_text(
            "CUSTOM_MANAGED_API_KEY=sk-managed-test-12345\n", encoding="utf-8"
        )
        try:
            result = prov.get_providers()
            cp = next(p for p in result["providers"] if p.get("is_custom"))
            assert cp["id"] == "custom:managed"
            assert cp["name"] == "Managed"
            assert cp["base_url"] == "https://managed.example/v1"
            assert cp["model"] == "best-model"
            assert cp["models"] == [
                {"id": "best-model", "label": "best-model"},
                {"id": "other-model", "label": "other-model"},
            ]
            assert cp["models_discovered"] is True
            assert cp["discover_models"] is False
            assert cp["key_env"] == "CUSTOM_MANAGED_API_KEY"
            assert cp["has_key"] is True
            assert cp["key_source"] == "env_file"
            assert cp["configurable"] is False
        finally:
            prov.invalidate_providers_cache()

    def test_keyless_entry_defaults(self, custom_home, monkeypatch):
        prov = _quiet_providers_catalog(monkeypatch)
        monkeypatch.setattr(
            prov,
            "get_config",
            lambda: {
                "model": {},
                "custom_providers": [
                    {"name": "Bare", "base_url": "http://127.0.0.1:1234/v1"}
                ],
            },
        )
        try:
            result = prov.get_providers()
            cp = next(p for p in result["providers"] if p.get("is_custom"))
            assert cp["has_key"] is False
            assert cp["key_env"] is None
            assert cp["model"] is None
            assert cp["models_discovered"] is False
            assert cp["discover_models"] is True
            assert cp["key_source"] == "none"
        finally:
            prov.invalidate_providers_cache()

    def test_key_env_flows_through_credential_helpers(self, custom_home, monkeypatch):
        from api import providers as prov

        monkeypatch.setattr(
            prov,
            "get_config",
            lambda: {
                "model": {},
                "custom_providers": [
                    {
                        "name": "Cred Helper",
                        "base_url": "https://ch.example/v1",
                        "key_env": "CUSTOM_CRED_HELPER_API_KEY",
                    }
                ],
            },
        )
        (custom_home / ".env").write_text(
            "CUSTOM_CRED_HELPER_API_KEY=sk-helper-test-999999\n", encoding="utf-8"
        )
        assert prov._provider_has_key("custom:cred-helper") is True
        assert prov._get_provider_api_key("custom:cred-helper") == "sk-helper-test-999999"

    def test_created_entry_visible_in_get_providers(self, custom_home, monkeypatch):
        _quiet_providers_catalog(monkeypatch)
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        save_custom_provider(
            {
                "name": "Flow Entry",
                "base_url": "https://flow.example/v1",
                "api_key": FAKE_KEY,
                "model": "flow-model",
            }
        )
        from api import providers as prov

        try:
            result = prov.get_providers()
            cp = next(p for p in result["providers"] if p.get("is_custom"))
            assert cp["id"] == "custom:flow-entry"
            assert cp["name"] == "Flow Entry"
            assert cp["model"] == "flow-model"
            assert cp["has_key"] is True
            assert cp["key_env"] == "CUSTOM_FLOW_ENTRY_API_KEY"
        finally:
            prov.invalidate_providers_cache()


# ── Unrelated config preservation ─────────────────────────────────────────


class TestConfigPreservation:
    # ``base_entry`` is YAML-anchored to the custom_providers entry: an edit to
    # the entry must not leak into the aliased sibling (ARCHITECTURE §4.10).
    RAW_CONFIG = (
        "model:\n"
        "  provider: custom:keeper\n"
        "ui:\n"
        "  theme: dark\n"
        "providers:\n"
        "  openrouter:\n"
        "    api_key: ${RT_SECRET}\n"
        "base_entry: &anchor\n"
        "  name: Keeper\n"
        "  base_url: https://keeper.example/v1\n"
        "  api_key: ${KEEPER_SECRET}\n"
        "  models:\n"
        "    - keep-model\n"
        "custom_providers:\n"
        "  - *anchor\n"
    )

    # LIST-level anchor: the whole custom_providers list is aliased, so an
    # in-place append/assign/del on the list would propagate to the sibling
    # on re-dump (reviewer F1 — the container itself must be detached).
    RAW_LIST_ALIAS_CONFIG = (
        "model: {}\n"
        "tpl: &cp\n"
        "  - name: Orig One\n"
        "    base_url: https://orig.example/v1\n"
        "custom_providers: *cp\n"
    )

    def test_list_alias_container_detached_on_mutations(self, custom_home):
        """Create/rename/delete must not leak into a LIST-level alias sibling."""
        from api.providers import delete_custom_provider, save_custom_provider

        (custom_home / "config.yaml").write_text(
            self.RAW_LIST_ALIAS_CONFIG, encoding="utf-8"
        )
        original = [{"name": "Orig One", "base_url": "https://orig.example/v1"}]

        # Create: append must land only in custom_providers.
        result = save_custom_provider(
            {
                "name": "Added",
                "base_url": "https://added.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert result["ok"] is True
        cfg = _read_config(custom_home)
        assert cfg["tpl"] == original
        assert [e["name"] for e in cfg["custom_providers"]] == ["Orig One", "Added"]

        # Rename: index assignment must land only in custom_providers.
        result = save_custom_provider(
            {
                "name": "Renamed",
                "original_name": "Added",
                "base_url": "https://added.example/v1",
                "model": "m1",
            }
        )
        assert result["ok"] is True
        cfg = _read_config(custom_home)
        assert cfg["tpl"] == original
        assert [e["name"] for e in cfg["custom_providers"]] == ["Orig One", "Renamed"]

        # Delete: del must land only in custom_providers.
        result = delete_custom_provider({"name": "Renamed"})
        assert result["ok"] is True
        cfg = _read_config(custom_home)
        assert cfg["tpl"] == original
        assert cfg["custom_providers"] == original

    def test_unrelated_keys_env_refs_and_aliases_survive(self, custom_home):
        from api.providers import delete_custom_provider, save_custom_provider

        (custom_home / "config.yaml").write_text(self.RAW_CONFIG, encoding="utf-8")
        save_custom_provider(
            {
                "name": "Added",
                "base_url": "https://added.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        save_custom_provider(
            {
                "name": "Renamed",
                "original_name": "Added",
                "base_url": "https://added.example/v1",
                "model": "m1",
            }
        )
        # Update the ALIASED entry itself: the rename must not leak into the
        # ``base_entry`` anchor source (detach-before-mutate, §4.10).
        save_custom_provider(
            {
                "name": "Keeper Prime",
                "original_name": "Keeper",
                "base_url": "https://keeper2.example/v1",
            }
        )
        cfg = _read_config(custom_home)
        assert cfg["base_entry"] == {
            "name": "Keeper",
            "base_url": "https://keeper.example/v1",
            "api_key": "${KEEPER_SECRET}",
            "models": ["keep-model"],
        }
        by_name = {e["name"]: e for e in cfg["custom_providers"]}
        assert by_name["Keeper Prime"] == {
            "name": "Keeper Prime",
            "base_url": "https://keeper2.example/v1",
            "api_key": "${KEEPER_SECRET}",
            "models": ["keep-model"],
        }

        delete_custom_provider({"name": "Renamed"})
        delete_custom_provider({"name": "Keeper Prime"})
        cfg = _read_config(custom_home)
        assert cfg["custom_providers"] == []
        assert cfg["base_entry"]["name"] == "Keeper"
        assert cfg["model"] == {"provider": "custom:keeper"}
        assert cfg["ui"] == {"theme": "dark"}
        assert cfg["providers"]["openrouter"]["api_key"] == "${RT_SECRET}"


# ── HTTP-level tests through the real route ───────────────────────────────


class TestHttpCustomProviderRoutes:
    NAME = "Http Crud Gateway"
    SLUG = "custom:http-crud-gateway"
    ENV_VAR = "CUSTOM_HTTP_CRUD_GATEWAY_API_KEY"

    def test_http_create_get_delete_flow(self):
        from tests.conftest import TEST_STATE_DIR

        origin = BASE
        try:
            body, status = _http_post(
                CUSTOM_CREATE_PATH,
                {
                    "name": self.NAME,
                    "base_url": "https://http-gw.example/v1",
                    "api_key": FAKE_KEY,
                    "model": "http-model",
                },
                origin=origin,
            )
            assert status == 200
            assert body["ok"] is True
            assert body["action"] == "created"
            assert body["provider"] == {"id": self.SLUG, "name": self.NAME}

            env_text = (TEST_STATE_DIR / ".env").read_text(encoding="utf-8")
            assert f"{self.ENV_VAR}=" in env_text

            providers = _http_get("/api/providers")
            cp = next(
                p for p in providers["providers"] if p.get("id") == self.SLUG
            )
            assert cp["is_custom"] is True
            assert cp["configurable"] is False
            assert cp["has_key"] is True
            assert cp["key_env"] == self.ENV_VAR
            assert cp["name"] == self.NAME
            assert cp["model"] == "http-model"

            body, status = _http_post(
                CUSTOM_DELETE_PATH, {"name": self.NAME}, origin=origin
            )
            assert status == 200
            assert body == {
                "ok": True,
                "provider": {"id": self.SLUG},
                "action": "deleted",
            }

            providers = _http_get("/api/providers")
            assert not any(
                p.get("id") == self.SLUG for p in providers["providers"]
            )
            env_text = (TEST_STATE_DIR / ".env").read_text(encoding="utf-8")
            assert f"{self.ENV_VAR}=" not in env_text
        finally:
            _http_post(CUSTOM_DELETE_PATH, {"name": self.NAME}, origin=origin)

    def test_http_create_invalid_name_400(self):
        body, status = _http_post(
            CUSTOM_CREATE_PATH,
            {"name": "", "base_url": "https://x.example"},
            origin=BASE,
        )
        assert status == 400
        assert body["error"] == "invalid_name"
        assert body["detail"]

    def test_http_models_endpoint_requires_name_or_base_url(self):
        body, status = _http_post(CUSTOM_MODELS_PATH, {}, origin=BASE)
        assert status == 400
        assert body["error"] == "invalid_request"


# ── Rename without a new key: owned-env migration (orphan defect) ─────────


class TestRenameOwnedKeyMigration:
    """Rename with api_key omitted must migrate the WebUI-owned env var.

    Defect: the update branch left ``key_env`` pointing at the OLD slug's
    env var, so ``delete_custom_provider``'s ownership check (key_env ==
    CURRENT-slug owned name) never removed it — an orphaned credential in
    .env. Migration restores the invariant: WebUI-managed entries always
    carry ``key_env == CUSTOM_<CURRENT_SLUG>_API_KEY``.
    """

    OLD_NAME = "QA Mock Gateway"
    NEW_NAME = "QA Renamed GW"
    OLD_ENV = "CUSTOM_QA_MOCK_GATEWAY_API_KEY"
    NEW_ENV = "CUSTOM_QA_RENAMED_GW_API_KEY"
    STORED_KEY = "sk-qa-mock-test-12345678"

    def _created(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        result = save_custom_provider(
            {
                "name": self.OLD_NAME,
                "base_url": "https://qa-gw.example/v1",
                "api_key": self.STORED_KEY,
            }
        )
        assert result["ok"] is True

    def test_rename_without_new_key_migrates_owned_env(self, custom_home):
        from api.providers import save_custom_provider

        self._created(custom_home)
        result = save_custom_provider(
            {
                "name": self.NEW_NAME,
                "original_name": self.OLD_NAME,
                "base_url": "https://qa-gw.example/v1",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["key_env"] == self.NEW_ENV
        assert _env_var_names(custom_home) == {self.NEW_ENV}
        env_text = (custom_home / ".env").read_text(encoding="utf-8")
        # Same stored value, now under the new owned name.
        assert f"{self.NEW_ENV}={self.STORED_KEY}" in env_text
        assert self.OLD_ENV not in env_text

    def test_rename_then_delete_leaves_no_orphan_env(self, custom_home):
        from api.providers import delete_custom_provider, save_custom_provider

        self._created(custom_home)
        save_custom_provider(
            {
                "name": self.NEW_NAME,
                "original_name": self.OLD_NAME,
                "base_url": "https://qa-gw.example/v1",
            }
        )
        result = delete_custom_provider({"name": self.NEW_NAME})
        assert result["ok"] is True
        assert _read_config(custom_home).get("custom_providers", []) == []
        assert _env_var_names(custom_home) == set()

    def test_rename_and_delete_keep_cli_authored_key_env(self, custom_home):
        from api.providers import delete_custom_provider, save_custom_provider

        _seed_config(
            custom_home,
            {
                "custom_providers": [
                    {
                        "name": "Cli GW",
                        "base_url": "https://cli.example/v1",
                        "key_env": "MY_GATEWAY_KEY",
                    }
                ]
            },
        )
        (custom_home / ".env").write_text(
            "MY_GATEWAY_KEY=sk-cli-test-12345678\n", encoding="utf-8"
        )
        result = save_custom_provider(
            {
                "name": "Cli GW Prime",
                "original_name": "Cli GW",
                "base_url": "https://cli.example/v1",
            }
        )
        assert result["ok"] is True
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["key_env"] == "MY_GATEWAY_KEY"
        assert _env_var_names(custom_home) == {"MY_GATEWAY_KEY"}

        result = delete_custom_provider({"name": "Cli GW Prime"})
        assert result["ok"] is True
        assert _read_config(custom_home).get("custom_providers", []) == []
        assert _env_var_names(custom_home) == {"MY_GATEWAY_KEY"}


# ── Env-var-name convergence across distinct slugs ────────────────────────


class TestEnvVarNameCollision:
    """Distinct slug_keys may derive ONE CUSTOM_*_API_KEY var.

    ``_api_key_env_name`` collapses ``-``/``.``/``_`` to ``_``, so "my-gateway"
    and "my.gateway" are separately creatable yet would share
    CUSTOM_MY_GATEWAY_API_KEY — one entry's key writes/deletes would clobber
    the other's. create/rename must reject the convergence (duplicate_name).
    """

    def test_create_rejects_env_name_convergence(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        first = save_custom_provider(
            {
                "name": "my-gateway",
                "base_url": "https://a.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert first["ok"] is True

        second = save_custom_provider(
            {
                "name": "my.gateway",
                "base_url": "https://b.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert second["ok"] is False
        assert second["error"] == "duplicate_name"
        assert "CUSTOM_MY_GATEWAY_API_KEY" in second["detail"]
        names = [e["name"] for e in _read_config(custom_home)["custom_providers"]]
        assert names == ["my-gateway"]

    def test_rename_rejects_env_name_convergence(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        for name, url in (
            ("alpha one", "https://a.example/v1"),
            ("beta.two", "https://b.example/v1"),
        ):
            result = save_custom_provider(
                {"name": name, "base_url": url, "api_key": FAKE_KEY}
            )
            assert result["ok"] is True

        # "beta-two" has a distinct slug_key from "beta.two" but both derive
        # CUSTOM_BETA_TWO_API_KEY.
        renamed = save_custom_provider(
            {
                "name": "beta-two",
                "original_name": "alpha one",
                "base_url": "https://a.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert renamed["ok"] is False
        assert renamed["error"] == "duplicate_name"
        assert "CUSTOM_BETA_TWO_API_KEY" in renamed["detail"]
        names = sorted(e["name"] for e in _read_config(custom_home)["custom_providers"])
        assert names == ["alpha one", "beta.two"]


# ── .env write failure: config.yaml rollback ──────────────────────────────


class TestEnvWriteFailureRollback:
    """A failed post-lock .env write must roll config.yaml back.

    Without the rollback, a rename-with-key commit leaves ``key_env`` on the
    NEW owned var while the OLD var still holds the credential — delete
    (ownership check computed from the new name) would never remove it.
    """

    OLD_NAME = "Roll Back Me"
    NEW_NAME = "Roll Back Two"
    OLD_ENV = "CUSTOM_ROLL_BACK_ME_API_KEY"

    def _created(self, custom_home):
        from api.providers import save_custom_provider

        _seed_config(custom_home, {"model": {}})
        result = save_custom_provider(
            {
                "name": self.OLD_NAME,
                "base_url": "https://rb.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert result["ok"] is True

    @staticmethod
    def _boom(_path, _updates):
        raise OSError("simulated .env write failure")

    def test_rename_env_write_failure_restores_config(self, custom_home, monkeypatch):
        from api import providers as prov

        self._created(custom_home)
        before = (custom_home / "config.yaml").read_bytes()

        monkeypatch.setattr(prov, "_write_env_file", self._boom)
        result = prov.save_custom_provider(
            {
                "name": self.NEW_NAME,
                "original_name": self.OLD_NAME,
                "base_url": "https://rb.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert result["ok"] is False
        assert result["error"] == "write_failed"
        assert (custom_home / "config.yaml").read_bytes() == before
        entry = _read_config(custom_home)["custom_providers"][0]
        assert entry["name"] == self.OLD_NAME
        assert entry["key_env"] == self.OLD_ENV

    def test_delete_env_write_failure_restores_entry(self, custom_home, monkeypatch):
        from api import providers as prov

        self._created(custom_home)
        before = (custom_home / "config.yaml").read_bytes()

        monkeypatch.setattr(prov, "_write_env_file", self._boom)
        result = prov.delete_custom_provider({"name": self.OLD_NAME})
        assert result["ok"] is False
        assert result["error"] == "write_failed"
        assert (custom_home / "config.yaml").read_bytes() == before
        names = [e["name"] for e in _read_config(custom_home)["custom_providers"]]
        assert names == [self.OLD_NAME]

    def test_create_env_write_failure_removes_created_config(self, custom_home, monkeypatch):
        """Rollback when config.yaml did not exist before the transaction."""
        from api import providers as prov

        # No _seed_config: config.yaml does not exist yet.
        monkeypatch.setattr(prov, "_write_env_file", self._boom)
        result = prov.save_custom_provider(
            {
                "name": "Fresh Entry",
                "base_url": "https://fresh.example/v1",
                "api_key": FAKE_KEY,
            }
        )
        assert result["ok"] is False
        assert result["error"] == "write_failed"
        assert not (custom_home / "config.yaml").exists()
