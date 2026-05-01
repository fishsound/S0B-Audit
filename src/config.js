const path = require('path');

const ROOT_DIR = path.join(__dirname, '..');

module.exports = {
  BASE_URL:        'https://auth.sonsofbane.com',
  ESI_BASE:        'https://esi.evetech.net',
  SOB_ALLIANCE_ID: 99001969,
  USER_AGENT:      'SoB-Audit-Tool/2.0 (web; contact: alliance leadership)',

  REQUEST_DELAY:    50,
  AUTH_CONCURRENCY: 5,
  ESI_CONCURRENCY:  10,

  TTL: {
    OVERVIEW:  24 * 60 * 60 * 1000,
    ESI:       24 * 60 * 60 * 1000,
    FAT_MONTH:  2 * 60 * 60 * 1000,
    FINDER:     6 * 60 * 60 * 1000,
  },

  MONTH_ABBRS: ['Jan','Feb','Mar','Apr','May','Jun',
                'Jul','Aug','Sep','Oct','Nov','Dec'],

  ROOT_DIR,
  CACHE_DIR:   path.join(ROOT_DIR, '.cache'),
  REPORTS_DIR: path.join(ROOT_DIR, 'reports'),
  ENV_FILE:    path.join(ROOT_DIR, 'Auth.env'),
  STATIC_DIR:  path.join(ROOT_DIR, 'static'),
  PORT:        process.env.PORT || 8000,

  // ── EVE SSO ───────────────────────────────────────────────────────────────
  // Register your app at https://developers.eveonline.com/
  // Set these as environment variables (Railway dashboard or .env).
  EVE_CLIENT_ID:     process.env.EVE_CLIENT_ID     || '',
  EVE_CLIENT_SECRET: process.env.EVE_CLIENT_SECRET  || '',
  // Must match exactly what you set in the EVE developer portal.
  EVE_CALLBACK_URL:  process.env.EVE_CALLBACK_URL   || 'http://localhost:8000/auth/callback',

  // ── Sessions ──────────────────────────────────────────────────────────────
  SESSION_SECRET: process.env.SESSION_SECRET || 'change-me-in-production',

  // ── Role config ───────────────────────────────────────────────────────────
  // Comma-separated EVE character IDs granted admin access (can run alliance
  // audits, clear cache, manage credentials).
  // e.g. ADMIN_CHARS=12345678,87654321
  ADMIN_CHAR_IDS: (process.env.ADMIN_CHARS || '')
    .split(',').map(s => parseInt(s.trim())).filter(Boolean),
};
