# Finora — Design System

## 1. Visual Philosophy
Finora follows restrained macOS productivity ergonomics (inspired conceptually by Things 3, Apple Numbers, Apple Wallet, and Linear):
- **Information over decoration**: Whitespace, typographic hierarchy, alignment, and 1px hairline borders organize content instead of heavy floating card grids or gradient surfaces.
- **No AI-slop aesthetics**: Purple/rainbow gradients, glassmorphic cards, glowing CTAs, excessive border radii, emoji nav icons, and fake marketing metrics are strictly prohibited.

## 2. Color Tokens (Light & Dark)

Defined in `app/static/css/tokens.css` using `light-dark()` with `:has(> head > meta[name="color-scheme"])` and `@media (prefers-color-scheme: dark)` fallback:

| Token | Light | Dark | Role |
| :--- | :--- | :--- | :--- |
| `--bg-canvas` | `#F7F7F4` | `#151716` | Main application background |
| `--bg-surface` | `#FFFFFF` | `#202321` | Elevated surface / table / modal |
| `--bg-sidebar` | `#EDEFEA` | `#191C1A` | Persistent sidebar chrome |
| `--bg-subtle` | `#E4E8E1` | `#282C29` | Hover / active list states |
| `--text-primary` | `#202420` | `#ECEEEA` | Primary text & monetary balances |
| `--text-secondary` | `#565F57` | `#9CA59E` | Labels, metadata, dates (≥4.5:1 contrast) |
| `--accent-primary` | `#28634B` | `#83B69A` | Primary actions, active focus/nav indicator |
| `--accent-hover` | `#204F3B` | `#96C5AB` | Hover state for primary actions |
| `--accent-text` | `#FFFFFF` | `#101914` | Text on primary accent background |
| `--positive` | `#1F6847` | `#74C198` | Income indicator (always paired with `+` / icon) |
| `--negative` | `#B84B43` | `#E38880` | Expense / deficit / error (always paired with `-` / icon) |
| `--warning` | `#8D5B14` | `#DFAA59` | Warning state |
| `--border-hairline` | `#D7DDD5` | `#2E332F` | Dividers and panel boundaries |
| `--border-control` | `#707A71` | `#69736B` | Form control borders (≥3:1 non-text contrast) |

## 3. Typography & Spacing
- **Font stack**: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif`.
- **Monetary figures**: `font-variant-numeric: tabular-nums;` for aligned columns and zero digit jitter.
- **Scale**: Spacing scale based on `4px` steps (`--space-1: 4px` through `--space-8: 32px`). Radii kept crisp (`--radius-sm: 5px`, `--radius-md: 7px`, `--radius-lg: 10px`).

## 4. Layout & Interaction Standards
- **Shell**: Persistent `224px` sidebar (`192px` at compact widths `<= 1020px`) + fluid main content canvas with `54px` toolbar and controlled scroll inside `<main>`.
- **Minimum Viewport**: `900 × 600` logical pixels without clipped controls, overlapping labels, or horizontal scrollbars.
- **Accessibility**: Visible `:focus-visible` `2px` high-contrast outline (`outline-offset: 2px`), native `<dialog>` with `showModal()` and `Esc`/backdrop dismiss, post-interaction `:user-invalid` + `aria-invalid` validation, `aria-live="polite"` status region, and `@media (prefers-reduced-motion: reduce)`.
