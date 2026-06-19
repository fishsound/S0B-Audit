# SONS of BANE Alliance Auth Compliance Audit Tool

Web app that generates sci-fi styled PDF audit reports from `auth.sonsofbane.com`
for a single corp or all SONS of BANE corps at once. Members log in with EVE SSO;
the app scrapes Alliance Auth (Member Audit + AFAT) and ESI for live data — nothing
is hardcoded.

## Run

```bash
npm install
cp .env.example Auth.env   # see "Configuration" below
npm start                  # http://localhost:8000
# npm run dev              # same, with --watch reload
```

## Configuration

Set as environment variables (Railway dashboard) or in `Auth.env` for local dev:

| Var | Purpose |
|-----|---------|
| `EVE_CLIENT_ID` / `EVE_CLIENT_SECRET` | EVE SSO app — register at https://developers.eveonline.com/ |
| `EVE_CALLBACK_URL` | Must match the SSO app exactly (default `http://localhost:8000/auth/callback`) |
| `SESSION_SECRET` | Express session signing secret |
| `SESSION_COOKIE` | Alliance Auth scraper cookie: `sessionid=…; csrftoken=…` (copy from Chrome DevTools). Admins can also save it via the UI. |
| `ADMIN_CHARS` | Comma-separated EVE character IDs granted admin access |
| `PORT` | Defaults to `8000` |

## Usage

Log in with EVE SSO. Access depends on your character:

- **Member** (any SoB character) — audit your own corporation.
- **Admin** (`ADMIN_CHARS`) — audit any corp, run the full alliance audit, import
  AFAT CSV reports, manage the scraper cookie, and clear the cache.

Reports stream progress over a WebSocket and are written to `./reports/` as
`sob_corp_<name>_<date>.pdf`, `sob_alliance_<date>.pdf`, or
`sob_csv_<name>_<date>.pdf` (each with a sibling `.json` for the in-app viewer).

## Data sources

- **Member Audit** (`aa-memberaudit`) — overview, SP, wallet, assets, location,
  sec status, last login, main/alt relationships
- **AFAT** (`aa-afat`) — FAT counts per main per month, attributing alt FATs to
  mains via the "by main" corp statistics view
- **Character Finder** — authoritative list of characters in a corp
- **ESI** — corp/character join dates ("time in alliance")

## Notes

- Read-only scraping; the tool never POSTs to or modifies auth.sonsofbane.com.
- `REQUEST_DELAY = 50ms` between scraper requests; responses are cached under
  `.cache/` (TTLs in `src/config.js`).
- Cookie auth only — no Alliance Auth credentials are stored beyond the session
  cookie you provide.
