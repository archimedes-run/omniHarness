# Logo assets (Feature 006 logo registry)

The registry is `frontend/src/components/brand/` (`registry.ts`, `marks.ts`, `brand-logo.tsx`). Every logo has an accessible name ("Gmail logo"); an unknown source gets a neutral monogram named after the source. Sources, hashes and terms of what is in the repo are in `THIRD-PARTY-NOTICES.md` (Logos).

## In the repo

| Brand | Kind | Source | Terms to respect |
|---|---|---|---|
| Gmail, Google Calendar, Google Drive | full-colour SVG, `frontend/public/brand/` | Google's product-logo CDN, `fonts.gstatic.com/s/i/productlogos/<product>_2020q4/v8/192px.svg` | Google brand terms; unmodified, full colour, not combined with other marks |
| Anthropic | monochrome mark (theme foreground) | Simple Icons 16.33.0 (CC0 path data) | Anthropic trademark; awaiting the user's confirmation (Open Question 9) |
| GitHub | monochrome mark | Simple Icons 16.33.0 (source github.com/logos) | GitHub logo policy: the Mark, black or white, unmodified |
| Notion, Linear, PostgreSQL | monochrome mark | Simple Icons 16.33.0 | each brand's trademark terms; monochrome black or white |

## Still a monogram (pending fetch)

| Brand | Official page | File to fetch | Why not here |
|---|---|---|---|
| OpenAI ("OAI") | https://openai.com/brand | the OpenAI Blossom mark, SVG, black and white | removed from Simple Icons at OpenAI's request; the page returned 403 to a scripted fetch |
| Slack ("S") | https://slack.com/media-kit | the Slack mark (multicolour), SVG | removed from Simple Icons at Slack's request; the media kit is a manual download |
| Outlook ("O") | https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks | the Outlook product icon, SVG | Microsoft marks removed from Simple Icons at Microsoft's request; Microsoft's terms limit product-icon use |

To add one: put the SVG in `frontend/public/brand/` (or path data in `marks.ts` for a monochrome mark), set `logo` on its `BRANDS` entry, and add a THIRD-PARTY-NOTICES row. `tests/unit/brand-registry.test.ts` checks the file exists, is a clean SVG (no scripts, handlers or external references) and is listed in the notices.
