'use strict';

/**
 * EVE SSO OAuth2 routes.
 *
 * GET  /auth/login    — redirect to EVE SSO
 * GET  /auth/callback — handle OAuth callback, build session
 * GET  /auth/logout   — destroy session
 * GET  /auth/me       — return current session user (or { authenticated: false })
 *
 * Required env vars (set in Railway dashboard):
 *   EVE_CLIENT_ID, EVE_CLIENT_SECRET, EVE_CALLBACK_URL
 *
 * Register your app at https://developers.eveonline.com/
 * Callback URL must match EVE_CALLBACK_URL exactly.
 */

const crypto = require('crypto');
const axios  = require('axios');
const { EVE_CLIENT_ID, EVE_CLIENT_SECRET, EVE_CALLBACK_URL,
        SOB_ALLIANCE_ID, ADMIN_CHAR_IDS, USER_AGENT } = require('../config');
const { credentialsFromEnv } = require('../utils');

const SSO_AUTH   = 'https://login.eveonline.com/v2/oauth/authorize';
const SSO_TOKEN  = 'https://login.eveonline.com/v2/oauth/token';
// Scope needed to check corp roles (Director/CEO) for officer status.
const SSO_SCOPES = 'esi-characters.read_corporation_roles.v1';

// ── SSO helpers ───────────────────────────────────────────────────────────────

function buildAuthUrl(state) {
  return `${SSO_AUTH}?${new URLSearchParams({
    response_type: 'code',
    client_id:     EVE_CLIENT_ID,
    redirect_uri:  EVE_CALLBACK_URL,
    scope:         SSO_SCOPES,
    state,
  })}`;
}

async function exchangeCode(code) {
  const r = await axios.post(
    SSO_TOKEN,
    new URLSearchParams({ grant_type: 'authorization_code', code }),
    {
      headers: {
        Authorization:   `Basic ${Buffer.from(`${EVE_CLIENT_ID}:${EVE_CLIENT_SECRET}`).toString('base64')}`,
        'Content-Type':  'application/x-www-form-urlencoded',
        'User-Agent':    USER_AGENT,
      },
    },
  );
  return r.data; // { access_token, refresh_token, expires_in, … }
}

function parseJwt(token) {
  return JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
}

async function esiGet(path, accessToken) {
  const headers = { 'User-Agent': USER_AGENT };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
  const r = await axios.get(`https://esi.evetech.net${path}`, { headers, timeout: 10000 });
  return r.data;
}

/**
 * Build the session user object after a successful OAuth callback.
 * Checks alliance membership and corp roles, assigns a role.
 */
async function resolveUser(accessToken) {
  const jwt    = parseJwt(accessToken);
  const charId = parseInt(jwt.sub.split(':')[2]);
  const name   = jwt.name;

  const charInfo = await esiGet(`/v5/characters/${charId}/`);
  const corpId   = charInfo.corporation_id;
  const corpInfo = await esiGet(`/v4/corporations/${corpId}/`);
  const allianceId = corpInfo.alliance_id || null;

  let role = 'none';
  if (allianceId === SOB_ALLIANCE_ID) {
    role = 'member';

    // Check corp roles using the scoped token
    try {
      const rolesData = await esiGet(`/v2/characters/${charId}/roles/`, accessToken);
      const roles     = rolesData.roles || [];
      if (roles.includes('Director') || roles.includes('CEO')) role = 'officer';
    } catch { /* scope may be missing or ESI down — stay as member */ }

    // Admin override: character ID explicitly listed in ADMIN_CHARS env var
    if (ADMIN_CHAR_IDS.includes(charId)) role = 'admin';
  }

  return {
    charId,
    charName:  name,
    corpId,
    corpName:  corpInfo.name || '',
    allianceId,
    role,
    // Whether SESSION_COOKIE is sourced from env (Railway) vs the saved file
    credFromEnv: credentialsFromEnv(),
  };
}

// ── Routes ────────────────────────────────────────────────────────────────────

module.exports = (app) => {

  app.get('/auth/login', (req, res) => {
    if (!EVE_CLIENT_ID || !EVE_CLIENT_SECRET)
      return res.status(500).send('EVE SSO not configured. Set EVE_CLIENT_ID and EVE_CLIENT_SECRET.');
    const state = crypto.randomBytes(16).toString('hex');
    req.session.oauthState = state;
    res.redirect(buildAuthUrl(state));
  });

  app.get('/auth/callback', async (req, res) => {
    const { code, state } = req.query;
    if (!code || state !== req.session.oauthState)
      return res.status(400).send('Invalid OAuth state. Please <a href="/auth/login">try again</a>.');
    delete req.session.oauthState;

    try {
      const tokens = await exchangeCode(code);
      const user   = await resolveUser(tokens.access_token);

      if (user.role === 'none')
        return res.status(403).send(
          `<p>Access denied. <strong>${user.charName}</strong> is not a SONS of BANE member.</p>` +
          `<p><a href="/auth/login">Try a different character</a></p>`
        );

      req.session.user = user;
      res.redirect('/');
    } catch (e) {
      res.status(500).send(`Authentication failed: ${e.message}. <a href="/auth/login">Retry</a>`);
    }
  });

  app.get('/auth/logout', (req, res) => {
    req.session.destroy(() => res.redirect('/'));
  });

  app.get('/auth/me', (req, res) => {
    if (!req.session?.user) return res.json({ authenticated: false });
    res.json({ authenticated: true, ...req.session.user });
  });

};
