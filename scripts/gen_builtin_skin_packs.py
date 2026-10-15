#!/usr/bin/env python3
"""Generate the builtin skin-pack manifests from the boot.js ``_SKINS`` array.

Skin-system unification (batch 3): every builtin accent skin — everything in
``_SKINS`` except ``default`` — also becomes a selectable skin pack whose
styling already ships in ``static/style.css`` keyed by
``:root[data-skin="<key>"]`` (and/or the ``:root.dark[...]`` variant). Those
generated packs declare ``"applyMode": "css-key"``: the frontend applies them
by setting ``data-skin="<key>"`` directly — no ``pack:`` prefix, no managed
palette style.

This script is the single source of truth for the generated manifests:

- it parses the ``_SKINS`` array literal from ``static/boot.js``; the key is
  the entry's ``value`` when present, else the lowercased ``name`` — the same
  convention ``_VALID_SKINS`` uses in boot.js
- it writes ``static/skins/<key>/manifest.json`` for every skin except
  ``default``, deterministically (re-running rewrites identical bytes)
- it only ever writes directories for keys parsed from ``_SKINS``, so
  hand-authored packs like ``static/skins/aurora/`` are never touched

Stdlib only; paths resolve relative to this file so it runs from anywhere.
Usage: ``python3 scripts/gen_builtin_skin_packs.py``
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOT_JS = REPO_ROOT / "static" / "boot.js"
SKINS_ROOT = REPO_ROOT / "static" / "skins"

# The default skin is the no-pack baseline; it must never become a pack.
EXCLUDED_KEYS = frozenset({"default"})

_SKINS_ARRAY_RE = re.compile(r"const\s+_SKINS\s*=\s*\[(?P<body>.*?)\];", re.DOTALL)
# Entry shape in boot.js: {name:'Display Name'[, value:'skin-key'],
# colors:['#hex', ...]} — name first, optional value second, colors last.
_SKIN_ENTRY_RE = re.compile(
    r"\{\s*name:\s*'(?P<name>[^']+)'"
    r"(?:,\s*value:\s*'(?P<value>[^']+)')?"
    r",\s*colors:\s*\[(?P<colors>[^\]]*)\]"
    r"\s*\}"
)


def parse_builtin_skins(boot_js: Path = BOOT_JS) -> list[dict]:
    """The ``_SKINS`` entries as ``{key, name, colors}`` dicts, in file order.

    Raises ``ValueError`` when the array is missing or an entry does not match
    the expected literal shape — silent partial parses would ship a stale
    pack set, so drift must fail loudly here instead of at discovery time.
    """
    source = boot_js.read_text(encoding="utf-8")
    array_match = _SKINS_ARRAY_RE.search(source)
    if array_match is None:
        raise ValueError(f"const _SKINS array not found in {boot_js}")
    body = array_match.group("body")
    skins = []
    for entry in _SKIN_ENTRY_RE.finditer(body):
        colors = [c.strip().strip("'\"") for c in entry.group("colors").split(",")]
        skins.append(
            {
                "key": (entry.group("value") or entry.group("name")).lower(),
                "name": entry.group("name"),
                "colors": [c for c in colors if c],
            }
        )
    expected = body.count("{name:")
    if len(skins) != expected:
        raise ValueError(
            f"parsed {len(skins)} of {expected} _SKINS entries in {boot_js}: "
            "the array literal changed shape — update _SKIN_ENTRY_RE"
        )
    return skins


def build_manifest(skin: dict) -> dict:
    """The deterministic manifest for one builtin skin."""
    return {
        "schemaVersion": 1,
        "key": skin["key"],
        "name": skin["name"],
        "version": "1.0.0",
        "author": "Hermes WebUI",
        "description": f"{skin['name']} — built-in accent skin (now a skin pack)",
        "scheme": "auto",
        "applyMode": "css-key",
        "preview": {"colors": skin["colors"][:3]},
    }


def generate(skins_root: Path = SKINS_ROOT) -> list[str]:
    """Write every non-default builtin skin manifest; returns the keys."""
    keys = []
    for skin in parse_builtin_skins():
        if skin["key"] in EXCLUDED_KEYS:
            continue
        pack_dir = skins_root / skin["key"]
        pack_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = pack_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(build_manifest(skin), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        keys.append(skin["key"])
    return keys


def main() -> int:
    keys = generate()
    print(f"builtin skin packs: wrote {len(keys)} manifests to {SKINS_ROOT}")
    for key in keys:
        print(f"  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
