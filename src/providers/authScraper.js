'use strict';

const axios   = require('axios');
const cheerio = require('cheerio');
const { BaseProvider } = require('./base');
const { cacheGet, cacheSet } = require('../cache');
const { BASE_URL, SOB_ALLIANCE_ID, USER_AGENT, REQUEST_DELAY,
        AUTH_CONCURRENCY, TTL, MONTH_ABBRS } = require('../config');
const { makeCharacter } = require('../models');
const { limiter, sleep } = require('../utils');

// ── Parsers ───────────────────────────────────────────────────────────────────

const stripHtml = (s) => (s || '').replace(/<[^>]+>/g, '').trim();

function parseIskB(s) {
  if (!s) return 0;
  const m = s.replace(/ISK|,/g, '').match(/([-+]?\d+(?:\.\d+)?)/);
  return m ? Math.round(parseFloat(m[1]) / 1e9 * 100) / 100 : 0;
}

function parseSpM(s) {
  if (!s) return 0;
  const m = s.replace(/SP|,/g, '').match(/(\d+(?:\.\d+)?)/);
  return m ? Math.round(parseFloat(m[1]) / 1e6 * 10) / 10 : 0;
}

function parseSec(s) {
  const m = (s || '').match(/[-+]?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : 0;
}

// ── Provider ──────────────────────────────────────────────────────────────────

class AllianceAuthProvider extends BaseProvider {
  get name() { return 'alliance_auth'; }
  get requiresAuth() { return true; }

  constructor(sessionId, csrfToken) {
    super();
    this._limit  = limiter(AUTH_CONCURRENCY);
    this._client = axios.create({
      baseURL: BASE_URL,
      timeout: 20000,
      headers: {
        'User-Agent':       USER_AGENT,
        'Accept':           'text/html,application/json',
        'Accept-Language':  'en-US,en;q=0.9',
        'X-Requested-With': 'XMLHttpRequest',
        'Cookie':           `sessionid=${sessionId}; csrftoken=${csrfToken}`,
        'X-CSRFToken':      csrfToken,
      },
      maxRedirects: 0,
      validateStatus: s => s < 400,
    });
  }

  async _get(path, params) {
    await sleep(REQUEST_DELAY);
    let r;
    try {
      r = await this._client.get(path, { params });
    } catch (e) {
      if (e.code === 'ECONNABORTED' || e.code === 'ETIMEDOUT') {
        throw new Error(`Alliance Auth timed out (${BASE_URL}). Check that the server is reachable.`);
      }
      if (e.code === 'ECONNREFUSED' || e.code === 'ENOTFOUND') {
        throw new Error(`Cannot reach Alliance Auth (${BASE_URL}): ${e.code}`);
      }
      throw e;
    }
    const url = r.request?.path || '';
    if (r.status === 302 || url.includes('login')) {
      throw new Error('Auth failed — session cookie has expired. Re-copy from Chrome DevTools.');
    }
    return r;
  }

  // ── Character Finder ───────────────────────────────────────────────────────

  async _finderRaw(corpName = '') {
    const key    = `finder:${corpName}`;
    const cached = await cacheGet(key, TTL.FINDER);
    if (cached) return cached;

    const all = [];
    let start = 0;
    while (true) {
      const params = { draw: '1', start: String(start), length: '100' };
      for (let i = 0; i < 13; i++) {
        params[`columns[${i}][data]`]          = String(i);
        params[`columns[${i}][searchable]`]    = 'true';
        params[`columns[${i}][orderable]`]     = 'false';
        params[`columns[${i}][search][value]`] = '';
        params[`columns[${i}][search][regex]`] = 'false';
      }
      if (corpName) params['columns[7][search][value]'] = corpName;

      const r    = await this._get('/member-audit/character_finder_data', params);
      const data = r.data;
      if (!data?.data) throw new Error('character_finder_data did not return JSON — are you logged in?');
      all.push(...data.data);
      const total = data.recordsFiltered || 0;
      start += data.data.length;
      if (!data.data.length || start >= total) break;
    }
    await cacheSet(key, all);
    return all;
  }

  _parseNameCell(html) {
    const $ = cheerio.load(html);
    const a = $('a[href*="/member-audit/character_viewer/"]').first();
    if (!a.length) return [null, ''];
    const m = (a.attr('href') || '').match(/\/character_viewer\/(\d+)\//);
    return [m ? parseInt(m[1]) : null, a.text().trim()];
  }

  async listCorpMembers(corpName) {
    const rows  = await this._finderRaw(corpName);
    const mains = [];
    for (const r of rows) {
      if (r.length < 13 || r[10] !== 'yes') continue;
      const [pk, name] = this._parseNameCell(r[0]);
      if (!pk) continue;
      const ch = makeCharacter(pk, name);
      ch.isMain       = true;
      ch.corpName     = stripHtml(r[7]);
      ch.allianceName = stripHtml(r[6]);
      try { ch.eveId = parseInt(r[12]); } catch {}
      mains.push(ch);
    }
    return mains;
  }

  async listAllianceCorps(year, month) {
    const key    = `alliance_corps:${year}:${month}`;
    const cached = await cacheGet(key, TTL.FINDER);
    if (cached) return cached;

    const r  = await this._get(
      `/fleet-activity-tracking/statistics/alliance/${SOB_ALLIANCE_ID}/${year}/${month}/`
    );
    const $  = cheerio.load(r.data);
    const corps = [];
    $('tbody tr').each((_, tr) => {
      const link = $(tr).find('a[href*="/corporation/"]').first();
      if (!link.length) return;
      const m = (link.attr('href') || '').match(/\/corporation\/(\d+)\//);
      if (!m) return;
      const id   = parseInt(m[1]);
      const name = $(tr).find('td').first().text().trim() || `Corp ${id}`;
      if (!corps.some(c => c[0] === id)) corps.push([id, name]);
    });
    await cacheSet(key, corps);
    return corps;
  }

  // ── Character Overview ─────────────────────────────────────────────────────

  async _overview(pk) {
    const key    = `overview:${pk}`;
    const cached = await cacheGet(key, TTL.OVERVIEW);
    if (cached) return cached;

    const r = await this._get(`/member-audit/character_viewer/${pk}/`);
    const $ = cheerio.load(r.data);
    const result = {};
    $('dl.dl-horizontal').each((_, dl) => {
      const dts = $(dl).find('dt').toArray();
      const dds = $(dl).find('dd').toArray();
      dts.forEach((dt, i) => {
        const key = $(dt).text().trim().replace(/:$/, '');
        if (key && dds[i]) result[key] = $(dds[i]).text().replace(/\s+/g, ' ').trim();
      });
    });
    const h = $('h1,h2').first();
    if (h.length && !result['Character']) result['Character'] = h.text().trim();

    // Extract the assets data URL from this same page so _topAssetSystem doesn't
    // need a second HTTP round-trip. Look in data-attrs and inline scripts.
    const assetUrl = this._discoverAssetUrl($, r.data);
    if (assetUrl) await cacheSet(`asset_url:${pk}`, assetUrl);

    await cacheSet(key, result);
    return result;
  }

  _discoverAssetUrl($, html) {
    // Strategy 1: data attributes (htmx, Bootstrap tabs, custom loaders)
    const dataAttrs = ['data-url', 'hx-get', 'data-tab-url', 'data-src'];
    for (const attr of dataAttrs) {
      let found = null;
      $(`[${attr}]`).each((_, el) => {
        const val = $(el).attr(attr) || '';
        if (!found && /asset/i.test(val) && val.startsWith('/')) found = val;
      });
      if (found) return found;
    }
    // Strategy 2: inline <script> blocks — look for a /member-audit/...asset... URL string
    const scripts = $('script').map((_, s) => $(s).html() || '').toArray().join('\n');
    const patterns = [
      /["'](\/member-audit\/[^"'\s]*asset[^"'\s]*data[^"'\s]*)['"]/i,
      /["'](\/member-audit\/[^"'\s]*asset[^"'\s]*)['"]/i,
      /url\s*[:=]\s*["'](\/member-audit\/[^"'\s]*asset[^"'\s]*)['"]/i,
    ];
    for (const re of patterns) {
      const m = scripts.match(re);
      if (m) return m[1];
    }
    return null;
  }

  _overviewToChar(pk, ov) {
    const ch = makeCharacter(pk, ov['Character'] || ov['Name'] || `char_${pk}`);
    ch.corpName     = ov['Corporation'] || '';
    ch.allianceName = ov['Alliance']    || '';
    ch.mainName     = ov['Main']        || '';
    ch.isMain       = ch.mainName === ch.name || !ch.mainName;
    ch.born         = ov['Born']        || '';
    ch.lastLogin    = ov['Last Login']  || '';
    ch.location     = ov['Location']    || ov['System'] || '';
    ch.ship         = ov['Ship']        || '';
    const spRaw = ov['Skill Points'] || ov['Skillpoints'] || ov['Total Skill Points'] || ov['SP']
      || Object.entries(ov).find(([k]) => /skill.*point/i.test(k))?.[1] || '';
    ch.skillpointsM = parseSpM(spRaw);
    ch.secStatus    = parseSec(ov['Sec. Status'] || '');
    ch.walletB      = parseIskB(ov['Wallet']  || '');
    ch.assetsB      = parseIskB(ov['Assets']  || '');
    return ch;
  }

  // ── AFAT ──────────────────────────────────────────────────────────────────

  async _fatMonth(corpId, year, month) {
    const today     = new Date();
    const isCurrent = year === today.getFullYear() && month === today.getMonth() + 1;
    const key       = `fat:${corpId}:${year}:${month}`;
    if (!isCurrent) {
      const cached = await cacheGet(key, TTL.FAT_MONTH);
      if (cached) return cached;
    }
    try {
      const r = await this._get(
        `/fleet-activity-tracking/statistics/corporation/${corpId}/${year}/${month}/`
      );
      const $ = cheerio.load(r.data);
      const results = {};
      $('table').first().find('tbody tr').each((_, tr) => {
        const cells = $(tr).find('td').map((_, td) => $(td).text().trim()).toArray();
        if (cells.length >= 2) {
          const n = parseInt(cells[1]);
          if (!isNaN(n)) results[cells[0]] = n;
        }
      });
      if (!isCurrent) await cacheSet(key, results);
      return results;
    } catch {
      return {};
    }
  }

  // ── Asset location ────────────────────────────────────────────────────────

  async _topAssetSystem(pk) {
    const key    = `asset_sys:${pk}`;
    const cached = await cacheGet(key, TTL.OVERVIEW);
    if (cached !== null) return cached === '__none__' ? '' : cached;

    try {
      // Prefer the URL discovered from the character viewer page HTML.
      // Fall back to the most common aa-memberaudit DataTables naming convention.
      const discovered = await cacheGet(`asset_url:${pk}`, TTL.OVERVIEW);
      const endpoint   = discovered || `/member-audit/character_assets_data/${pk}/`;
      const r    = await this._get(endpoint, { draw: '1', start: '0', length: '2000' });
      const rows = r.data?.data;
      if (!Array.isArray(rows) || !rows.length) {
        await cacheSet(key, '__none__');
        return '';
      }

      // Response uses named keys: { solar_system, total, location, region, … }
      // solar_system is the system name directly; total is ISK value of that row.
      const totals = {};
      for (const row of rows) {
        const sys = row.solar_system
          || (typeof row.location === 'string' ? row.location.split(' - ')[0].trim() : '');
        if (!sys) continue;
        const val = typeof row.total === 'number' ? row.total : 1;
        totals[sys] = (totals[sys] || 0) + val;
      }

      const top = Object.entries(totals).sort(([, a], [, b]) => b - a)[0]?.[0] || '';
      await cacheSet(key, top || '__none__');
      return top;
    } catch {
      return '';
    }
  }

  // ── Alt counting ──────────────────────────────────────────────────────────

  async _buildAltCountMap() {
    const all = await this._finderRaw('');
    const map = new Map();
    for (const r of all) {
      if (r.length < 13 || r[10] === 'yes') continue;
      // column 2 (main_character) has the same HTML format as column 0 —
      // an anchor pointing to /member-audit/character_viewer/<pk>/ with the
      // character name as link text.  Reuse _parseNameCell for reliable extraction.
      const [, mainName] = this._parseNameCell(r[2] || '');
      if (mainName) map.set(mainName, (map.get(mainName) || 0) + 1);
    }
    return map;
  }

  // ── Provider entry-point ──────────────────────────────────────────────────

  async enrich(chars, corpId, corpName, year, log) {
    const today = new Date();

    log(`      building alt counts…`, 'grey');
    const altMap = await this._buildAltCountMap();
    for (const ch of chars) ch.altCount = altMap.get(ch.name) || 0;

    log(`      fetching overviews (${chars.length} chars)…`, 'grey');
    await Promise.all(chars.map(ch => this._limit(async () => {
      try {
        const ov     = await this._overview(ch.pk);
        const merged = this._overviewToChar(ch.pk, ov);
        merged.corpId       = corpId;
        merged.corpName     = corpName;
        merged.eveId        = ch.eveId;
        if (!merged.allianceName) merged.allianceName = ch.allianceName;
        Object.assign(ch, merged);
      } catch (e) {
        log(`      ! overview ${ch.name}: ${e.message}`, 'red');
      }
    })));

    log(`      fetching asset locations (${chars.length} chars)…`, 'grey');
    await Promise.all(chars.map(ch => this._limit(async () => {
      ch.topAssetSystem = await this._topAssetSystem(ch.pk);
    })));

    // Build 3-year FAT task list
    const tasks = [];
    for (let y = year - 2; y <= year; y++) {
      const maxM = y < today.getFullYear() ? 12 : today.getMonth() + 1;
      for (let m = 1; m <= maxM; m++) tasks.push([y, m]);
    }

    log(`      fetching ${tasks.length} FAT months…`, 'grey');
    const fatMap = new Map();
    await Promise.all(tasks.map(([y, m]) => this._limit(async () => {
      fatMap.set(`${y}:${m}`, await this._fatMonth(corpId, y, m));
    })));

    const byName = Object.fromEntries(chars.map(ch => [ch.name, ch]));
    for (let y = year - 2; y <= year; y++) {
      const maxM      = y < today.getFullYear() ? 12 : today.getMonth() + 1;
      const yearTotals = {};
      for (let m = 1; m <= maxM; m++) {
        for (const [charName, cnt] of Object.entries(fatMap.get(`${y}:${m}`) || {})) {
          yearTotals[charName] = (yearTotals[charName] || 0) + cnt;
          const ch = byName[charName];
          if (ch) {
            const k = `${y}-${MONTH_ABBRS[m - 1]}`;
            ch.fatsByMonth[k] = (ch.fatsByMonth[k] || 0) + cnt;
          }
        }
      }
      for (const [charName, total] of Object.entries(yearTotals)) {
        const ch = byName[charName];
        if (ch) ch.fatsByYear[y] = (ch.fatsByYear[y] || 0) + total;
      }
    }
    for (const ch of chars) {
      ch.totalFats = Object.values(ch.fatsByYear).reduce((a, b) => a + b, 0);
    }
  }
}

module.exports = { AllianceAuthProvider };
