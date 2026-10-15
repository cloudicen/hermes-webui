# Hermes Web UI — Themes

Hermes Web UI splits **appearance** into two independent pickers:

- **Theme** — the mode: `System`, `Dark`, or `Light`. Drives the background,
  text, surface, and chrome colors.
- **Skin** — the accent palette: built-in skins ship as named keys. Drives only
  the `--accent` family (active states, links, focus rings, primary actions).

You pick one of each and they combine, so the look adapts to your environment
without losing your favorite accent — pure CSS, no Python changes needed.

---

## Switching Appearance

**Settings panel:** Click the gear icon → **Appearance**. The **Theme** card
toggles Light/Dark/System; the **Skin** grid offers the built-in accent palettes.
Preview is instant — the UI updates as you click.

**Slash command:** Type `/theme <name>` in the composer. The command accepts
both theme names (`system`, `dark`, `light`) and skin names (`default`, `ares`,
`mono`, `slate`, `poseidon`, `sisyphus`, `charizard`, `sienna`,
`catppuccin`, `nous`, `geist-contrast`, `zeus`). It updates the matching axis and leaves the other one
alone.

**Persistence:** Both choices are stored in `localStorage` for flicker-free
loading, and saved server-side via `POST /api/settings` (under `theme` and
`skin` keys in `settings.json`).

---

## Built-in Themes

| Theme | Description |
|-------|-------------|
| **System** (default) | Follows the OS `prefers-color-scheme` preference and updates live. |
| **Dark** | Deep dark surfaces, low-glare for long sessions. |
| **Light** | Bright surfaces with dark text, high contrast for daylight environments. |

The theme is applied as a class on `<html>`: `.dark` is present for dark mode,
absent for light. System mode tracks the OS preference at runtime.

---

## Built-in Skins

| Skin | Description |
|------|-------------|
| **Default** | The original Hermes gold accent. Warm and understated. |
| **Ares** | Fiery red. High-energy and assertive. |
| **Mono** | Neutral gray. Distraction-free, for deep focus. |
| **Slate** | Slate blue-gray. Subtle and grown-up. |
| **Poseidon** | Ocean blue. Calm and focused for long sessions. |
| **Sisyphus** | Vivid purple. Distinctive without being loud. |
| **Charizard** | Warm orange. Energetic and easy on the eyes. |
| **Sienna** | Warm clay and sand earth palette. Soft and natural. |
| **Catppuccin** | Catppuccin Latte/Mocha palette with Mauve accent. |
| **Nous** | Steel-blue accent with dashed technical surfaces. |
| **Geist Contrast** (`geist-contrast`) | Geist-inspired monochrome surfaces with a restrained dark-mode `#FFF175` accent. |
| **Zeus** | OLED-near-black dark surfaces that keep the default gold accent. Dark-focused; falls back to the default light palette in light mode. |

Each skin defines paired light + dark variants so it reads cleanly on either
theme. The skin is applied as `data-skin="<name>"` on `<html>` (the default
skin clears the attribute).

---

## Creating a Custom Skin

A skin is a small CSS block that overrides the accent variables for both the
light and dark variants:

```css
/* Light variant */
:root[data-skin="my-skin"] {
  --accent:           #2E7D32;                   /* Active states, links, primary buttons */
  --accent-hover:     #1B5E20;                   /* Hover */
  --accent-bg:        rgba(46,125,50,0.08);      /* Soft tinted backgrounds */
  --accent-bg-strong: rgba(46,125,50,0.15);      /* Highlighted backgrounds */
  --accent-text:      #1B5E20;                   /* Text on accent bg */
}

/* Dark variant — usually lighter or more saturated for contrast */
:root.dark[data-skin="my-skin"] {
  --accent:           #66BB6A;
  --accent-hover:     #43A047;
  --accent-bg:        rgba(102,187,106,0.08);
  --accent-bg-strong: rgba(102,187,106,0.15);
  --accent-text:      #66BB6A;
}
```

Two ways to ship it:

1. **In the repo (built-in):** add the block to `static/style.css`, register it
   in the Settings skin picker (`static/index.html`) and in the `/theme` command
   list (`static/commands.js`), then open a PR.

