'use strict';

const crypto = require('crypto');
const fs     = require('fs');
const path   = require('path');

const { collectCorp, collectAlliance } = require('../audit');
const { REPORTS_DIR, ENV_FILE, MONTH_ABBRS } = require('../config');
const { AllianceAuthProvider, ESIProvider, EXTRA_PROVIDERS } = require('../providers');
const { buildCorpPdf, buildAlliancePdf, buildCsvPdf } = require('../report/pdf');
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

// ── CSV helpers ───────────────────────────────────────────────────────────────

const CSV_FLEET_TYPES = [
  '*IGC', '*TNT', 'Beehive', 'Corp', 'Cricket', 'GSOL',
  'Incursion-HQ', 'Incursion-VG', 'Locust', 'PEACETIME', 'SCOUTS',
  'SIG/SQUAD', 'SIG/SQUAD Strategic', 'STRATEGIC', 'Survey',
];

const CSV_SHIP_TYPES = [
  'Assault Frigate', 'Attack Battlecruiser', 'Battleship', 'Black Ops',
  'Blockade Runner', 'Capital Industrial Ship', 'Capsule', 'Carrier',
  'Combat Battlecruiser', 'Combat Recon Ship', 'Command Destroyer',
  'Command Ship', 'Corvette', 'Cruiser', 'Deep Space Transport',
  'Destroyer', 'Dreadnought', 'Electronic Attack Ship', 'Exhumer',
  'Force Auxiliary', 'Force Recon Ship', 'Frigate', 'Hauler',
  'Heavy Assault Cruiser', 'Heavy Interdiction Cruiser', 'Interceptor',
  'Interdictor', 'Jump Freighter', 'Logistics', 'Logistics Frigate',
  'Marauder', 'Shuttle', 'Stealth Bomber', 'Strategic Cruiser',
  'Supercarrier', 'Tactical Destroyer', 'Titan',
];

function parseCsvText(text) {
  const lines = text.trim().split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim());
  return lines.slice(1).map(line => {
    const vals = line.split(',').map(v => v.trim());
    const row  = {};
    headers.forEach((h, i) => { row[h] = vals[i] || ''; });
    return row;
  });
}

function csvRowToMember(row) {
  const name = (row['Account'] || '').trim();
  if (!name) return null;
  const totalFats  = parseInt(row['Total']) || 0;
  const fleetTypes = {};
  for (const ft of CSV_FLEET_TYPES) fleetTypes[ft] = parseInt(row[ft]) || 0;
  let topShip = '—', topN = 0;
  for (const st of CSV_SHIP_TYPES) {
    const n = parseInt(row[st]) || 0;
    if (n > topN) { topN = n; topShip = st; }
  }
  const incursion = (fleetTypes['Incursion-HQ'] || 0) + (fleetTypes['Incursion-VG'] || 0);
  return { name, totalFats, fleetTypes, incursion, topShip };
}

