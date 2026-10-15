"""Builtin skin-pack manifest tests (skin-system unification, batch 3).

``scripts/gen_builtin_skin_packs.py`` generates a skin-pack manifest for every
builtin accent skin in ``static/boot.js`` ``_SKINS`` except ``default`` — the
unification that lets the Settings pack picker list the shipped skins as
``applyMode: "css-key"`` packs. These tests pin the generated artifacts:

- every generated manifest passes the real validator with applyMode "css-key"
- the set is exactly the 20 non-default builtin skin keys (no ``default`` dir)
- every key's CSS actually exists in ``static/style.css`` under
  ``:root[data-skin="<key>"]`` or ``:root.dark[data-skin="<key>"]`` — without
  the stylesheet blocks the css-key application mode would be a no-op
- the on-disk manifests are byte-identical to the generator's output, so a
  stale generated file fails loudly instead of drifting
- the hand-authored aurora pack (not generated) still validates
"""

import importlib.util
import json
import sys
from pathlib import Path

from api.skinpacks import _load_and_validate_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKINS_ROOT = REPO_ROOT / "static" / "skins"
GENERATOR = REPO_ROOT / "scripts" / "gen_builtin_skin_packs.py"
STYLE_CSS = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")

# The 20 non-default _SKINS keys, pinned independently of the generator:
# value-derived keys (neon-soft, neon-paint, geist-contrast, verdigris) and
# name-derived keys (everything else, lowercased).
EXPECTED_KEYS = {
    "ares", "mono", "graphite", "github", "codex", "terracotta", "slate",
    "poseidon", "sisyphus", "charizard", "sienna", "catppuccin", "hepburn",
    "nous", "neon", "neon-soft", "neon-paint", "geist-contrast", "zeus",
    "verdigris",
}


def _generator_module():
    spec = importlib.util.spec_from_file_location("gen_builtin_skin_packs", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_builtin_pack_count_is_20():
    # 21 builtin skins ship in boot.js; every one except default becomes a pack
    skins = _generator_module().parse_builtin_skins()
    assert len(skins) == 21
    assert {skin["key"] for skin in skins} == EXPECTED_KEYS | {"default"}
    on_disk = {entry.name for entry in SKINS_ROOT.iterdir() if entry.is_dir()}
    assert on_disk == EXPECTED_KEYS | {"aurora"}


def test_every_builtin_manifest_validates_as_css_key():
    for key in sorted(EXPECTED_KEYS):
        normalized, error = _load_and_validate_manifest(SKINS_ROOT / key)
        assert error is None, f"{key} must validate: {error}"
        assert normalized["key"] == key
        assert normalized["applyMode"] == "css-key", key
        assert normalized["name"], key
        assert 1 <= len(normalized["preview"]["colors"]) <= 3, key


def test_no_default_pack_dir():
    # the default skin is the no-pack baseline — it must never be a pack
    assert not (SKINS_ROOT / "default").exists()


def test_every_key_has_css_block_in_style_css():
    # css-key application sets data-skin="<key>" directly, so the stylesheet
    # must carry the block; verdigris and zeus are dark-only skins
    for key in sorted(EXPECTED_KEYS):
        assert (
            f':root[data-skin="{key}"]' in STYLE_CSS
            or f':root.dark[data-skin="{key}"]' in STYLE_CSS
        ), f"static/style.css has no :root[data-skin={key!r}] block"


def test_generated_manifests_match_generator_output():
    generator = _generator_module()
    skins = {skin["key"]: skin for skin in generator.parse_builtin_skins()}
    assert set(skins) == EXPECTED_KEYS | {"default"}
    for key in sorted(EXPECTED_KEYS):
        expected = json.dumps(
            generator.build_manifest(skins[key]), indent=2, ensure_ascii=False
        ) + "\n"
        on_disk = (SKINS_ROOT / key / "manifest.json").read_text(encoding="utf-8")
        assert on_disk == expected, (
            f"{key}/manifest.json is stale — run scripts/gen_builtin_skin_packs.py"
        )