2. **Self-hosted (no fork):** use the WebUI extensions surface — see
   `docs/EXTENSIONS.md`. Drop your CSS in `HERMES_WEBUI_EXTENSION_DIR` and
   declare it in `HERMES_WEBUI_EXTENSION_STYLESHEET_URLS`. No code changes
   needed; the skin attribute can be set from your own JS.

   Extensions that register a skin through `window.registerHermesSkin()` may
   also set `scheme: "light"` or `scheme: "dark"` for light-only or dark-only
   skins. The saved Theme preference stays unchanged, but WebUI applies the
   matching effective base class while that skin is selected so System/Light or
   System/Dark does not mix incompatible base tokens into the skin.

### Tips

- **Test both themes.** A skin that pops on Dark can be illegible on Light.
  Always check `:root[data-skin]` (light) *and* `:root.dark[data-skin]` (dark).
- **Pick contrasting `--accent-text` on `--accent-bg`.** The strong variant
  appears behind small labels and chips; weak contrast there reads as blur.
- **The logo gradient uses `--accent` automatically**, so it adapts to your
  skin without any extra work.
- **No server changes needed.** The `skin` setting in `settings.json` accepts
  any string, so your custom skin name persists without code changes once you
  load the CSS.

---

## Skin Packs

A **skin pack** is a drop-in directory (`manifest.json` plus assets) that layers
a palette, optional extra CSS, and declarative tweak options on top of the
built-in look. No fork, no rebuild, no Python. The Settings → Appearance skin
grid **is** the pack picker: the twenty built-in accent skins ship as builtin
packs (`applyMode: "css-key"` — their CSS already lives in the app stylesheet,
so applying one just sets `data-skin="<key>"`), while user packs apply as
`data-skin="pack:<key>"` with a managed palette style. The active skin is the
single `skin_pack` setting (the legacy `skin` key is kept in sync for
compatibility), and the `pack:` namespace can never collide with a builtin
skin name.

Two roots are discovered at boot:

| Root | Location | Notes |
|------|----------|-------|
| **Builtin** | `static/skins/<key>/` | Shipped with the repo, committable |
| **User** | `.hermes/skins/<key>/` | Hermes home user-data area (gitignored) |

A user pack whose key matches a builtin pack **shadows** it; the Settings picker
badges each pack with its origin and shadow status. A pack whose manifest fails
validation is skipped with a server-log warning; the other packs still load.

Besides hand-authored packs like Aurora, the builtin root carries one generated
`css-key` manifest per builtin accent skin (every `_SKINS` entry in
`static/boot.js` except `default`). They are owned by
`scripts/gen_builtin_skin_packs.py` — regenerate instead of hand-editing — and
make the built-in skins selectable from the same pack picker.

### The manifest

`manifest.json` is declarative by default: CSS, tokens, and option definitions
only. No pack JavaScript runs unless you give it consent (below).

| Field | Required | Meaning |
|-------|----------|---------|
| `schemaVersion` | yes | Must be the integer `1`. |
| `key` | yes | Must equal the directory name and match `^[a-z0-9][a-z0-9-]{0,31}$`. |
| `name`, `version` | yes | Picker display name, and a free-form version string. |
| `author`, `description` | no | Credit line and blurb shown in the picker. |
| `scheme` | no | `auto` (default), `light`, or `dark`: forces the effective base scheme while the pack is selected, the same contract as extension-skin `scheme`. |
| `applyMode` | no | `pack` (default) or `css-key`. A `css-key` pack's styling already ships in the app stylesheet keyed by `:root[data-skin="<key>"]`, so the frontend applies it by setting `data-skin` to the bare key — no `pack:` prefix, no managed palette style. The server validates the enum only. |
| `preview.colors` | no | 1-3 swatch colors drawn on the picker tile. |
| `palette` | no | `light` + `dark` maps of token name (written without `--`) to value. Allowed tokens: the accent family, the documented design tokens, and custom `pack-*` tokens. Each value must pass a safe-CSS regex, so `url()` and friends are rejected. |
| `extraCss` | no | One optional stylesheet inside the pack directory, loaded via `<link>`. |
| `scripts` | no | Up to 4 JS files inside the pack directory. Loaded only behind explicit per-pack consent, recorded in settings. |
| `tweaks` | no | 0-12 declarative options (below). |
| `icons`, `thinking` | no | Brand-icon overrides: `favicon`/`favicon32`/`favicon192`/`favicon512`/`appleTouch` swap the favicon links, the manifest icons, and `/favicon.ico`; `logoSvg` replaces the in-app brand marks (titlebar + empty-state); `favicon192` also becomes the desktop-notification icon. `thinking` swaps the pending-thinking indicator: `mode: "gif"` shows a pack GIF in the indicator box (`size`, 8-128 px), `mode: "css"` loads a pack stylesheet to restyle `.thinking` — scope rules under `:root[data-skin="pack:<key>"]`. |

