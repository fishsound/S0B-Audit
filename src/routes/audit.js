'use strict';

const crypto = require('crypto');
const fs     = require('fs');
const path   = require('path');

const { collectCorp, collectAlliance } = require('../audit');
const { REPORTS_DIR, ENV_FILE }        = require('../config');
const { AllianceAuthProvider, ESIProvider, EXTRA_PROVIDERS } = require('../providers');
const { buildCorpPdf, buildAlliancePdf } = require('../report/pdf');
const { loadCredentials } = require('../utils');
const { requireMember, requireAdmin } = require('../middleware');

// ── Job registry ──────────────────────────────────────────────────────────────
// Each job: { messages: [], done: false, resultFile: null }
const jobs = new Map();

function createJob() {
  const jobId = crypto.randomBytes(4).toString('hex');
  jobs.set(jobId, { messages: [], done: false, resultFile: null });
  return jobId;
}

function safeFilename(s) {
  return (s || 'report').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_|_$/g, '').toLowerCase();
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

module.exports = (app) => {

  // ── REST: list corps ────────────────────────────────────────────────────────
  app.get('/api/corps', requireMember, async (req, res) => {
    try {
      const { sessionId, csrfToken } = loadCredentials(ENV_FILE);
      const auth  = new AllianceAuthProvider(sessionId, csrfToken);
      const now   = new Date();
      const corps = await auth.listAllianceCorps(now.getFullYear(), now.getMonth() + 1);
      res.json(corps.map(([id, name]) => ({ id, name })));
    } catch (e) {
      res.status(e.message.includes('Credentials') ? 401 : 502).json({ detail: e.message });
    }
  });

  // ── REST: start corp audit ──────────────────────────────────────────────────
  app.post('/api/audit/corp', requireMember, async (req, res) => {
    const { corp_id, corp_name, year = new Date().getFullYear() } = req.body;
    if (!corp_id || !corp_name)
      return res.status(400).json({ detail: 'corp_id and corp_name are required.' });

    // Members can only audit their own corporation
    const user = req.session.user;
    if (user.role === 'member' && String(corp_id) !== String(user.corpId))
      return res.status(403).json({ detail: 'Members can only audit their own corporation.' });

    let auth, esi;
    try {
      const { sessionId, csrfToken } = loadCredentials(ENV_FILE);
      auth = new AllianceAuthProvider(sessionId, csrfToken);
      esi  = new ESIProvider();
    } catch (e) {
      return res.status(401).json({ detail: e.message });
    }

    const jobId = createJob();
    const job   = jobs.get(jobId);
    res.json({ job_id: jobId });

    // Run async — messages accumulate; WS drains them
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
    (async () => {
      const log = (msg, tag = 'white') => job.messages.push({ msg, tag });
      try {
        const corp  = await collectCorp(auth, esi, EXTRA_PROVIDERS, corp_id, corp_name, year, log);
        const fname = `sob_corp_${safeFilename(corp_name)}_${today()}.pdf`;
        await buildCorpPdf(corp_name, corp.members, year, path.join(REPORTS_DIR, fname));
        job.resultFile = fname;
        log(`[✓] Report ready: ${fname}`, 'green');
      } catch (e) {
        log(`[!] ${e.message}`, 'red');
      } finally {
        job.done = true;
      }
    })();
  });

  // ── REST: start alliance audit ──────────────────────────────────────────────
  app.post('/api/audit/alliance', requireAdmin, async (req, res) => {
    const { year = new Date().getFullYear() } = req.body;

    let auth, esi;
    try {
      const { sessionId, csrfToken } = loadCredentials(ENV_FILE);
      auth = new AllianceAuthProvider(sessionId, csrfToken);
      esi  = new ESIProvider();
    } catch (e) {
      return res.status(401).json({ detail: e.message });
    }

    const jobId = createJob();
    const job   = jobs.get(jobId);
    res.json({ job_id: jobId });

    fs.mkdirSync(REPORTS_DIR, { recursive: true });
    (async () => {
      const log = (msg, tag = 'white') => job.messages.push({ msg, tag });
      try {
        const corps = await collectAlliance(auth, esi, EXTRA_PROVIDERS, year, log);
        const fname = `sob_alliance_${today()}.pdf`;
        await buildAlliancePdf(corps, year, path.join(REPORTS_DIR, fname));
        job.resultFile = fname;
        const total = corps.reduce((s, c) => s + c.members.length, 0);
        log(`[★] Alliance report ready: ${fname}  (${corps.length} corps, ${total} mains)`, 'gold');
      } catch (e) {
        log(`[!] ${e.message}`, 'red');
      } finally {
        job.done = true;
      }
    })();
  });

  // ── REST: download report ───────────────────────────────────────────────────
  app.get('/api/reports/:filename', requireMember, (req, res) => {
    const fname = req.params.filename;
    if (!fname.endsWith('.pdf') || fname.includes('..'))
      return res.status(400).json({ detail: 'Invalid filename.' });
    const p = path.join(REPORTS_DIR, fname);
    if (!fs.existsSync(p)) return res.status(404).json({ detail: 'Report not found.' });
    res.download(p, fname);
  });

  // ── WebSocket: stream job progress ─────────────────────────────────────────
  app.ws('/ws/:jobId', (ws, req) => {
    const job = jobs.get(req.params.jobId);
    if (!job) {
      ws.send(JSON.stringify({ msg: 'Job not found.', tag: 'red' }));
      ws.close();
      return;
    }

    let idx = 0;
    const poll = setInterval(() => {
      // Drain buffered messages
      while (idx < job.messages.length) {
        try { ws.send(JSON.stringify(job.messages[idx])); } catch {}
        idx++;
      }
      if (job.done) {
        clearInterval(poll);
        try { ws.send(JSON.stringify({ done: true, file: job.resultFile })); } catch {}
        ws.close();
        jobs.delete(req.params.jobId);
      }
    }, 50);

    ws.on('close', () => clearInterval(poll));
    ws.on('error', () => clearInterval(poll));
  });

};