// Overlay CSV FAT totals onto the current month for any matching pilot.
// Only applied when the audit year matches the current calendar year.
function applyCsvFats(members, csvFats, year, log) {
  if (!csvFats || !Object.keys(csvFats).length) return;
  const today = new Date();
  if (year !== today.getFullYear()) return;
  const monthKey = `${year}-${MONTH_ABBRS[today.getMonth()]}`;
  let applied = 0;
  for (const ch of members) {
    const csvCount = csvFats[ch.name];
    if (csvCount === undefined) continue;
    const old = ch.fatsByMonth[monthKey] || 0;
    ch.fatsByMonth[monthKey] = csvCount;
    const diff = csvCount - old;
    ch.fatsByYear[year] = (ch.fatsByYear[year] || 0) + diff;
    ch.totalFats = Object.values(ch.fatsByYear).reduce((a, b) => a + b, 0);
    applied++;
  }
  if (applied) log(`      applied CSV FAT data for ${applied} pilots (${monthKey})`, 'teal');
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
    const { corp_id, corp_name, year = new Date().getFullYear(), csvFats } = req.body;
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
        applyCsvFats(corp.members, csvFats, year, log);
        const fname = `sob_corp_${safeFilename(corp_name)}_${today()}.pdf`;
        await Promise.all([
          buildCorpPdf(corp_name, corp.members, year, path.join(REPORTS_DIR, fname)),
          fs.promises.writeFile(
            path.join(REPORTS_DIR, fname.replace('.pdf', '.json')),
            JSON.stringify({ type: 'corp', corpName: corp_name, year, generatedAt: new Date().toISOString(), members: corp.members }),
          ),
        ]);
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
    const { year = new Date().getFullYear(), csvFats } = req.body;

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
        for (const corp of corps) applyCsvFats(corp.members, csvFats, year, log);
        const fname = `sob_alliance_${today()}.pdf`;
        const total = corps.reduce((s, c) => s + c.members.length, 0);
        await Promise.all([
          buildAlliancePdf(corps, year, path.join(REPORTS_DIR, fname)),
          fs.promises.writeFile(
            path.join(REPORTS_DIR, fname.replace('.pdf', '.json')),
            JSON.stringify({ type: 'alliance', year, generatedAt: new Date().toISOString(), corps: corps.map(c => ({ corpId: c.corpId, name: c.name, members: c.members })) }),
          ),
        ]);
        job.resultFile = fname;
        log(`[★] Alliance report ready: ${fname}  (${corps.length} corps, ${total} mains)`, 'gold');
      } catch (e) {
        log(`[!] ${e.message}`, 'red');
      } finally {
        job.done = true;
      }
    })();
  });

  // ── REST: CSV fleet-activity import ────────────────────────────────────────
  app.post('/api/audit/csv', requireMember, (req, res) => {
    const { csv: csvText, reportName = 'Fleet Activity' } = req.body;
    if (!csvText || typeof csvText !== 'string')
      return res.status(400).json({ detail: 'No CSV data provided.' });
    const rows = parseCsvText(csvText);
    if (!rows.length) return res.status(400).json({ detail: 'CSV has no data rows.' });
    const members = rows.map(csvRowToMember).filter(Boolean);
    if (!members.length) return res.status(400).json({ detail: 'No valid members in CSV.' });

    const jobId = createJob();
    const job   = jobs.get(jobId);
    res.json({ job_id: jobId });

    fs.mkdirSync(REPORTS_DIR, { recursive: true });
    (async () => {
      const log = (msg, tag = 'white') => job.messages.push({ msg, tag });
      try {
        const fname = `sob_csv_${safeFilename(reportName)}_${today()}.pdf`;
        log(`[▶] Building CSV report: ${reportName}  (${members.length} pilots)…`, 'cyan');
        await Promise.all([
          buildCsvPdf(reportName, members, path.join(REPORTS_DIR, fname)),
          fs.promises.writeFile(
            path.join(REPORTS_DIR, fname.replace('.pdf', '.json')),
            JSON.stringify({ type: 'csv', reportName, generatedAt: new Date().toISOString(), members }),
          ),
        ]);
        job.resultFile = fname;
        log(`[✓] Report ready: ${fname}`, 'green');
      } catch (e) {
        log(`[!] ${e.message}`, 'red');
      } finally {
        job.done = true;
      }
    })();
  });

  // ── REST: report data (JSON for in-app viewer) ─────────────────────────────
  app.get('/api/reports/:filename/data', requireMember, (req, res) => {
    const fname = req.params.filename;
    if (!fname.endsWith('.pdf') || fname.includes('..'))
      return res.status(400).json({ detail: 'Invalid filename.' });
    const jsonPath = path.join(REPORTS_DIR, fname.replace('.pdf', '.json'));
    if (!fs.existsSync(jsonPath)) return res.status(404).json({ detail: 'Report data not found.' });
    res.sendFile(jsonPath);
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
