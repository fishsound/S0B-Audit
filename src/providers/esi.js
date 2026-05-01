'use strict';

const axios = require('axios');
const { BaseProvider } = require('./base');
const { cacheGet, cacheSet } = require('../cache');
const { ESI_BASE, SOB_ALLIANCE_ID, TTL, USER_AGENT, ESI_CONCURRENCY } = require('../config');
const { limiter, sleep } = require('../utils');

async function esiGet(path) {
  const delays = [1000, 2000, 4000];
  for (let i = 0; i <= delays.length; i++) {
    try {
      const r = await axios.get(`${ESI_BASE}${path}`, {
        headers: { 'User-Agent': USER_AGENT },
        timeout: 10000,
      });
      if (r.status === 200) return r.data;
      if (r.status < 500) return [];
    } catch {}
    if (i < delays.length) await sleep(delays[i]);
  }
  return [];
}

function formatDuration(startMs) {
  const totalDays = Math.floor((Date.now() - startMs) / 86400000);
  const years  = Math.floor(totalDays / 365);
  const months = Math.floor((totalDays % 365) / 30);
  const days   = totalDays % 30;
  const parts  = [];
  if (years)  parts.push(`${years} year${years  > 1 ? 's' : ''}`);
  if (months) parts.push(`${months} month${months > 1 ? 's' : ''}`);
  if (!parts.length) parts.push(`${days} day${days > 1 ? 's' : ''}`);
  return parts.slice(0, 2).join(', ');
}

const MONTH_ABBRS = ['Jan','Feb','Mar','Apr','May','Jun',
                     'Jul','Aug','Sep','Oct','Nov','Dec'];

function fmtDate(isoString) {
  const d = new Date(isoString);
  return `${d.getUTCFullYear()}-${MONTH_ABBRS[d.getUTCMonth()]}-${String(d.getUTCDate()).padStart(2,'0')}`;
}

class ESIProvider extends BaseProvider {
  get name() { return 'esi'; }

  constructor() {
    super();
    this._limit = limiter(ESI_CONCURRENCY);
  }

  async _charCorpJoin(eveId, corpId) {
    const key    = `esi_char:${eveId}:${corpId}`;
    const cached = await cacheGet(key, TTL.ESI);
    if (cached !== null) return cached === '__none__' ? null : new Date(cached).getTime();

    const history = await esiGet(`/v2/characters/${eveId}/corporationhistory/`);
    let result = null;
    for (const entry of [...history].reverse()) {
      if (entry.corporation_id === corpId) { result = new Date(entry.start_date).getTime(); break; }
    }
    await cacheSet(key, result !== null ? new Date(result).toISOString() : '__none__');
    return result;
  }

  async _corpAllianceJoin(corpId) {
    const key    = `esi_corp:${corpId}`;
    const cached = await cacheGet(key, TTL.ESI);
    if (cached !== null) return cached === '__none__' ? null : new Date(cached).getTime();

    const history = await esiGet(`/v2/corporations/${corpId}/alliancehistory/`);
    let result = null;
    for (const entry of [...history].reverse()) {
      if (entry.alliance_id === SOB_ALLIANCE_ID) { result = new Date(entry.start_date).getTime(); break; }
    }
    await cacheSet(key, result !== null ? new Date(result).toISOString() : '__none__');
    return result;
  }

  async enrich(chars, corpId, corpName, year, log) {
    const corpJoin = await this._corpAllianceJoin(corpId);
    if (corpJoin) log(`      corp joined SoB: ${fmtDate(new Date(corpJoin).toISOString())}`, 'grey');

    log(`      fetching ESI join dates (${chars.length} chars)…`, 'grey');
    await Promise.all(chars.map(ch => this._limit(async () => {
      if (!ch.eveId) return;
      const charJoin = await this._charCorpJoin(ch.eveId, corpId);
      if (charJoin === null) { ch.joinDate = '—'; ch.timeInCorp = '—'; return; }
      ch.joinDate   = fmtDate(new Date(charJoin).toISOString());
      const effMs   = corpJoin !== null && corpJoin > charJoin ? corpJoin : charJoin;
      ch.timeInCorp = formatDuration(effMs);
    })));
  }
}

module.exports = { ESIProvider };
