"""Skin pack batch-2 backend tests: icon replacement surfaces.

Batch 1 (W1-W4) shipped discovery/normalization, the ``skin_pack`` setting,
and the ``/api/skins`` routes, with ``icons``/``thinking`` shallow-validated
as opaque objects. Batch 2 tightens that validation and wires the active
pack's icons into three PRE-AUTH surfaces in ``api/routes.py``:

- ``_serve_manifest`` — stock manifest icon srcs (and the shortcut icon that
  shares the favicon-192 src) rewritten to ``/api/skins/<key>/assets/<rel>``
  by matching the ORIGINAL src value; parse errors fail open to stock bytes
- the index shell render — the stock icon ``<link>`` hrefs rewritten per
  request (never inside the cached shell base, so a settings-time pack
  switch needs no redeploy)
- ``/favicon.ico`` — the pack's ``faviconIco`` bytes with the route's own
  headers (``image/x-icon``, ``max-age=86400``), stock fallback otherwise

Active-pack resolution is fail-safe everywhere: these surfaces serve
pre-auth traffic, so settings/discovery errors degrade to stock, never 500.
"""

import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.config as config
from api import skinpacks
from api.skinpacks import _load_and_validate_manifest
from tests._pytest_port import BASE

REPO_ROOT = Path(__file__).parent.parent
STOCK_FAVICON_ICO = (REPO_ROOT / "static" / "favicon.ico").read_bytes()
STOCK_TMP_ICO = b"stock-ico-bytes"

FULL_ICONS = {
    "favicon": "icons/favicon.svg",
    "favicon32": "icons/favicon-32.png",
    "favicon192": "icons/favicon-192.png",
    "favicon512": "icons/favicon-512.png",
    "appleTouch": "icons/apple-touch-icon.png",
    "faviconIco": "icons/favicon.ico",
    "logoSvg": "icons/favicon.svg",
}

STOCK_MANIFEST = {
    "id": "./",
    "name": "Hermes",
    "short_name": "Hermes",
    "start_url": "./?source=pwa",
    "shortcuts": [
        {
            "name": "New conversation",
            "url": "./?source=pwa&action=new-chat",
            "icons": [{"src": "static/favicon-192.png", "sizes": "192x192"}],
        }
    ],
    "icons": [
        {"src": "static/favicon.svg", "sizes": "any", "type": "image/svg+xml"},
        {"src": "static/favicon-32.png", "sizes": "32x32", "type": "image/png"},
        {"src": "static/favicon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "static/favicon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "static/untouched.png", "sizes": "64x64", "type": "image/png"},
    ],
}


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

    def header(self, name):
        for key, value in self.sent_headers:
            if key.lower() == name.lower():
                return value
        return None


def _manifest(**overrides):
    manifest = {
        "schemaVersion": 1,
        "key": "aurora",
        "name": "Aurora",
        "version": "1.0.0",
        "author": "Someone",
        "description": "An aurora pack",
        "scheme": "auto",
        "icons": dict(FULL_ICONS),
        "thinking": {"mode": "gif", "gif": "anim/thinking.gif", "size": 28},
    }
    manifest.update(overrides)
    return manifest


def _write_pack(root, key, manifest, files=None):
    pack_dir = root / key
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, content in (files or {}).items():
        target = pack_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    return pack_dir


def _use_pack_roots(monkeypatch, tmp_path, builtin_packs=(), user_packs=()):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(exist_ok=True)
    user.mkdir(exist_ok=True)
    for key, manifest, files in builtin_packs:
        _write_pack(builtin, key, manifest, files)
    for key, manifest, files in user_packs:
        _write_pack(user, key, manifest, files)
    monkeypatch.setattr(skinpacks, "_default_builtin_root", lambda: builtin)
    monkeypatch.setattr(skinpacks, "_default_user_root", lambda: user)
    return builtin, user


