'use strict';

const fs   = require('fs');
const path = require('path');
const { ENV_FILE } = require('../config');

module.exports = (app) => {

  app.get('/api/config/credentials', (req, res) => {
    if (!fs.existsSync(ENV_FILE)) return res.json({ configured: false });
    try {
      const text = fs.readFileSync(ENV_FILE, 'utf8');
      const ok   = /sessionid=\S+/.test(text) && /csrftoken=\S+/.test(text);
      res.json({ configured: ok });
    } catch {
      res.json({ configured: false });
    }
  });

  app.post('/api/config/credentials', (req, res) => {
    const { session_id, csrf_token } = req.body;
    if (!session_id || !csrf_token)
      return res.status(400).json({ detail: 'Both session_id and csrf_token are required.' });
    const cookie = `sessionid=${session_id}; csrftoken=${csrf_token}`;
    fs.writeFileSync(
      ENV_FILE,
      `# Saved by SoB Audit web UI on ${new Date().toISOString().slice(0, 10)}\n` +
      `SESSION_COOKIE="${cookie}"\n`,
    );
    res.json({ ok: true });
  });

};
