const path = require('path');

const ROOT_DIR = path.join(__dirname, '..');

module.exports = {
  BASE_URL:        'https://auth.sonsofbane.com',
  ESI_BASE:        'https://esi.evetech.net',
  SOB_ALLIANCE_ID: 99001969,
  USER_AGENT:      'SoB-Audit-Tool/2.0 (web; contact: alliance leadership)',

  REQUEST_DELAY:   50,   // ms between auth scraper requests
  AUTH_CONCURRENCY: 5,
  ESI_CONCURRENCY:  10,

  TTL: {
    OVERVIEW:  24 * 60 * 60 * 1000,   // 24 h
    ESI:       24 * 60 * 60 * 1000,
    FAT_MONTH:  2 * 60 * 60 * 1000,   //  2 h
    FINDER:     6 * 60 * 60 * 1000,   //  6 h
  },

  MONTH_ABBRS: ['Jan','Feb','Mar','Apr','May','Jun',
                'Jul','Aug','Sep','Oct','Nov','Dec'],

  ROOT_DIR,
  CACHE_DIR:   path.join(ROOT_DIR, '.cache'),
  REPORTS_DIR: path.join(ROOT_DIR, 'reports'),
  ENV_FILE:    path.join(ROOT_DIR, 'Auth.env'),
  STATIC_DIR:  path.join(ROOT_DIR, 'static'),
  PORT:        process.env.PORT || 8000,
};
