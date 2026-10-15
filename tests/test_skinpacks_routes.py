"""Skin pack HTTP route tests (skin-pack feature, W3).

``api/routes.py`` owns two GET routes on top of the frozen W1 foundation
(``api/skinpacks.py``):

- ``GET /api/skins`` — JSON pack listing discovered over the builtin + user
  roots, each entry carrying ``assetsBase`` for asset URL construction
- ``GET /api/skins/<key>/assets/<rel>`` — sandboxed asset serving delegated
  to ``skinpacks.serve_pack_asset``

These tests pin the ROUTE-level contract: dispatcher wiring (same auth/CSRF
position as every other ``/api/`` GET), listing shape without local-path
leakage, ``<key>/assets/<rel>`` path parsing, key validation, and shadowing
re-resolution. The discovery/manifest/sandbox mechanics are pinned in
``test_skinpacks_discovery.py`` (W1) and are exercised here only through
the route.

The last test drives the autouse session server over HTTP and asserts only
the response SHAPE — the shipped builtin example pack lands with W4, so no
specific pack may be asserted present.
"""

import json
import shutil
import urllib.request
from types import SimpleNamespace

from tests._pytest_port import BASE


class FakeHandler:
    """Minimal handler double; ``headers`` carries request headers so
    If-None-Match can be exercised at the route level."""

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
    manifest = {
        "schemaVersion": 1,
        "key": "aurora",
        "name": "Aurora",
        "version": "1.0.0",
        "author": "Someone",
        "description": "An aurora pack",
        "scheme": "auto",
        "preview": {"colors": ["#ff5500"]},
        "palette": {"light": {"accent": "#0055ff"}, "dark": {"accent": "#3388ff"}},
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
        target.write_text(content, encoding="utf-8")
    return pack_dir


def _use_pack_roots(monkeypatch, tmp_path, builtin_packs=(), user_packs=()):
    """Point the default discovery roots at fixtures under tmp_path so the
    route's ``discover_skin_packs()`` call resolves real fixture packs."""
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(exist_ok=True)
    user.mkdir(exist_ok=True)
    for key, manifest, files in builtin_packs:
        _write_pack(builtin, key, manifest, files)
    for key, manifest, files in user_packs:
        _write_pack(user, key, manifest, files)
    import api.skinpacks as skinpacks

    monkeypatch.setattr(skinpacks, "_default_builtin_root", lambda: builtin)
    monkeypatch.setattr(skinpacks, "_default_user_root", lambda: user)
    return builtin, user


def _get(path, query="", headers=None):
    """Drive routes.handle_get with a parsed-path namespace. Asserts the
    dispatcher contract server.py relies on: a branch matched and handled
    the request (``False`` would mean fallthrough-to-404). JSON branches
    ``return j(...)`` which is None — same as every neighboring API route."""
    from api import routes

    handler = FakeHandler(headers=headers)
    handled = routes.handle_get(handler, SimpleNamespace(path=path, query=query))
    assert handled is not False, path
    return handler


def _json_body(handler):
    return json.loads(bytes(handler.body).decode("utf-8"))


# ── GET /api/skins listing ─────────────────────────────────────────────────


def test_skins_listing_returns_discovered_pack_fields(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"pack.js": "//ok", "extra.css": "x"})],
    )
    handler = _get("/api/skins")
    assert handler.status == 200
    assert handler.header("Content-Type") == "application/json; charset=utf-8"
    assert handler.header("Cache-Control") == "no-store"

    packs = _json_body(handler)["packs"]
    pack = next(p for p in packs if p["key"] == "aurora")
    assert pack["name"] == "Aurora"
    assert pack["version"] == "1.0.0"
    assert pack["author"] == "Someone"
    assert pack["description"] == "An aurora pack"
    assert pack["origin"] == "builtin"
    assert pack["shadows"] is False
    assert pack["scheme"] == "auto"
    assert pack["preview"] == {"colors": ["#ff5500"]}
    assert pack["palette"]["dark"] == {"accent": "#3388ff"}
    assert pack["extraCss"] == "extra.css"
    assert pack["scripts"] == ["pack.js"]
    assert pack["tweaks"][0]["id"] == "radius"
    assert pack["assetsBase"] == "/api/skins/aurora/assets/"


