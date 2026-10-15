"""Skin pack batch-4 backend tests: image-tweak uploads.

Batch 4 extends the frozen batch 1-3 surface with ``"type": "image"`` tweaks:
the manifest validation (``apply`` exactly ``{"var": <token>}``, no template,
no class, no default), the stored-value normalizer (server-generated sha256
filenames only), the upload store (magic-byte sniff, 64B..2MB, per-pack
32-file cap with oldest-first eviction, atomic writes), and two routes
(``POST /api/skins/<key>/upload`` for the bytes, ``GET
/api/skins/<key>/uploads/<file>`` to serve them same-origin).

SVG is deliberately not uploadable/servable: an uploaded SVG navigated to
directly is a same-origin stored-XSS surface the admin-trust pack-asset route
does not have.
"""

import hashlib
import io
import json
import os
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

import api.config as config
from api import skinpacks
from api.skinpacks import _load_and_validate_manifest, normalize_skin_tweaks
from tests._pytest_port import BASE

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_BYTES = PNG_MAGIC + b"\x00" * 64
JPEG_MAGIC = b"\xff\xd8\xff"
GIF_BYTES = b"GIF89a" + b"\x00" * 64
WEBP_BYTES = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 64
SHA = lambda payload: hashlib.sha256(payload).hexdigest()  # noqa: E731


class FakeHandler:
    """Minimal handler double; ``headers`` carries request headers so
    If-None-Match can be exercised (mirrors test_skinpacks_routes.py)."""

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


class PostFakeHandler(FakeHandler):
    """FakeHandler plus an rfile/Content-Length so POST routes can read a
    raw body (mirrors the handler double in test_commands_endpoint.py)."""

    def __init__(self, body: bytes, headers=None):
        super().__init__(headers=headers)
        self.rfile = io.BytesIO(body)
        self.headers["Content-Length"] = str(len(body))

    def json_body(self):
        return json.loads(bytes(self.body).decode("utf-8"))


def _manifest(**overrides):
    manifest = {
        "schemaVersion": 1,
        "key": "aurora",
        "name": "Aurora",
        "version": "1.0.0",
        "author": "Someone",
        "description": "An aurora pack",
        "scheme": "auto",
        "tweaks": [
            {
                "id": "bg",
                "label": "Background image",
                "type": "image",
                "apply": {"var": "pack-bg"},
            }
        ],
    }
    manifest.update(overrides)
    return manifest


def _write_pack(root, key, manifest):
    pack_dir = root / key
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack_dir


@pytest.fixture()
def upload_root(tmp_path, monkeypatch):
    """Isolated STATE_DIR; returns the aurora pack's upload dir (not created
    until the first save)."""
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    return tmp_path / "skin_uploads" / "aurora"


def _get(path, headers=None):
    from api import routes

    handler = FakeHandler(headers=headers)
    handled = routes.handle_get(handler, SimpleNamespace(path=path, query=""))
    assert handled is not False, path
    return handler


def _post(path, body: bytes, content_type: str):
    from api import routes

    handler = PostFakeHandler(body, {"Content-Type": content_type})
    handled = routes.handle_post(handler, SimpleNamespace(path=path, query=""))
    assert handled is not False, path
    return handler


# ── manifest validation: image tweaks ───────────────────────────────────────


@pytest.mark.parametrize(
    "apply",
    [
        {"var": "pack-bg", "template": "url({value})"},
        {"class": "pack-bg"},
        {"var": "not a token!"},
        {},
        {"var": "pack-bg", "extra": 1},
    ],
)
def test_image_tweak_drop_shapes(tmp_path, apply):
    """apply must be exactly {"var": <token>}: template, class, invalid
    tokens, empty and extra keys all drop the tweak — never the pack."""
    pack_dir = _write_pack(tmp_path, "aurora", _manifest(tweaks=[
        {"id": "bg", "label": "Background image", "type": "image", "apply": apply}
    ]))
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    assert normalized["tweaks"] == []


def test_image_tweak_valid_var_kept_and_default_tolerated(tmp_path):
    pack_dir = _write_pack(tmp_path, "aurora", _manifest(tweaks=[
        {
            "id": "bg",
            "label": "Background image",
            "type": "image",
            "default": "ignored.png",
            "apply": {"var": "pack-bg"},
        }
    ]))
    normalized, error = _load_and_validate_manifest(pack_dir)
    assert error is None
    # exact shape: no default, no min/max/step/options — the manifest's
    # stray default is tolerated-and-ignored
    assert normalized["tweaks"] == [
        {
            "id": "bg",
            "label": "Background image",
            "type": "image",
            "apply": {"var": "pack-bg"},
        }
    ]


# ── stored-value normalization ──────────────────────────────────────────────


def _image_packs():
    return {
        "aurora": {
            "key": "aurora",
            "tweaks": [
                {"id": "bg", "label": "Background image", "type": "image",
                 "apply": {"var": "pack-bg"}},
            ],
        }
    }