`name`, `description`, `tweaks[].label` and `tweaks[].options[].label` also
accept a localized object instead of a plain string — `{"en": "Glow strength",
"zh": "发光强度"}` — with 1–8 entries whose locale keys look like `en`, `zh`, or
`zh-Hant`. The raw form is preserved and the frontend resolves it per locale;
invalid entries drop individually and an object emptied entirely behaves like
an absent field.

The browser reads the catalog from `GET /api/skins` (metadata, manifests, and an
`assetsBase` per pack) and fetches pack files from
`GET /api/skins/<key>/assets/<rel>`. Asset serving is sandboxed to the pack
directory and sent with `Cache-Control: no-cache` plus ETag/304 revalidation:
user pack files are mutable, so the `?v=` fingerprint used for immutable static
assets deliberately does not apply.

Applying a pack writes a managed `<style>` whose light and dark blocks are scoped
to the pack attribute:

```css
/* managed palette <style> for pack "my-pack" */
:root[data-skin="pack:my-pack"]      { --accent: #0e7490; /* palette.light */ }
:root.dark[data-skin="pack:my-pack"] { --accent: #22d3ee; /* palette.dark  */ }
```

Selecting a builtin skin again removes the pack's managed styles and restores
the previous builtin skin.

### Tweaks and script consent

Each tweak declares an `id`, a `label`, a `type` (`range`, `select`, `toggle`,
`color`, or `image`), a `default` (not for `image`), and an `apply` spec that
either sets a CSS variable (optionally through a `{value}` template) or toggles
a `pack-*` class on `<html>`. Tweak controls render inside Settings →
Appearance from the active pack's schema, preview live, and persist through
the same appearance autosave as theme and skin (`POST /api/settings`). Applied
values land in a second managed `<style>` placed after the palette one, plus
the `pack-*` classes. A reset button next to the section title restores every
tweak of the active pack to its manifest defaults.

An `image` tweak lets the user upload a picture straight from the panel
(`POST /api/skins/<key>/upload`): PNG/JPEG/GIF/WebP up to 2 MB, magic-byte
checked, stored content-addressed (sha256) under the WebUI state dir, and
served same-origin from `/api/skins/<key>/uploads/<file>`. The stored value
is the server-generated filename; applying it sets the declared CSS variable
to `url('<same-origin URL>')` — the URL is server-shaped end to end and never
passes through the pack-token sanitizer. Removing the upload clears the
variable, so consume it as `var(--token, none)`. SVG uploads are deliberately
rejected: an uploaded SVG served same-origin is a stored-XSS surface that
pack assets (admin-authored files) do not have.

A pack that declares `scripts` shows an explicit consent prompt in the UI. Its JS
loads only after you approve that pack, and the decision persists in the
`skin_script_consents` setting; withdrawing consent returns the pack to
declaration-only.

State layers:

| Store | Key | Contents |
|-------|-----|----------|
| `settings.json` | `skin_pack` | Selected pack key; `""` means no pack, the builtin skin axis rules. |
| `settings.json` | `skin_tweaks` | Pack key → {tweak id → value}, revalidated against discovered packs on load and save. |
| `settings.json` | `skin_script_consents` | Pack key → bool. |
| `localStorage` | `hermes-skin-pack`, `hermes-skin-pack-palette` | Boot mirrors read before first paint, so a pack applies flicker-free alongside theme and skin. |