def test_skins_listing_includes_icons_and_thinking(tmp_path, monkeypatch):
    manifest = _manifest(
        icons={
            "favicon": "icons/favicon.svg",
            "favicon32": "icons/favicon-32.png",
            "favicon192": "icons/favicon-192.png",
            "favicon512": "icons/favicon-512.png",
            "appleTouch": "icons/apple-touch-icon.png",
            "faviconIco": "icons/favicon.ico",
            "logoSvg": "icons/logo.svg",
        },
        thinking={"mode": "gif", "gif": "anim/thinking.gif", "size": 28},
    )
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", manifest, None)])
    handler = _get("/api/skins")
    pack = next(p for p in _json_body(handler)["packs"] if p["key"] == "aurora")
    assert pack["icons"]["favicon"] == "icons/favicon.svg"
    assert pack["icons"]["logoSvg"] == "icons/logo.svg"
    assert pack["thinking"] == {"mode": "gif", "gif": "anim/thinking.gif", "size": 28}


def test_skins_listing_icons_and_thinking_defaults(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), None)])
    handler = _get("/api/skins")
    pack = next(p for p in _json_body(handler)["packs"] if p["key"] == "aurora")
    assert pack["icons"] == {}
    # An absent thinking field normalizes to {"mode": "none"} — the frontend
    # treats that as "no replacement".
    assert pack["thinking"] == {"mode": "none"}


def test_skins_listing_omits_pack_dir_and_local_paths(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), None)])
    handler = _get("/api/skins")
    raw = bytes(handler.body).decode("utf-8")
    assert "dir" not in _json_body(handler)["packs"][0]
    assert str(tmp_path) not in raw


def test_skins_listing_empty_when_no_packs(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path)
    handler = _get("/api/skins")
    assert handler.status == 200
    assert _json_body(handler) == {"packs": []}


def test_skins_listing_marks_user_pack_shadowing_builtin(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), None)],
        user_packs=[("aurora", _manifest(name="User Aurora"), None)],
    )
    handler = _get("/api/skins")
    aurora_entries = [p for p in _json_body(handler)["packs"] if p["key"] == "aurora"]
    assert len(aurora_entries) == 1
    assert aurora_entries[0]["origin"] == "user"
    assert aurora_entries[0]["shadows"] is True
    assert aurora_entries[0]["name"] == "User Aurora"


# ── GET /api/skins/<key>/assets/<rel> ───────────────────────────────────────


def test_skins_asset_serves_file_with_no_cache_and_weak_etag(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"theme.css": "body { color: red; }"})],
    )
    handler = _get("/api/skins/aurora/assets/theme.css")
    assert handler.status == 200
    assert handler.header("Content-Type") == "text/css; charset=utf-8"
    assert handler.header("Cache-Control") == "no-cache"
    assert handler.header("Content-Length") == str(len(b"body { color: red; }"))
    assert handler.header("ETag").startswith('W/"')
    assert bytes(handler.body) == b"body { color: red; }"


def test_skins_asset_304_on_if_none_match(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"theme.css": "body {}"})],
    )
    first = _get("/api/skins/aurora/assets/theme.css")
    assert first.status == 200
    etag = first.header("ETag")
    assert etag is not None

    fresh = _get("/api/skins/aurora/assets/theme.css", headers={"If-None-Match": etag})
    assert fresh.status == 304
    assert fresh.header("ETag") == etag
    assert bytes(fresh.body) == b""


