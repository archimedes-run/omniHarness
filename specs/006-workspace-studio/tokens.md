# Feature 006 theme tokens ("Graphite")

One set of semantic CSS variables in `frontend/src/styles/globals.css`. Light values live in
`:root, .light`; dark ("Graphite") values in `.dark`. `.light` / `.dark` also work on any element,
so a preview can show the other theme with the same tokens. Components use the Tailwind utilities
(`bg-<token>`, `text-<token>`, `border-<token>`) and never a hex, `rgb()` or palette class:
`frontend/tests/unit/colour-tokens.test.ts` enforces that, and
`frontend/tests/rendering/contrast.spec.ts` measures every audited page in both themes against WCAG AA.

Values come from the design reference (`design/*.dc.html`) and `design-notes.md`. No value from the
brief's table failed AA, so none was tuned. `--sidebar-accent` (light) is not in the table; it was chosen as `#E4E6EA`,
one step darker than the light sidebar, so a selected item reads without the inverted black fill
the old theme used.

## Colour tokens

| Token | Utility | Role (mockup) | Light | Dark |
|---|---|---|---|---|
| `--background` | `bg-background` | bg (page) | `#F7F7F8` | `#121316` |
| `--foreground` | `text-foreground` | text | `#17181B` | `#ECEDEF` |
| `--foreground-2` | `text-foreground-2` | text-2 (secondary body text) | `#2F333A` | `#C9CCD2` |
| `--card` / `--card-foreground` | `bg-card` | surface (cards, sheets) | `#FFFFFF` / `#17181B` | `#1C1E23` / `#ECEDEF` |
| `--popover` / `--popover-foreground` | `bg-popover` | dropdowns, menus | `#FFFFFF` / `#17181B` | `#24272D` / `#ECEDEF` |
| `--surface-raised` | `bg-surface-raised` | raised (chips, hovered rows, inputs on cards) | `#F1F2F4` | `#24272D` |
| `--secondary` / `--secondary-foreground` | `bg-secondary` | raised (shadcn secondary) | `#F1F2F4` / `#17181B` | `#24272D` / `#ECEDEF` |
| `--muted` | `bg-muted` | raised (shadcn muted fill) | `#F1F2F4` | `#24272D` |
| `--muted-foreground` | `text-muted-foreground` | muted (metadata) | `#5A606B` | `#9EA3AD` |
| `--accent` / `--accent-foreground` | `bg-accent` | neutral hover wash (NOT the blue accent) | `#F1F2F4` / `#17181B` | `#24272D` / `#ECEDEF` |
| `--primary` / `--primary-foreground` | `bg-primary text-primary-foreground`, `text-primary` | accent / on-accent | `#3355D6` / `#FFFFFF` | `#8FA8FF` / `#121316` |
| `--ring` | `ring-ring` | focus ring (the accent) | `#3355D6` | `#8FA8FF` |
| `--highlight` / `--highlight-foreground` | `text-highlight` | active / selected thing (the accent) | `#3355D6` / `#FFFFFF` | `#8FA8FF` / `#121316` |
| `--success` / `--success-foreground` | `text-success` | good ("Live") | `#1E7A4B` / `#FFFFFF` | `#6FD3A0` / `#121316` |
| `--warning` / `--warning-foreground` | `text-warning` | warn ("Off", held) | `#8A5300` / `#FFFFFF` | `#F2B65A` / `#121316` |
| `--destructive` / `--destructive-foreground` | `text-destructive` | bad ("Unreachable", failed) | `#B3261E` / `#FFFFFF` | `#FF8A80` / `#121316` |
| `--border` | `border-border` | border | `#DDDFE3` | `#2E3138` |
| `--border-strong` | `border-border-strong` | strong-border (outline buttons) | `#C9CCD3` | `#4A4E57` |
| `--input` | `border-input` | input borders | `#C9CCD3` | `#3A3E46` |
| `--sidebar` | `bg-sidebar` | sidebar | `#EFF0F2` | `#17181C` |
| `--sidebar-foreground` | `text-sidebar-foreground` | sidebar labels (text-2) | `#2F333A` | `#C9CCD2` |
| `--sidebar-accent` / `-foreground` | `bg-sidebar-accent` | active / hovered sidebar item | `#E4E6EA` / `#17181B` | `#24272D` / `#ECEDEF` |
| `--sidebar-primary` / `-foreground` | `bg-sidebar-primary` | accent in the sidebar | `#3355D6` / `#FFFFFF` | `#8FA8FF` / `#121316` |
| `--sidebar-border` | `border-sidebar-border` | sidebar border | `#DDDFE3` | `#2E3138` |
| `--sidebar-ring` | `ring-sidebar-ring` | focus in the sidebar | `#3355D6` | `#8FA8FF` |
| `--primary-subtle` | `bg-primary-subtle` | selected tab / selected "+" fill (text on it: `text-foreground`, never muted) | `#E7EBFA` | `#2F3A5C` |
| `--overlay` | `bg-overlay/60` | scrim behind panels and dialogs | `#17181B` | `#0C0D0F` |
| `--avatar-lead`, `--avatar-0..7` (+ `-foreground`) | `bg-avatar-N text-avatar-N-foreground`; mention `text-avatar-N-foreground` | agent avatars and @mentions, see below | see below | see below |
| `--chart-1..5` | `bg-chart-N` | chart series (unchanged) | oklch, see CSS | oklch, see CSS |

Opacity modifiers are fine (`bg-primary/10`, `border-border/60`).