### Copy-paste starting point

The shipped `static/skins/aurora/` pack is the reference: a cyan/teal accent
family with full light + dark palettes, one tweak of each of the four types, an
`extraCss` demo (`theme.css`), and a pack-author walkthrough at
`static/skins/aurora/README.md`. To make your own:

```
.hermes/skins/
  my-pack/
    manifest.json    # "key" must equal "my-pack"
    theme.css        # optional, referenced by "extraCss"
```

Copy the aurora directory, change `key` and `name`, drop it under `.hermes/skins/`,
and pick it in Settings → Appearance.

---

## Creating a Custom Theme

A full custom *theme* (a different overall mood, not just an accent change) is
a larger task than a skin: it has to redefine the core palette variables
(`--bg`, `--surface`, `--text`, `--border`, `--code-bg`, and friends) for one
or both modes. The contract is defined in the top `:root` and `:root.dark`
blocks of `static/style.css` — start there.

Most of the time, a custom **skin** is what you actually want. Reach for a
custom theme only when the existing Light/Dark modes don't fit (for example,
a high-contrast accessibility theme or an OLED black variant).

---

## Font Size

Right under Theme/Skin in **Settings → Appearance**: `Small`, `Default`,
`Large`. Applied as `data-font-size` on `<html>` and scales the WebUI's root
font size. Persists alongside theme and skin.

---

## Typography Tokens

The three font tokens are declared in `static/style.css`:

- `--font-ui`: user interface chrome, controls, composer chrome, labels, and
  ordinary non-code UI text
- `--font-conversation`: user/assistant message prose
- `--font-mono`: code, tool details, logs, identifiers, and terminal text

By default:

```css
--font-conversation: var(--font-ui);
--font-mono: ui-monospace,"SFMono-Regular","SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
```

For CSS-based custom skins and extension stylesheets/scripts, override the three
font tokens directly (`--font-ui`, `--font-conversation`, `--font-mono`) on the
skin root (`:root[data-skin="..."]`), including any mode-specific variant.
`window.registerHermesSkin()` currently accepts only the documented design-token
allowlist (no `--font-*` tokens), so custom font families should be supplied via
CSS rather than skin registration.

Leaving `--font-conversation` untouched keeps prose coupled to `--font-ui`;
override it only when a different reading face is explicitly required. Avoid
hard-coded selector-level font declarations when one of these tokens already
expresses the intent.

---

## How It Works Internally

1. **Theme:** `document.documentElement.classList.toggle('dark', isDark)` —
   light mode removes the class. System mode tracks
   `matchMedia('(prefers-color-scheme: dark)')`. Extension-registered skins
   may declare a light/dark `scheme`; when selected, that scheme controls the
   effective `.dark` class without rewriting the saved Theme preference.
2. **Skin:** `document.documentElement.dataset.skin = name` (or remove the
   attribute for `default`).
3. **Font size:** `document.documentElement.dataset.fontSize = size` (or
   remove for `default`).
4. **No flash on load:** a tiny inline `<script>` in `<head>` reads
   `localStorage` before the stylesheet does, so the right look is applied
   before paint.
5. **Server sync:** preferences are saved via `POST /api/settings` and
   rehydrated on boot via `GET /api/settings`.

---

## Contributing a Skin

Skins are the easiest extension point — pure CSS, no Python, no JS logic. To
contribute one upstream:

1. Add your `:root[data-skin="name"]` and `:root.dark[data-skin="name"]`
   blocks to `static/style.css`.
2. Register it in the Settings skin picker in `static/index.html` and in the
   skin list used by `cmdTheme()` in `static/commands.js`.
3. Test on desktop and mobile across both Light and Dark themes.
4. Open a PR — skins are pure CSS additions with no backend changes needed.

For a custom *theme* (overriding the base palette), prefer opening an issue
first to discuss scope, since it touches many selectors.