def test_skins_asset_ignores_query_string(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"theme.css": "body {}"})],
    )
    handler = _get("/api/skins/aurora/assets/theme.css", query="v=123")
    assert handler.status == 200
    assert bytes(handler.body) == b"body {}"
    # the version query must not upgrade the asset to an immutable long cache
    assert handler.header("Cache-Control") == "no-cache"


def test_skins_asset_rejects_traversal(tmp_path, monkeypatch):
    _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"theme.css": "body {}"})],
    )
    for path in (
        "/api/skins/aurora/assets/../../etc/passwd",
        "/api/skins/aurora/assets/%2e%2e/secret.css",
    ):
        handler = _get(path)
        assert handler.status == 404, path
        text = bytes(handler.body).decode("utf-8", "replace")
        assert "not found" in text
        assert str(tmp_path) not in text


def test_skins_asset_rejects_non_assets_shapes(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), None)])
    for path in (
        "/api/skins/aurora/other/file",   # missing /assets/ segment
        "/api/skins/aurora",              # no assets at all
        "/api/skins/",                    # empty remainder
        "/api/skins//assets/theme.css",   # empty key
        "/api/skins/aurora/assets/",      # empty rel → sandboxed 404
    ):
        handler = _get(path)
        assert handler.status == 404, path


def test_skins_asset_rejects_invalid_keys(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), None)])
    for path in (
        "/api/skins/%2e%2e/assets/theme.css",                    # encoded ".."
        "/api/skins/../assets/theme.css",                        # literal ".."
        "/api/skins/Aurora/assets/theme.css",                    # uppercase
        "/api/skins/aur.ora/assets/theme.css",                   # dot in key
        "/api/skins/aur%6Fra/assets/missing.css",                # decoded 'o', unknown key
        "/api/skins/" + "a" * 33 + "/assets/theme.css",          # over-length key
    ):
        handler = _get(path)
        assert handler.status == 404, path


def test_skins_asset_404_for_missing_file_and_unknown_pack(tmp_path, monkeypatch):
    _use_pack_roots(monkeypatch, tmp_path, builtin_packs=[("aurora", _manifest(), None)])
    for path in (
        "/api/skins/aurora/assets/missing.css",
        "/api/skins/ghost/assets/theme.css",
    ):
        handler = _get(path)
        assert handler.status == 404, path
        body_text = bytes(handler.body).decode("utf-8", "replace")
        assert "not found" in body_text
        assert str(tmp_path) not in body_text


def test_skins_asset_shadowing_user_wins_then_builtin_re_resolve(tmp_path, monkeypatch):
    _, user = _use_pack_roots(
        monkeypatch,
        tmp_path,
        builtin_packs=[("aurora", _manifest(), {"theme.css": "builtin-bytes"})],
        user_packs=[("aurora", _manifest(name="User Aurora"), {"theme.css": "user-bytes"})],
    )
    shadowed = _get("/api/skins/aurora/assets/theme.css")
    assert shadowed.status == 200
    assert bytes(shadowed.body) == b"user-bytes"

    shutil.rmtree(user / "aurora")
    reverted = _get("/api/skins/aurora/assets/theme.css")
    assert reverted.status == 200
    assert bytes(reverted.body) == b"builtin-bytes"


# ── end-to-end over the autouse session server ──────────────────────────────


def test_skins_endpoint_shape_over_http():
    """GET /api/skins over real HTTP returns 200 JSON with a packs list whose
    entries each carry assetsBase. The shipped builtin example pack may not
    exist yet (W4 lands separately) — assert shape only."""
    with urllib.request.urlopen(BASE + "/api/skins", timeout=10) as response:
        assert response.status == 200
        assert response.headers.get("Content-Type") == "application/json; charset=utf-8"
        data = json.loads(response.read())
    assert isinstance(data, dict)
    assert isinstance(data["packs"], list)
    for entry in data["packs"]:
        assert entry["assetsBase"] == "/api/skins/{}/assets/".format(entry["key"])