ICON_FILES = {
    "icons/favicon.svg": b"<svg>pack</svg>",
    "icons/favicon-32.png": b"png32-pack",
    "icons/favicon-192.png": b"png192-pack",
    "icons/favicon-512.png": b"png512-pack",
    "icons/apple-touch-icon.png": b"apple-pack",
    "icons/favicon.ico": b"ico-pack-bytes",
    "anim/thinking.gif": b"GIF89a-pack",
}


@pytest.fixture()
def pack_env(tmp_path, monkeypatch):
    """aurora active: tmp pack roots with the full icon set on disk, and an
    isolated SETTINGS_FILE selecting it (the real load_settings path —
    skin_pack is normalized against the monkeypatched discovery)."""
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), ICON_FILES)],
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"skin_pack": "aurora"}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)
    return tmp_path


def _use_static_root(monkeypatch, tmp_path, manifest_payload):
    """Tmp static root carrying the given manifest payload plus a stock
    favicon.ico with distinct bytes, so pack-served vs stock-served bytes are
    distinguishable and the fallback provably reads the static root."""
    static_root = tmp_path / "static-root"
    static_root.mkdir(exist_ok=True)
    manifest_path = static_root / "manifest.json"
    if isinstance(manifest_payload, bytes):
        manifest_path.write_bytes(manifest_payload)
    else:
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    (static_root / "favicon.ico").write_bytes(STOCK_TMP_ICO)
    monkeypatch.setattr(config, "get_static_root", lambda: static_root)
    return static_root


def _get(path, query=""):
    from api import routes

    handler = FakeHandler()
    handled = routes.handle_get(handler, SimpleNamespace(path=path, query=query))
    assert handled is not False, path
    return handler


# ── manifest validation: icons ──────────────────────────────────────────────


def test_icons_unsafe_paths_drop_entry_not_pack(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        "aurora",
        _manifest(
            icons={
                "favicon": "../evil.svg",
                "favicon32": "/abs/evil.png",
                "appleTouch": ".hidden.png",
                "favicon192": "icons/sub\\back.png",
                "favicon512": "icons/fine.png",
            }
        ),
    )
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    assert normalized["icons"] == {"favicon512": "icons/fine.png"}


def test_icons_unknown_keys_and_wrong_types_dropped(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        "aurora",
        _manifest(
            icons={
                "favicon": "icons/favicon.svg",
                "logo": "icons/logo.svg",
                "weight": 2,
                "favicon32": ["not", "a", "string"],
            }
        ),
    )
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    assert normalized["icons"] == {"favicon": "icons/favicon.svg"}


# ── manifest validation: thinking ───────────────────────────────────────────


def test_thinking_gif_mode_requires_safe_gif_path(tmp_path):
    for thinking in ({"mode": "gif"}, {"mode": "gif", "gif": "../escape.gif"}):
        _write_pack(tmp_path, "aurora", _manifest(thinking=thinking))
        normalized, error = _load_and_validate_manifest(tmp_path / "aurora")
        assert error is None
        assert normalized["thinking"] == {"mode": "none"}


def test_thinking_css_mode_kept_and_size_clamped(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        "aurora",
        _manifest(thinking={"mode": "css", "css": "anim/thinking.css"}),
    )
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    assert normalized["thinking"] == {"mode": "css", "css": "anim/thinking.css"}

    for raw_size, expected in ((4, 8), (200, 128), (64, 64)):
        pack_dir = _write_pack(
            tmp_path,
            "aurora",
            _manifest(
                thinking={"mode": "gif", "gif": "anim/thinking.gif", "size": raw_size}
            ),
        )
        normalized, error = _load_and_validate_manifest(pack_dir)
        assert error is None
        assert normalized["thinking"]["size"] == expected

    for bad_size in ("big", 28.5, True):
        pack_dir = _write_pack(
            tmp_path,
            "aurora",
            _manifest(
                thinking={"mode": "gif", "gif": "anim/thinking.gif", "size": bad_size}
            ),
        )
        normalized, error = _load_and_validate_manifest(pack_dir)
        assert error is None
        assert "size" not in normalized["thinking"]