## Measured contrast (WCAG 2.x, AA = 4.5:1 normal text)

| Pair | Light | Dark |
|---|---|---|
| foreground on background | 16.58 | 15.86 |
| foreground-2 on card | 12.69 | 10.36 |
| muted-foreground on background | 5.91 | 7.34 |
| muted-foreground on surface-raised / muted | 5.65 | 5.91 |
| primary (as text) on card | 6.16 | 7.32 |
| primary-foreground on primary | 6.16 | 8.15 |
| success on card | 5.33 | 9.13 |
| success on surface-raised | 4.76 | 8.20 |
| success-foreground on success | 5.33 | 10.17 |
| warning on card | 6.33 | 9.22 |
| warning-foreground on warning | 6.33 | 10.27 |
| destructive on card | 6.54 | 7.30 |
| destructive-foreground on destructive | 6.54 | 8.14 |
| sidebar-foreground on sidebar | 11.12 | 11.02 |
| sidebar-foreground on sidebar-accent | 10.15 | 9.30 |
| primary on sidebar-accent | 4.93 | 6.57 |
| foreground on primary-subtle | 14.93 | 9.53 |
| muted-foreground on primary-subtle (NOT allowed) | 5.32 | **4.41, fails** |
| primary on primary-subtle | 5.18 | 4.90 |

`tests/rendering/theme.spec.ts` re-measures the token pairs from painted pixels in both themes.

Colours derived from a token rather than given their own: link hover is the accent mixed with
white (`hover:text-primary/80` or a `color-mix`), status-pill borders are the status colour at 35%
(`border-success/35`). The mockups' logo placeholder fills are dropped (the real logos replace them).

**Non-text contrast.** Borders against the background are about 1.4:1 and the input border about
2:1, under the 3:1 non-text guideline, so no state may be carried by a border colour alone: an off
switch is told by its knob (muted, 5.9:1), a field by its fill and its label, a selected tab by
`bg-primary-subtle` plus `text-foreground` (the shadcn tabs already use `text-foreground` when
active).

## Agent avatars and @mentions

`src/core/agents/avatar.ts` picks the colour: `avatarColor(agentId)` is a stable FNV-1a hash of the
id modulo 8, and the lead agent (`lead_agent`) always gets `lead`. `avatarClasses(id)` and
`mentionClasses(id)` return literal class names. An @mention takes the colour of the mentioned
agent's avatar, so there is no separate mention colour. Each foreground is AA on its own fill, on
the page and on a card, because it is also the mention text.

**Colour is never the only identifier.** An avatar always shows the agent's initials
(`avatarInitials`), and a mention always shows the name.

| N | Hue | Light fill / fg | fg on fill / on page | Dark fill / fg | fg on fill / on page |
|---|---|---|---|---|---|
| `lead` | neutral | `#E4E6EA` / `#17181B` | 13.95 / 16.58 | `#24272D` / `#ECEDEF` | 12.78 / 15.86 |
| `0` | blue | `#DEE7F7` / `#285ABD` | 5.13 / 5.97 | `#2B3750` / `#87A9EE` | 5.07 / 7.91 |
| `1` | violet | `#E7DEF7` / `#5F28BD` | 6.41 / 7.77 | `#382B50` / `#B694F0` | 5.21 / 7.5 |
| `2` | magenta | `#F7DEF7` / `#A022A0` | 5.18 / 6.07 | `#502B50` / `#ED82ED` | 5.0 / 7.98 |
| `3` | pink | `#F7DEE7` / `#B12554` | 5.08 / 6.01 | `#502B37` / `#EE8BAC` | 5.12 / 7.89 |
| `4` | red-orange | `#F7E3DE` / `#A83E24` | 5.03 / 5.8 | `#50322B` / `#ED9782` | 5.1 / 8.27 |
| `5` | amber | `#F7EEDE` / `#825D1C` | 5.16 / 5.55 | `#50422B` / `#ECC279` | 5.83 / 11.11 |
| `6` | green | `#DEF7EB` / `#187245` | 5.27 / 5.55 | `#2B503D` / `#79ECB3` | 6.24 / 12.79 |
| `7` | teal | `#DEF5F7` / `#196E76` | 5.24 / 5.55 | `#2B4D50` / `#79E2EC` | 6.1 / 12.3 |

`tests/rendering/theme.spec.ts` measures every pair (fg on fill, on background, on card) in both themes.

## Type and shape

- `font-sans`: Inter 400 / 500 / 600; `font-mono`: JetBrains Mono 400 / 500, for ids, paths and
  code. Both are self-hosted through `next/font` (downloaded at build time, served by the app; no
  runtime font CDN). `src/app/layout.tsx` sets `--font-inter` and `--font-jetbrains-mono`.
- Radii (`--radius` = 10 px): `rounded-md` 8 px (controls), `rounded-lg` 10 px (cards),
  `rounded-xl` 14 px (panels and sheets).

## Exceptions

Brand logos in `frontend/src/components/brand/` keep their official colours. Other fixed colours
(always-dark code panels, overlays, decorative effects) are listed one literal at a time, each with
its reason, in `ALLOWED` in `colour-tokens.test.ts`.

## Appearance

Settings > Appearance offers Light / Dark / System (System is the default). The choice is stored per
user in the gateway database (`GET/PUT /api/preferences/appearance`, table `user_preferences`),
applied before first paint during SSR, and cached in localStorage under next-themes' `theme` key.
