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
  return require('util').parseEnv(fs.readFileSync(envFile, 'utf8'));
}

/**
 * Parse sessionid and csrftoken for the Alliance Auth scraper.
 * Priority: process.env.SESSION_COOKIE (Railway / prod) → Auth.env file (local dev).
 */
function loadCredentials(envFile) {
  const parse = (cookie) => {
    const sid  = cookie.match(/sessionid=([^;\s]+)/)?.[1] || '';
    const csrf = cookie.match(/csrftoken=([^;\s]+)/)?.[1] || '';
    return { sid, csrf };
  };

  // 1. Environment variable (Railway / any 12-factor deployment)
  if (process.env.SESSION_COOKIE) {
    const { sid, csrf } = parse(process.env.SESSION_COOKIE);
    if (sid && csrf) return { sessionId: sid, csrfToken: csrf };
  }

  // 2. Auth.env file (local development)
  const env    = loadEnvFile(envFile);
  const cookie = env['SESSION_COOKIE'] || '';
  const { sid, csrf } = parse(cookie);
  const finalSid  = sid  || env['SESSIONID']  || '';
  const finalCsrf = csrf || env['CSRFTOKEN']  || '';
  if (!finalSid || !finalCsrf)
    throw new Error('Alliance Auth credentials not configured. Set SESSION_COOKIE env var or save via the UI.');
  return { sessionId: finalSid, csrfToken: finalCsrf };
}

/** Returns true when credentials come from the environment (Railway mode). */
function credentialsFromEnv() {
  const c = process.env.SESSION_COOKIE || '';
  return /sessionid=[^;\s]/.test(c) && /csrftoken=[^;\s]/.test(c);
}

module.exports = { sleep, limiter, loadEnvFile, loadCredentials, credentialsFromEnv };