def test_thinking_unknown_mode_and_unknown_keys_dropped(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        "aurora",
        _manifest(
            thinking={"mode": "sparkle", "gif": "anim/thinking.gif", "accent": "#fff"}
        ),
    )
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    assert normalized["thinking"] == {"mode": "none"}


# ── active_skin_pack ────────────────────────────────────────────────────────


def test_active_skin_pack_resolves_selected_and_rejects_stale(tmp_path):
    _write_pack(tmp_path, "aurora", _manifest())
    packs = skinpacks.discover_skin_packs(
        builtin_root=tmp_path, user_root=tmp_path / "no-user"
    )
    pack = skinpacks.active_skin_pack({"skin_pack": "aurora"}, packs)
    assert pack is packs["aurora"]
    assert skinpacks.active_skin_pack({"skin_pack": "ghost"}, packs) is None
    assert skinpacks.active_skin_pack({"skin_pack": ""}, packs) is None
    assert skinpacks.active_skin_pack({}, packs) is None
    assert skinpacks.active_skin_pack(None, packs) is None
    assert skinpacks.active_skin_pack(["nope"], packs) is None


# ── _serve_manifest icon replacement ────────────────────────────────────────


def test_manifest_icon_srcs_replaced_when_pack_active(pack_env, monkeypatch, tmp_path):
    _use_static_root(monkeypatch, tmp_path, STOCK_MANIFEST)
    handler = _get("/manifest.json")
    assert handler.status == 200
    assert handler.header("Content-Type") == "application/manifest+json; charset=utf-8"
    served = json.loads(bytes(handler.body).decode("utf-8"))
    assert served["name"] == "Hermes"
    assert served["start_url"] == "./?source=pwa"
    srcs = {icon["src"] for icon in served["icons"]}
    assert srcs == {
        "/api/skins/aurora/assets/icons/favicon.svg",
        "/api/skins/aurora/assets/icons/favicon-32.png",
        "/api/skins/aurora/assets/icons/favicon-192.png",
        "/api/skins/aurora/assets/icons/favicon-512.png",
        # unmapped src stays stock
        "static/untouched.png",
    }
    # sizes/type metadata ride along untouched
    by_src = {icon["src"]: icon for icon in served["icons"]}
    assert by_src["/api/skins/aurora/assets/icons/favicon.svg"]["type"] == "image/svg+xml"
    # the shortcut icon shares the favicon-192 src → replaced naturally
    shortcut_icon = served["shortcuts"][0]["icons"][0]
    assert shortcut_icon["src"] == "/api/skins/aurora/assets/icons/favicon-192.png"
    assert shortcut_icon["sizes"] == "192x192"


def test_manifest_serves_stock_bytes_on_parse_error_or_no_pack(
    pack_env, monkeypatch, tmp_path
):
    broken = b"{not json"
    _use_static_root(monkeypatch, tmp_path, broken)
    assert bytes(_get("/manifest.json").body) == broken

    # no pack selected → byte-faithful stock manifest
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    _use_static_root(monkeypatch, tmp_path, STOCK_MANIFEST)
    stock_bytes = (tmp_path / "static-root" / "manifest.json").read_bytes()
    assert bytes(_get("/manifest.json").body) == stock_bytes

    # pack selected but declares no icons → stock bytes too
    (tmp_path / "settings.json").write_text(
        json.dumps({"skin_pack": "bare"}), encoding="utf-8"
    )
    _write_pack(tmp_path / "builtin", "bare", _manifest(key="bare", icons={}))
    _use_static_root(monkeypatch, tmp_path, STOCK_MANIFEST)
    assert bytes(_get("/manifest.json").body) == stock_bytes


# ── index shell icon <link> rewrite ─────────────────────────────────────────


def _render_shell(monkeypatch):
    from api import routes

    captured = {}

    def fake_t(_handler, body, *, content_type=None, **_kwargs):
        captured["body"] = body
        captured["content_type"] = content_type
        return True

    import api.extensions as extensions

    monkeypatch.setattr(routes, "t", fake_t)
    monkeypatch.setattr(extensions, "inject_extension_tags", lambda html: html)
    handler = FakeHandler()
    assert routes.handle_get(handler, SimpleNamespace(path="/", query="")) is True
    return captured["body"]


