# Aurora — builtin skin pack

Aurora is the example skin pack shipped with Hermes WebUI. It doubles as the
reference for pack authors: a complete light + dark palette, all four tweak
types, pack-scoped CSS, brand-icon overrides, a thinking animation, and no
scripts (builtin packs ship script-free by policy).

## Directory layout

```
static/skins/aurora/
├── manifest.json   # pack metadata, palettes, tweaks, icons, thinking (validated)
├── theme.css       # extraCss — layered on top of the builtin skin CSS
├── icons/          # brand icon overrides (full favicon set + logo)
├── anim/           # thinking.gif — replacement thinking indicator
└── README.md       # this guide
```

## manifest.json

The authoritative validator is `_load_and_validate_manifest` in
[`api/skinpacks.py`](../../../api/skinpacks.py) — if a field is rejected there,
the pack is skipped with a warning at discovery time. Field summary:

| Field | Rules |
|---|---|
| `schemaVersion` | must be the integer `1` |
| `key` | `^[a-z0-9][a-z0-9-]{0,31}$`, **must equal the directory name** |
| `name` | 1–40 chars, or a localized object (below) |
| `version` | `^[0-9A-Za-z.+-]{1,32}$` |
| `author`, `description` | optional, ≤60 / ≤200 chars, or a localized object (below) |
| `scheme` | `auto` \| `light` \| `dark` (default `auto`) |
| `applyMode` | optional, `pack` (default) \| `css-key`. A `css-key` pack's styling already ships in the app stylesheet keyed by `:root[data-skin="<key>"]` — the frontend applies it by setting `data-skin` to the bare key (no `pack:` prefix, no managed palette style). The server validates the enum only and never restricts which keys may use it. The generated builtin skin packs (see below) use `css-key`. |
| `preview.colors` | 0–3 safe color values (hex, rgb()/rgba()/hsl()/hsla(), `r, g, b` triple, keyword, number+unit; never `url()`, ≤64 chars) |
| `palette.light` / `palette.dark` | token → safe value; omitting one side mirrors the other |
| `extraCss` | optional relative subpath inside the pack (e.g. `"theme.css"`) |
| `scripts` | optional, ≤4 relative subpaths — see consent below |
| `tweaks` | 0–12 entries, unique ids `^[a-z0-9-]{1,32}$`, labels ≤40 chars |
| `icons`, `thinking` | optional — brand-icon overrides and a thinking-indicator replacement, see below |

Palette token names (without the `--` prefix): the accent family
(`accent`, `accent-hover`, `accent-bg`, `accent-bg-strong`, `accent-text`,
`accent2`, `accent3`, `accent-contrast`, `accent-rgb`), the documented design
tokens (`bg`, `surface`, `text`, `border`, …), and pack-scoped customs
(`pack-[a-z0-9-]{1,32}`). Unknown tokens and unsafe values are dropped
individually — they never reject the whole pack.

### Localized text

`name`, `description`, `tweaks[].label` and `tweaks[].options[].label` accept
either a plain string or a localized object with 1–8 entries:

```json
{ "en": "Glow strength", "zh": "发光强度", "zh-Hant": "發光強度" }
```

Locale keys match `^[a-z]{2}(-[A-Za-z0-9]{2,8})?$`; each value is a string
within the same per-field length limit. The raw form is preserved through
validation and the frontend resolves it per locale. Invalid locale keys and
over-length values drop just that entry; an object left empty behaves like an
absent field — a missing name rejects the pack, an emptied description is
treated as absent, and an emptied tweak/option label drops that tweak/option
(the pack survives).

## Tweak types

| Type | Extra fields | `apply` |
|---|---|---|
| `range` | `min` < `max`, `step` > 0, `default` clamped | `{var}` or `{var, template}` |
| `select` | 1–8 options (`value` `^[A-Za-z0-9._-]{1,32}$`), `default` must be an option | `{var}` or `{var, template}` |
| `toggle` | `default` boolean | `{class: "pack-…"}` (toggle-only) or `{var}` |
| `color` | `default` `^#[0-9a-fA-F]{3,8}$` | `{var}` or `{var, template}` |
| `image` | no `default` — the value is a server-generated upload filename | `{var}` only |

A `template` (≤128 chars) must contain `{value}` and may only use
`A-Za-z0-9 #%(),./-` around it — one declaration value, never a second rule.
At runtime each tweak either sets a CSS custom property (optionally through
the template) or toggles a `pack-*` class on the root element; `theme.css`
consumes the results (see `var(--pack-glow-strength)`,
`var(--pack-accent-tone)` and `html.pack-compact` there).

An `image` tweak uploads a picture through the panel (PNG/JPEG/GIF/WebP,
≤2 MB, magic-byte checked; stored content-addressed under the WebUI state
dir and served same-origin) and sets its variable to `url(<upload URL>)` —
consume it as `var(--token, none)` so removing the upload clears it. Aurora
demonstrates this with the `corner-image` tweak: upload any picture and it
appears as a corner watermark over the chat area.

## How packs are discovered

Two roots are scanned at startup and on settings reload:

- **builtin**: `static/skins/` in the WebUI repo (this pack)
- **user**: `$HERMES_HOME/skins/` for the active profile

A user pack with the same `key` as a builtin pack **shadows** the builtin one.
An invalid `manifest.json` only skips that pack — its neighbours are unaffected.

## The generated builtin packs

Every builtin accent skin in `static/boot.js` (`_SKINS`, except `default`)
also exists as a generated `css-key` pack under `static/skins/<key>/`, so the
built-in skins show up in the same pack picker. Those manifests are owned by
`scripts/gen_builtin_skin_packs.py` — regenerate rather than hand-edit them.
Aurora is the only hand-authored builtin pack.

## Icons and thinking animation

`icons` (all keys optional; values are pack-relative paths, served same-origin
under the pack's asset base):

| Key | Replaces |
|---|---|
| `favicon` | the SVG favicon `<link>` and the manifest "any" icon |
| `favicon32` | the 32px favicon link + manifest entry |
| `favicon192` | the manifest 192 icon + desktop-notification icon |
| `favicon512` | the manifest 512 icon |
| `appleTouch` | the iOS `apple-touch-icon` link |
| `faviconIco` | the `/favicon.ico` response |
| `logoSvg` | the in-app brand marks (titlebar icon + empty-state logo) |

`thinking` swaps the pending-thinking indicator (the three pulsing dots shown
while waiting for the first token):

| Key | Rules |
|---|---|
| `mode` | `none` (default) \| `gif` \| `css` |
| `gif` | pack-relative GIF shown inside the indicator box (`size`, 8–128 px, default 28) |
| `css` | pack-relative stylesheet; scope rules under `:root[data-skin="pack:<key>"]` and override `.thinking` / `.thinking .dot` |

Aurora demonstrates `gif` mode with `anim/thinking.gif` and a full self-contained
`icons/` set (no references outside the pack directory). Manifest values are
paths only — remote URLs are rejected by validation.

## Scripts and consent

Scripts listed in `scripts` are never loaded silently. On first use the UI
shows a consent prompt ("This pack contains custom scripts") because pack
scripts run with full page trust; the choice is stored per pack and can be
reversed later (reload required). Builtin packs — including Aurora — ship
without any `scripts` field.
