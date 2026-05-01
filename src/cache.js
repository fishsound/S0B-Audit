'use strict';

const crypto = require('crypto');
const fs     = require('fs');
const fsp    = require('fs').promises;
const path   = require('path');
const { CACHE_DIR } = require('./config');

// Ensure cache dir exists at startup (sync is fine here)
fs.mkdirSync(CACHE_DIR, { recursive: true });

function cachePath(key) {
  return path.join(CACHE_DIR, `${crypto.createHash('md5').update(key).digest('hex')}.json`);
}

async function cacheGet(key, ttlMs) {
  try {
    const raw  = await fsp.readFile(cachePath(key), 'utf8');
    const data = JSON.parse(raw);
    if (Date.now() - new Date(data.savedAt).getTime() > ttlMs) return null;
    return data.value;
  } catch {
    return null;
  }
}

async function cacheSet(key, value) {
  const p   = cachePath(key);
  const tmp = p + '.tmp';
  try {
    await fsp.writeFile(tmp, JSON.stringify({ savedAt: new Date().toISOString(), value }), 'utf8');
    await fsp.rename(tmp, p);
  } catch {}
}

async function cacheClear() {
  let count = 0;
  try {
    const files = (await fsp.readdir(CACHE_DIR)).filter(f => f.endsWith('.json'));
    await Promise.all(files.map(async f => {
      try { await fsp.unlink(path.join(CACHE_DIR, f)); count++; } catch {}
    }));
  } catch {}
  return count;
}

async function cacheStats() {
  try {
    const files = (await fsp.readdir(CACHE_DIR)).filter(f => f.endsWith('.json'));
    if (!files.length) return { count: 0, size_kb: 0, oldest: null, newest: null };
    const stats  = await Promise.all(files.map(f => fsp.stat(path.join(CACHE_DIR, f))));
    const mtimes = stats.map(s => s.mtime.getTime());
    const fmt    = t => new Date(t).toISOString().replace('T', ' ').slice(0, 16);
    return {
      count:    files.length,
      size_kb:  Math.round(stats.reduce((s, f) => s + f.size, 0) / 102.4) / 10,
      oldest:   fmt(Math.min(...mtimes)),
      newest:   fmt(Math.max(...mtimes)),
    };
  } catch {
    return { count: 0, size_kb: 0, oldest: null, newest: null };
  }
}

module.exports = { cacheGet, cacheSet, cacheClear, cacheStats };