def test_shell_icon_links_rewritten_when_pack_active(pack_env, monkeypatch):
    html = _render_shell(monkeypatch)
    assert 'href="/api/skins/aurora/assets/icons/favicon.svg"' in html
    assert 'href="/api/skins/aurora/assets/icons/favicon-32.png"' in html
    assert 'href="/api/skins/aurora/assets/icons/apple-touch-icon.png"' in html
    # unmapped icon hrefs stay stock
    assert 'href="static/favicon.ico"' in html
    assert 'href="static/favicon.svg"' not in html
    assert 'href="static/favicon-32.png"' not in html
    assert 'href="static/apple-touch-icon.png"' not in html


def test_shell_unchanged_without_active_pack(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), ICON_FILES)]
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)
    html = _render_shell(monkeypatch)
    assert 'href="static/favicon.svg"' in html
    assert "/api/skins/aurora/assets/" not in html


# ── /favicon.ico ────────────────────────────────────────────────────────────


def test_favicon_ico_serves_pack_bytes_with_route_headers(pack_env, monkeypatch, tmp_path):
    _use_static_root(monkeypatch, tmp_path, {})
    handler = _get("/favicon.ico")
    assert handler.status == 200
    assert bytes(handler.body) == b"ico-pack-bytes"
    assert handler.header("Content-Type") == "image/x-icon"
    assert handler.header("Cache-Control") == "public, max-age=86400"
    assert handler.header("Content-Length") == str(len(b"ico-pack-bytes"))


def test_favicon_ico_falls_back_to_stock_without_pack_or_file(
    pack_env, monkeypatch, tmp_path
):
    _use_static_root(monkeypatch, tmp_path, {})
    # no pack selected → static-root favicon.ico
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    assert bytes(_get("/favicon.ico").body) == STOCK_TMP_ICO

    # pack selected but its faviconIco file is missing on disk → stock too
    (tmp_path / "settings.json").write_text(
        json.dumps({"skin_pack": "aurora"}), encoding="utf-8"
    )
    (tmp_path / "builtin" / "aurora" / "icons" / "favicon.ico").unlink()
    handler = _get("/favicon.ico")
    assert handler.status == 200
    assert bytes(handler.body) == STOCK_TMP_ICO

    # pack without a faviconIco entry at all → stock
    (tmp_path / "settings.json").write_text(
        json.dumps({"skin_pack": "bare"}), encoding="utf-8"
    )
    _write_pack(tmp_path / "builtin", "bare", _manifest(key="bare", icons={}))
    assert bytes(_get("/favicon.ico").body) == STOCK_TMP_ICO


def test_favicon_ico_never_500s_when_settings_read_fails(pack_env, monkeypatch):
    def broken_load_settings():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(config, "load_settings", broken_load_settings)
    handler = _get("/favicon.ico")
    assert handler.status == 200
    assert bytes(handler.body) == STOCK_FAVICON_ICO


# ── end-to-end over the autouse session server ──────────────────────────────


def test_manifest_and_favicon_stay_stock_over_http():
    """The session server has no pack selected: both pre-auth surfaces serve
    the stock assets (and prove the new resolution never 500s them)."""
    with urllib.request.urlopen(BASE + "/manifest.json", timeout=10) as response:
        assert response.status == 200
        assert (
            response.headers.get("Content-Type")
            == "application/manifest+json; charset=utf-8"
        )
        manifest = json.loads(response.read())
    srcs = [icon["src"] for icon in manifest["icons"]]
    assert srcs and all(src.startswith("static/") for src in srcs)
    assert all("/api/skins/" not in src for src in srcs)

    with urllib.request.urlopen(BASE + "/favicon.ico", timeout=10) as response:
        assert response.status == 200
        assert response.headers.get("Content-Type") == "image/x-icon"
        assert response.read() == STOCK_FAVICON_ICO