@pytest.mark.parametrize(
    "value,kept",
    [
        ("a" * 64 + ".png", True),
        ("0123456789abcdef" * 4 + ".jpg", True),
        ("b" * 64 + ".jpeg", True),          # read side tolerates jpeg spelling
        ("c" * 64 + ".gif", True),
        ("d" * 64 + ".webp", True),
        ("a" * 64 + ".svg", False),          # never in the uploadable set
        ("A" * 64 + ".png", False),          # uppercase hex
        ("a" * 63 + ".png", False),          # short hash
        ("a" * 65 + ".png", False),          # long hash
        ("../../" + "a" * 64 + ".png", False),
        ("a" * 64 + ".png/../x", False),
        ("a" * 64 + ".PNG", False),          # uppercase ext
        ("", False),
        (None, False),
        (123, False),
    ],
)
def test_normalize_image_tweak_value(value, kept):
    result = normalize_skin_tweaks({"aurora": {"bg": value}}, _image_packs())
    assert result == ({"aurora": {"bg": value}} if kept else {})


# ── save_skin_pack_upload ───────────────────────────────────────────────────


def test_save_upload_png_happy_path(upload_root):
    filename, reason = skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    assert reason is None
    assert filename == SHA(PNG_BYTES) + ".png"
    assert (upload_root / filename).read_bytes() == PNG_BYTES
    # hash names dedupe repeats: same bytes → same file, count stays 1
    again, _ = skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    assert again == filename
    assert len(list(upload_root.iterdir())) == 1


@pytest.mark.parametrize(
    "content_type,payload",
    [
        ("image/jpeg", JPEG_MAGIC + b"\x00" * 64),
        ("image/gif", GIF_BYTES),
        ("image/webp", WEBP_BYTES),
    ],
)
def test_save_upload_other_types_happy_paths(upload_root, content_type, payload):
    filename, reason = skinpacks.save_skin_pack_upload("aurora", payload, content_type)
    assert reason is None
    assert filename == SHA(payload) + "." + content_type.rsplit("/", 1)[1].replace("jpeg", "jpg")
    assert (upload_root / filename).is_file()


@pytest.mark.parametrize(
    "content_type,payload",
    [
        ("image/jpeg", PNG_BYTES),           # png bytes declared jpeg
        ("image/png", JPEG_MAGIC + b"\x00" * 64),
        ("image/png", GIF_BYTES),
        ("image/webp", b"RIFF" + b"\x00" * 64),  # RIFF without WEBP at 8:12
        ("image/gif", b"GIF88a" + b"\x00" * 64),  # neither GIF87a nor GIF89a
    ],
)
def test_save_upload_rejects_magic_mismatch(upload_root, content_type, payload):
    filename, reason = skinpacks.save_skin_pack_upload("aurora", payload, content_type)
    assert filename is None
    assert reason is not None and "match" in reason


def test_save_upload_size_bounds(upload_root):
    tiny, tiny_reason = skinpacks.save_skin_pack_upload(
        "aurora", PNG_MAGIC + b"\x00" * 10, "image/png"
    )
    assert tiny is None and "small" in tiny_reason

    huge, huge_reason = skinpacks.save_skin_pack_upload(
        "aurora", PNG_MAGIC + b"\x00" * (2 * 1024 * 1024 + 1), "image/png"
    )
    assert huge is None and "too large" in huge_reason
    assert not upload_root.exists()


@pytest.mark.parametrize("content_type", ["image/svg+xml", "text/plain", "", None])
def test_save_upload_rejects_bad_content_type(upload_root, content_type):
    payload = b"<svg onload=alert(1)>" + b"\x00" * 64
    filename, reason = skinpacks.save_skin_pack_upload("aurora", payload, content_type)
    assert filename is None
    assert reason is not None and "content type" in reason


def test_save_upload_rejects_invalid_pack_key(upload_root):
    filename, reason = skinpacks.save_skin_pack_upload("../evil", PNG_BYTES, "image/png")
    assert filename is None
    assert "pack key" in reason


def test_upload_cap_evicts_oldest(upload_root):
    """33 distinct uploads → the oldest (by mtime) is evicted, ≤32 remain."""
    base_time = 1_700_000_000
    names = []
    for i in range(33):
        payload = PNG_MAGIC + f"cap-{i:04d}".encode() + b"\x00" * 60
        filename, reason = skinpacks.save_skin_pack_upload("aurora", payload, "image/png")
        assert reason is None
        names.append(filename)
        os.utime(upload_root / filename, (base_time + i, base_time + i))

    remaining = {entry.name for entry in upload_root.iterdir()}
    assert len(remaining) == skinpacks._UPLOAD_MAX_FILES_PER_PACK
    assert names[0] not in remaining          # oldest evicted
    assert names[-1] in remaining             # newest kept
    assert names[1] in remaining


# ── resolve_skin_upload + serve_skin_upload ─────────────────────────────────


