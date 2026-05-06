'use strict';

/**
 * Diagnostic: fetch a character viewer page and report everything
 * that could be the assets data URL — data attrs, hx-get, script blocks, etc.
 *
 * Usage: node scripts/inspect-assets-tab.js
 */

const axios   = require('axios');
const cheerio = require('cheerio');
const path    = require('path');
const { loadCredentials } = require('../src/utils');
const { BASE_URL, USER_AGENT } = require('../src/config');

const ENV_FILE = path.join(__dirname, '..', 'Auth.env');

async function main() {
  const { sessionId, csrfToken } = loadCredentials(ENV_FILE);
  const client = axios.create({
    baseURL: BASE_URL,
    timeout: 20000,
    headers: {
      'User-Agent':  USER_AGENT,
      'Accept':      'text/html,application/json',
      'Cookie':      `sessionid=${sessionId}; csrftoken=${csrfToken}`,
      'X-CSRFToken': csrfToken,
    },
    maxRedirects: 0,
    validateStatus: s => s < 400,
  });

  // ── Step 1: get one character PK from the finder ──────────────────────────
  console.log('Fetching character finder (first 10 results)…');
  const params = { draw: '1', start: '0', length: '10' };
  for (let i = 0; i < 13; i++) {
    params[`columns[${i}][data]`]          = String(i);
    params[`columns[${i}][searchable]`]    = 'true';
    params[`columns[${i}][orderable]`]     = 'false';
    params[`columns[${i}][search][value]`] = '';
    params[`columns[${i}][search][regex]`] = 'false';
  }
  const finder = await client.get('/member-audit/character_finder_data', { params });
  if (!finder.data?.data?.length) {
    console.error('No characters returned from finder. Check credentials.');
    process.exit(1);
  }

  // Extract the first character PK and name from column 0 HTML
  const firstRow = finder.data.data[0];
  const $f = cheerio.load(firstRow[0] || '');
  const href = $f('a[href*="/member-audit/character_viewer/"]').first().attr('href') || '';
  const pkMatch = href.match(/\/character_viewer\/(\d+)\//);
  if (!pkMatch) {
    console.error('Could not parse character PK from finder row:', firstRow[0]);
    process.exit(1);
  }
  const pk   = pkMatch[1];
  const name = $f('a').first().text().trim();
  console.log(`\nUsing character: ${name} (pk=${pk})\n`);

  // ── Step 2: fetch the character viewer page ───────────────────────────────
  console.log(`Fetching /member-audit/character_viewer/${pk}/…`);
  const viewer = await client.get(`/member-audit/character_viewer/${pk}/`);
  const $v = cheerio.load(viewer.data);

  // ── Step 3: report all data-url / hx-get / data-tab-url / href containing "asset" ──
  console.log('\n=== Elements with data-url / hx-get / data-tab-url / data-src ===');
  const dataAttrs = ['data-url', 'hx-get', 'data-tab-url', 'data-src', 'href'];
  for (const attr of dataAttrs) {
    $v(`[${attr}]`).each((_, el) => {
      const val = $v(el).attr(attr) || '';
      if (val.startsWith('/')) {
        console.log(`  ${attr}: ${val}  [tag=${el.tagName}, id=${$v(el).attr('id') || ''}, class=${($v(el).attr('class') || '').slice(0, 60)}]`);
      }
    });
  }

  // ── Step 4: dump ALL <script> content that mentions "asset" ──────────────
  console.log('\n=== Script blocks mentioning "asset" ===');
  let foundScript = false;
  $v('script').each((_, el) => {
    const src = $v(el).html() || '';
    if (/asset/i.test(src)) {
      foundScript = true;
      // Print lines mentioning asset
      src.split('\n').forEach(line => {
        if (/asset/i.test(line)) console.log(' ', line.trim().slice(0, 200));
      });
      console.log('  ---');
    }
  });
  if (!foundScript) console.log('  (none)');

  // ── Step 5: dump all nav tabs and their associated pane ids ──────────────
  console.log('\n=== Nav tabs / tab panes ===');
  $v('.nav-tabs a, .nav-tabs button, [role="tab"]').each((_, el) => {
    const text   = $v(el).text().trim();
    const target = $v(el).attr('href') || $v(el).attr('data-bs-target') || $v(el).attr('data-target') || '';
    console.log(`  "${text}" → ${target}`);
  });
  $v('.tab-pane, [role="tabpanel"]').each((_, el) => {
    const id = $v(el).attr('id') || '';
    const url = $v(el).attr('data-url') || $v(el).attr('hx-get') || '';
    console.log(`  pane id="${id}"  data-url="${url}"`);
  });

  // ── Step 6: try the guessed URL and report what comes back ───────────────
  const guessedUrl = `/member-audit/character_assets_data/${pk}/`;
  console.log(`\n=== Testing hardcoded guess: GET ${guessedUrl} ===`);
  try {
    const ar = await client.get(guessedUrl, {
      params: { draw: '1', start: '0', length: '5' },
      validateStatus: () => true,
    });
    console.log(`  Status: ${ar.status}`);
    if (ar.status === 200) {
      const d = ar.data;
      console.log(`  Type: ${typeof d}`);
      if (typeof d === 'object') {
        console.log(`  Keys: ${Object.keys(d).join(', ')}`);
        if (Array.isArray(d.data)) {
          console.log(`  data[0]: ${JSON.stringify(d.data[0]).slice(0, 300)}`);
        }
      } else {
        console.log(`  Body (first 400 chars): ${String(d).slice(0, 400)}`);
      }
    }
  } catch (e) {
    console.log(`  Error: ${e.message}`);
  }

  console.log('\nDone.');
}

main().catch(e => { console.error(e.message); process.exit(1); });
