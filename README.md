# SONS of BANE Alliance Auth Compliance Audit Tool

Parameterized, live-data replacement for the old hardcoded `mineski_audit.py`.
Generates sci-fi styled Excel audit reports from `auth.sonsofbane.com` for a single
character, a single corp, or all 24 SONS of BANE corps at once.

## Setup

```bash
pip install requests beautifulsoup4 openpyxl lxml --break-system-packages
cp .env.example .env
# edit .env — paste your session cookie from Chrome DevTools
```

## Usage

```bash
# One character
python sob_audit.py character "aduron"

# One corp by name (partial match) or ID
python sob_audit.py corp "Mineski Infinity"
python sob_audit.py corp 98614919

# All 24 corps + combined alliance report
python sob_audit.py alliance

# Options: --year, --out, --env
python sob_audit.py corp "Mineski Infinity" --year 2026 --out ./reports/
```

Reports are written to `./reports/` by default as `sob_corp_<name>_<date>.xlsx`,
`sob_character_<name>_<date>.xlsx`, or `sob_alliance_<date>.xlsx`.

## Data sources

Data is pulled live from two Alliance Auth plugins — nothing is hardcoded:

- **Member Audit** (`aa-memberaudit`) — character overview, SP, wallet, assets,
  location, sec status, last login, main/alt relationships
- **AFAT** (`aa-afat`) — fleet activity (FAT) counts per main per month,
  correctly attributing alt FATs to mains via the "by main" corp statistics view
- **Character Finder** — authoritative list of characters in a corp

## Styling

Exact match to `mineski_infinity_audit.xlsx`: same dark sci-fi palette, same
`★ ◆ ▷ ○` tier symbols, same `◈` banner, same three sheets (ROSTER / SUMMARY /
CHARTS), same column layout and widths.

## Notes

- The old `mineski_audit.py` (with hardcoded member data) is replaced by this tool
- Session cookie-based auth only; no credentials are stored or transmitted
- `REQUEST_DELAY = 0.3` seconds between requests — polite scraping
- Read-only: the tool never POSTs or modifies data on auth.sonsofbane.com