@pytest.mark.parametrize(
    "filename",
    [
        "../" + "a" * 64 + ".png",
        "a" * 64 + ".png/../../etc/passwd",
        "a" * 64 + ".svg",
        "a" * 64 + ".txt",
        "A" * 64 + ".png",
        "short.png",
        "",
        None,
        "a" * 64 + ".png.exe",
    ],
)
def test_resolve_and_serve_upload_rejects_bad_filenames(upload_root, filename):
    skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    assert skinpacks.resolve_skin_upload("aurora", filename) is None
    handler = FakeHandler()
    assert skinpacks.serve_skin_upload(handler, "aurora", filename) is True
    assert handler.status == 404
    text = bytes(handler.body).decode("utf-8", "replace")
    assert "not found" in text
    assert "skin_uploads" not in text          # no path leak


def test_serve_upload_rejects_invalid_pack_key(upload_root):
    skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    filename = SHA(PNG_BYTES) + ".png"
    for key in ("../evil", "AURORA", "", None, "aur.ora"):
        assert skinpacks.resolve_skin_upload(key, filename) is None
        handler = FakeHandler()
        assert skinpacks.serve_skin_upload(handler, key, filename) is True
        assert handler.status == 404


# ── routes: POST /api/skins/<key>/upload ────────────────────────────────────


def test_post_upload_route_validation_statuses(upload_root):
    wrong_magic = _post("/api/skins/aurora/upload", PNG_BYTES, "image/jpeg")
    assert wrong_magic.status == 400
    assert "error" in wrong_magic.json_body()

    oversize = _post(
        "/api/skins/aurora/upload",
        PNG_MAGIC + b"\x00" * (2 * 1024 * 1024 + 1),
        "image/png",
    )
    assert oversize.status == 413
    assert "error" in oversize.json_body()

    bad_type = _post("/api/skins/aurora/upload", b"<svg/>" + b"\x00" * 64, "image/svg+xml")
    assert bad_type.status == 400
    assert "error" in bad_type.json_body()


@pytest.mark.parametrize(
    "path",
    [
        "/api/skins/../upload",
        "/api/skins/AURORA/upload",
        "/api/skins/aur.ora/upload",
        "/api/skins//upload",
    ],
)
def test_post_upload_route_rejects_invalid_keys(path):
    handler = _post(path, PNG_BYTES, "image/png")
    assert handler.status == 404, path
    assert "not found" in bytes(handler.body).decode("utf-8", "replace")


# ── routes: GET /api/skins/<key>/uploads/<file> ─────────────────────────────


def test_get_uploads_route_serves_stored_file(upload_root):
    filename, _ = skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    handler = _get(f"/api/skins/aurora/uploads/{filename}")
    assert handler.status == 200
    assert handler.header("Content-Type") == "image/png"
    assert handler.header("Cache-Control") == "no-cache"
    assert handler.header("ETag").startswith('W/"')
    assert bytes(handler.body) == PNG_BYTES

    fresh = _get(f"/api/skins/aurora/uploads/{filename}",
                 headers={"If-None-Match": handler.header("ETag")})
    assert fresh.status == 304
    assert bytes(fresh.body) == b""


@pytest.mark.parametrize(
    "path",
    [
        "/api/skins/aurora/uploads/short.png",
        "/api/skins/aurora/uploads/" + "a" * 64 + ".svg",
        "/api/skins/aurora/uploads/%2e%2e/" + "a" * 64 + ".png",
        "/api/skins/aurora/uploads/" + "a" * 64 + ".png/../../etc/passwd",
        "/api/skins/aurora/uploads/",
        "/api/skins/AURORA/uploads/" + "a" * 64 + ".png",
        "/api/skins/aurora/uploads/missing-" + "a" * 56 + ".png",
    ],
)
def test_get_uploads_route_404s(upload_root, path):
    skinpacks.save_skin_pack_upload("aurora", PNG_BYTES, "image/png")
    handler = _get(path)
    assert handler.status == 404, path
    text = bytes(handler.body).decode("utf-8", "replace")
    assert "not found" in text
    assert "skin_uploads" not in text


# ── end-to-end over the autouse session server ──────────────────────────────


def test_upload_round_trip_over_http():
    """POST real bytes, then GET them back same-origin over the session
    server (no Origin header → non-browser client → CSRF gate passes)."""
    payload = PNG_MAGIC + b"e2e" + b"\x00" * 61
    req = urllib.request.Request(
        BASE + "/api/skins/aurora/upload",
        data=payload,
        headers={"Content-Type": "image/png"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == 200
        stored = json.loads(response.read())
    filename = stored["file"]
    assert filename == SHA(payload) + ".png"

    with urllib.request.urlopen(
        BASE + f"/api/skins/aurora/uploads/{filename}", timeout=10
    ) as response:
        assert response.status == 200
        assert response.headers.get("Content-Type") == "image/png"
        assert response.headers.get("Cache-Control") == "no-cache"
        assert response.read() == payload

    try:
        urllib.request.urlopen(
            BASE + "/api/skins/aurora/uploads/not-a-hash.png", timeout=10
        )
        raised = False
    except urllib.error.HTTPError as exc:
        raised = True
        assert exc.code == 404
    assert raised
