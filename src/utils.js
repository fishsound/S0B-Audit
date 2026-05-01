'use strict';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/**
 * Returns a function that runs async tasks with at most `concurrency` in flight.
 * Usage: const limit = limiter(5);  await limit(() => fetchSomething());
 */
function limiter(concurrency) {
  let active = 0;
  const queue = [];
  const run = () => {
    while (active < concurrency && queue.length) {
      active++;
      const { fn, res, rej } = queue.shift();
      fn().then(res, rej).finally(() => { active--; run(); });
    }
  };
  return (fn) => new Promise((res, rej) => { queue.push({ fn, res, rej }); run(); });
}

/** Load Auth.env into a plain object. */
function loadEnvFile(envFile) {
  const fs = require('fs');
  if (!fs.existsSync(envFile)) return {};
  const env = {};
  for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const idx = t.indexOf('=');
    env[t.slice(0, idx).trim()] = t.slice(idx + 1).trim().replace(/^["']|["']$/g, '');
  }
  return env;
}

/** Parse sessionid and csrftoken out of a saved Auth.env. */
function loadCredentials(envFile) {
  const env = loadEnvFile(envFile);
  const cookie = env['SESSION_COOKIE'] || '';
  const sidM  = cookie.match(/sessionid=([^;\s]+)/);
  const csrfM = cookie.match(/csrftoken=([^;\s]+)/);
  const sid  = sidM?.[1]  || env['SESSIONID']  || '';
  const csrf = csrfM?.[1] || env['CSRFTOKEN']  || '';
  if (!sid || !csrf) throw new Error('Credentials missing or incomplete — save them via the UI.');
  return { sessionId: sid, csrfToken: csrf };
}

module.exports = { sleep, limiter, loadEnvFile, loadCredentials };
