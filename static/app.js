// ── State ─────────────────────────────────────────────────────────────────────
let _corps       = [];
let _running     = false;
let _reportFile  = null;
let _ws          = null;
let _user        = null;
let _reportData  = null;
let _filteredRows = [];
let _sortState   = { col: 'totalFats', dir: -1 };
let _page = 0; const PAGE_SIZE = 100;

// ── Helpers ───────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function apiFetch(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) {
    logLine('[!] Session expired — redirecting to login…', 'gold');
    setTimeout(() => { window.location.href = '/auth/login'; }, 1500);
    return null;
  }
  return r;
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async function init() {
  const res  = await fetch('/auth/me');
  const user = await res.json();

  if (!user.authenticated) return; // login screen already visible

  document.getElementById('login-screen').style.display = 'none';
  _user = user;

  document.getElementById('user-info').innerHTML =
    `<strong style="color:var(--cyan)">${escHtml(user.charName)}</strong>` +
    `<span style="color:var(--grey);font-size:10px">${escHtml(user.corpName)}</span>` +
    `<span class="role-badge role-${user.role}">${user.role}</span>` +
    `<a href="/auth/logout" class="logout-link">logout</a>`;

  const sel = document.getElementById('year-select');
  const yr  = new Date().getFullYear();
  for (let y = yr; y >= yr - 4; y--) {
    const o = document.createElement('option'); o.value = y; o.textContent = y; sel.appendChild(o);
  }

  if (user.role !== 'admin') {
    document.getElementById('card-cache').style.display   = 'none';
    document.getElementById('btn-alliance').style.display = 'none';
  }
  if (user.role !== 'admin' || user.credFromEnv) {
    document.getElementById('card-creds').style.display = 'none';
  }

  if (user.role === 'admin') {
    if (user.credFromEnv) {
      setBadge('cred-status', '✓ Credentials loaded from environment variable', 'ok');
      document.getElementById('cred-fields').style.display = 'none';
    } else {
      apiFetch('/api/config/credentials').then(r => r && r.json()).then(d => {
        if (!d) return;
        setBadge('cred-status', d.configured ? '✓ Credentials loaded from Auth.env' : '⚠ No credentials saved — paste and save above', d.configured ? 'ok' : 'err');
      });
    }
    refreshCache();
  }
})();

// ── Credentials ───────────────────────────────────────────────────────────────
async function saveCredentials() {
  const sid  = document.getElementById('session-id').value.trim();
  const csrf = document.getElementById('csrf-token').value.trim();
  if (!sid || !csrf) { setBadge('cred-status', '! Both fields required', 'err'); return; }
  const r = await apiFetch('/api/config/credentials', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sid, csrf_token: csrf}),
  });
  if (!r) return;
  if (r.ok) {
    setBadge('cred-status', '✓ Saved to Auth.env', 'ok');
    logLine('[session] Credentials saved.', 'teal');
  } else {
    const e = await r.json();
    setBadge('cred-status', `! ${e.detail || 'Save failed'}`, 'err');
  }
}

// ── Corp list ─────────────────────────────────────────────────────────────────
async function loadCorps() {
  status('Loading corps from SONS of BANE…');
  logLine('[↓] Fetching alliance corp list…', 'cyan');
  try {
    const r = await apiFetch('/api/corps');
    if (!r) return;
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail); }
    _corps = await r.json();
    const sel = document.getElementById('corp-select');
    sel.innerHTML = '';

    let visible = _corps;
    if (_user?.role === 'member') {
      visible = _corps.filter(c => String(c.id) === String(_user.corpId));
      if (!visible.length) {
        logLine('[!] Your corporation is not in the alliance corp list — contact an officer.', 'red');
        status('Corp not found in alliance list.'); return;
      }
    }

    visible.forEach(c => {
      const o = document.createElement('option'); o.value = JSON.stringify(c); o.textContent = c.name; sel.appendChild(o);
    });
    logLine(`[✓] Found ${_corps.length} corps in SONS of BANE.`, 'green');
    visible.forEach(c => logLine(`    ${c.name}  (${c.id})`, 'grey'));
    status(`Loaded ${visible.length} corp(s).`);
  } catch(e) {
    logLine(`[!] ${e.message}`, 'red'); status('Failed to load corps.');
  }
}

// ── Audit runners ─────────────────────────────────────────────────────────────

// Reads the optional AFAT CSV and returns { pilotName: fatCount } or null.
async function readFatCsv() {
  const fileInput = document.getElementById('fat-csv');
  if (!fileInput.files.length) return null;
  const text = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = e => resolve(e.target.result);
    reader.onerror = () => reject(new Error('Failed to read CSV'));
    reader.readAsText(fileInput.files[0]);
  });
  const lines = text.trim().split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return null;
  const headers = lines[0].split(',').map(h => h.trim());
  const accIdx  = headers.indexOf('Account');
  const totIdx  = headers.indexOf('Total');
  if (accIdx === -1 || totIdx === -1) return null;
  const result = {};
  for (const line of lines.slice(1)) {
    const vals = line.split(',');
    const name = (vals[accIdx] || '').trim();
    const tot  = parseInt(vals[totIdx]) || 0;
    if (name) result[name] = tot;
  }
  const count = Object.keys(result).length;
  if (count) logLine(`[csv] Loaded FAT data for ${count} pilots from ${fileInput.files[0].name}`, 'teal');
  return count ? result : null;
}

async function runCorp() {
  if (_running) return;
  const sel = document.getElementById('corp-select');
  if (!sel.value) { logLine('[!] No corp selected — click ⟳ to load corps first.', 'gold'); return; }
  const corp = JSON.parse(sel.value);
  const year = parseInt(document.getElementById('year-select').value);

  showTab('log');
  logDivider();
  logLine(`[▶] Corp audit: ${corp.name}  (${year})`, 'cyan');

  const csvFats = await readFatCsv().catch(() => null);
  const r = await apiFetch('/api/audit/corp', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({corp_id: corp.id, corp_name: corp.name, year, csvFats}),
  });
  if (!r) return;
  if (!r.ok) { const e = await r.json(); logLine(`[!] ${e.detail}`, 'red'); return; }
  const {job_id} = await r.json();
  connectWs(job_id);
}

async function runAlliance() {
  if (_running) return;
  const year = parseInt(document.getElementById('year-select').value);

  showTab('log');
  logDivider();
  logLine(`[★] Alliance-wide audit  (${year})`, 'gold');

  const csvFats = await readFatCsv().catch(() => null);
  const r = await apiFetch('/api/audit/alliance', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({year, csvFats}),
  });
  if (!r) return;
  if (!r.ok) { const e = await r.json(); logLine(`[!] ${e.detail}`, 'red'); return; }
  const {job_id} = await r.json();
  connectWs(job_id);
}

async function runCsvImport() {
  if (_running) return;
  const fileInput  = document.getElementById('csv-file');
  const reportName = document.getElementById('csv-report-name').value.trim() || 'Fleet Activity';
  if (!fileInput.files.length) {
    logLine('[!] No CSV file selected — click "Choose File" above.', 'gold'); return;
  }
  const file = fileInput.files[0];
  let text;
  try {
    text = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = e => resolve(e.target.result);
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsText(file);
    });
  } catch (e) { logLine(`[!] ${e.message}`, 'red'); return; }

  showTab('log');
  logDivider();
  logLine(`[▶] CSV import: ${reportName}  (${file.name})`, 'teal');

  const r = await apiFetch('/api/audit/csv', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ csv: text, reportName }),
  });
  if (!r) return;
  if (!r.ok) { const e = await r.json(); logLine(`[!] ${e.detail}`, 'red'); return; }
  const {job_id} = await r.json();
  connectWs(job_id);
}

// ── WebSocket progress ────────────────────────────────────────────────────────
function connectWs(jobId) {
  setRunning(true); hideDownload();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/${jobId}`);

  _ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.done) {
      setRunning(false);
      if (msg.file) {
        showDownload(msg.file);
        loadReport(msg.file);
      }
      if (_user?.role === 'admin') refreshCache();
      return;
    }
    if (msg.msg) logLine(msg.msg, msg.tag || 'white');
  };
  _ws.onerror = () => { logLine('[!] WebSocket error.', 'red'); setRunning(false); };
  _ws.onclose = () => { if (_running) setRunning(false); };
}

// ── Download ──────────────────────────────────────────────────────────────────
function showDownload(filename) {
  _reportFile = filename;
  document.getElementById('download-label').textContent = `Report ready: ${filename}`;
  document.getElementById('download-bar').classList.add('visible');
}
function hideDownload() {
  _reportFile = null;
  document.getElementById('download-bar').classList.remove('visible');
}
function downloadReport() {
  if (_reportFile) window.open(`/api/reports/${encodeURIComponent(_reportFile)}`);
}

// ── Cache ─────────────────────────────────────────────────────────────────────
async function refreshCache() {
  const r = await apiFetch('/api/cache/stats');
  if (!r) return;
  const s = await r.json();
  const el = document.getElementById('cache-stats');
  el.textContent = s.count === 0 ? 'Cache empty' : `${s.count} entries · ${s.size_kb} KB\nOldest: ${s.oldest} · Newest: ${s.newest}`;
}
async function clearCache() {
  const r = await apiFetch('/api/cache/clear', {method: 'DELETE'});
  if (!r) return;
  const s = await r.json();
  logLine(`[🗑] Cache cleared — ${s.cleared} entries removed.`, 'gold');
  refreshCache();
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function showTab(name) {
  document.getElementById('view-log').style.display    = name === 'log'    ? 'flex' : 'none';
  document.getElementById('view-report').style.display = name === 'report' ? 'flex' : 'none';
  document.getElementById('tab-btn-log').classList.toggle('active',    name === 'log');
  document.getElementById('tab-btn-report').classList.toggle('active', name === 'report');
}

// ── Report: load & render ─────────────────────────────────────────────────────
async function loadReport(pdfFile) {
  const r = await apiFetch(`/api/reports/${encodeURIComponent(pdfFile)}/data`);
  if (!r || !r.ok) return;
  _reportData = await r.json();
  _sortState  = { col: 'totalFats', dir: -1 };
  _page = 0;
  document.getElementById('rpt-filter').value = '';
  document.getElementById('rpt-rating').value = '';

  const corpSel = document.getElementById('rpt-corp');
  if (_reportData.type === 'alliance') {
    corpSel.style.display = '';
    corpSel.innerHTML = '<option value="">All Corps</option>';
    _reportData.corps.forEach(c => {
      const o = document.createElement('option'); o.value = c.name; o.textContent = c.name; corpSel.appendChild(o);
    });
  } else {
    corpSel.style.display = 'none';
  }

  filterReport();
  showTab('report');
}

function filterReport() {
  if (!_reportData) return;
  const nameF   = document.getElementById('rpt-filter').value.toLowerCase();
  const ratingF = document.getElementById('rpt-rating').value;
  const corpF   = document.getElementById('rpt-corp').value;

  let members = _reportData.type === 'alliance'
    ? _reportData.corps.flatMap(c => c.members.map(m => ({ ...m, _corp: c.name })))
    : _reportData.members;

  if (corpF)   members = members.filter(m => m._corp === corpF);
  if (nameF)   members = members.filter(m => m.name.toLowerCase().includes(nameF));
  if (ratingF) members = members.filter(m => tierLabel(m.totalFats) === ratingF);

  _filteredRows = members;
  _page = 0;
  applySort();
}

function applySort() {
  const { col, dir } = _sortState;
  _filteredRows = [..._filteredRows].sort((a, b) => {
    let av, bv;
    if (col && col.startsWith('ft:')) {
      const k = col.slice(3);
      av = a.fleetTypes?.[k] ?? 0;
      bv = b.fleetTypes?.[k] ?? 0;
    } else {
      // month keys (e.g. "2026-Jan") live in fatsByMonth, not on the row directly
      av = col in a ? (a[col] ?? '') : (a.fatsByMonth?.[col] ?? 0);
      bv = col in b ? (b[col] ?? '') : (b.fatsByMonth?.[col] ?? 0);
    }
    if (typeof av === 'string') return dir * av.toLowerCase().localeCompare(bv.toLowerCase());
    return dir * (av - bv);
  });
  buildTableHeaders();
  renderTableBody();
}

function sortBy(col) {
  _sortState = (_sortState.col === col)
    ? { col, dir: _sortState.dir === -1 ? 1 : -1 }
    : { col, dir: -1 };
  applySort();
}

function changePage(dir) {
  const maxPage = Math.max(0, Math.ceil(_filteredRows.length / PAGE_SIZE) - 1);
  _page = Math.max(0, Math.min(maxPage, _page + dir));
  renderTableBody();
}

// ── Report: build headers ─────────────────────────────────────────────────────
function buildTableHeaders() {
  if (!_reportData) return;

  let cols;
  if (_reportData.type === 'csv') {
    cols = [
      { label: '#',          key: null,                      sort: false },
      { label: 'PILOT',      key: 'name',                    sort: true  },
      { label: 'TOTAL',      key: 'totalFats',               sort: true  },
      { label: 'STRATEGIC',  key: 'ft:STRATEGIC',            sort: true  },
      { label: 'SIG/SQUAD',  key: 'ft:SIG/SQUAD',           sort: true  },
      { label: 'SIG STR',    key: 'ft:SIG/SQUAD Strategic',  sort: true  },
      { label: 'PEACETIME',  key: 'ft:PEACETIME',            sort: true  },
      { label: 'CORP',       key: 'ft:Corp',                 sort: true  },
      { label: 'SCOUTS',     key: 'ft:SCOUTS',               sort: true  },
      { label: 'INCURSION',  key: 'incursion',               sort: true  },
      { label: 'BEEHIVE',    key: 'ft:Beehive',              sort: true  },
      { label: 'TOP SHIP',   key: 'topShip',                 sort: true  },
      { label: 'RATING',     key: null,                      sort: false },
    ];
  } else {
    const year   = _reportData.year;
    const months = getMonths(year);
    cols = [
      { label: '#',           key: null,             sort: false },
      { label: 'PILOT NAME',  key: 'name',           sort: true  },
      { label: 'ASSET BASE',  key: 'topAssetSystem', sort: true  },
    ];
    if (_reportData.type === 'alliance')
      cols.push({ label: 'CORPORATION', key: '_corp', sort: true });
    const hasCsv = getHasCsv();
    cols.push(
      { label: 'CORP JOINED',  key: 'joinDate',   sort: true  },
      { label: 'IN ALLIANCE',  key: 'timeInCorp', sort: false },
      { label: 'ALTS',         key: 'altCount',   sort: true  },
      { label: 'LAST LOGIN',   key: 'lastLogin',  sort: true  },
      { label: 'TOTAL FATs',   key: 'totalFats',  sort: true  },
      ...months.map(mo => ({ label: mo.label, key: mo.key, sort: true })),
      { label: 'RATING',       key: null,         sort: false },
      ...(hasCsv ? [{ label: 'Loaded Imperium PAPs', key: 'csvFat', sort: true }] : []),
    );
  }

  const thead = document.getElementById('rt-head');
  thead.innerHTML = '';
  const tr = document.createElement('tr');
  cols.forEach(c => {
    const th = document.createElement('th');
    if (c.sort) {
      th.className = 'sortable';
      if (_sortState.col === c.key)
        th.className += _sortState.dir === -1 ? ' s-desc' : ' s-asc';
      th.onclick = () => sortBy(c.key);
    }
    th.innerHTML = escHtml(c.label) + (c.sort ? '<span class="sa"></span>' : '');
    tr.appendChild(th);
  });
  thead.appendChild(tr);
}

// ── Report: render body ───────────────────────────────────────────────────────
function renderTableBody() {
  if (!_reportData) return;
  const tbody = document.getElementById('rt-body');
  tbody.innerHTML = '';

  const pageRows = _filteredRows.slice(_page * PAGE_SIZE, (_page + 1) * PAGE_SIZE);

  if (_reportData.type === 'csv') {
    pageRows.forEach((m, i) => {
      const [tier, cls] = tierInfo(m.totalFats);
      const tr = document.createElement('tr');
      const ft = m.fleetTypes || {};
      const ftv = (key, color) => {
        const n = ft[key] || 0;
        return td(n || '—', 'center', n ? color : '#8B949E');
      };
      const incurs = (ft['Incursion-HQ'] || 0) + (ft['Incursion-VG'] || 0);
      const cells = [
        td(_page * PAGE_SIZE + i + 1, 'center', '#8B949E'),
        td(m.name,          'left',   '#FFFFFF', true),
        td(m.totalFats,     'center', fatColor(m.totalFats), true),
        ftv('STRATEGIC',            '#00E5CC'),
        ftv('SIG/SQUAD',            '#00BFFF'),
        ftv('SIG/SQUAD Strategic',  '#00BFFF'),
        ftv('PEACETIME',            '#27AE60'),
        ftv('Corp',                 '#27AE60'),
        ftv('SCOUTS',               '#27AE60'),
        td(incurs || '—',   'center', incurs ? '#FFD700' : '#8B949E'),
        ftv('Beehive',              '#27AE60'),
        td(m.topShip || '—', 'left', '#8B949E'),
      ];
      const ratingTd = document.createElement('td');
      ratingTd.style.textAlign = 'center';
      const badge = document.createElement('span');
      badge.className = `rt-badge rt-${cls}`;
      badge.textContent = tier;
      ratingTd.appendChild(badge);
      cells.forEach(c => tr.appendChild(c));
      tr.appendChild(ratingTd);
      tbody.appendChild(tr);
    });
  } else {
    const year   = _reportData.year;
    const months = getMonths(year);

    pageRows.forEach((m, i) => {
      const [tier, cls] = tierInfo(m.totalFats);
      const tr = document.createElement('tr');

      const cells = [
        td(_page * PAGE_SIZE + i + 1, 'center', '#8B949E'),
        td(m.name,                  'left',   '#FFFFFF', true),
        td(m.topAssetSystem || '—', 'left',   m.topAssetSystem ? '#27AE60' : '#8B949E'),
      ];
      if (_reportData.type === 'alliance')
        cells.push(td(m._corp || '—', 'left', '#8B949E'));

      cells.push(
        td(m.joinDate   || '—',            'center', '#8B949E'),
        td(m.timeInCorp || m.born || '—', 'center', '#8B949E'),
        td(m.altCount != null ? m.altCount : 0, 'center',
           m.altCount > 0 ? '#00E5CC' : '#8B949E'),
        td(m.lastLogin  || '—',            'center', '#8B949E'),
        td(m.totalFats,                    'center', fatColor(m.totalFats), true),
        ...months.map(mo => {
          const n = m.fatsByMonth?.[mo.key] || 0;
          return td(n || '—', 'center', n ? '#00E5CC' : '#8B949E');
        }),
      );

      const ratingTd = document.createElement('td');
      ratingTd.style.textAlign = 'center';
      const badge = document.createElement('span');
      badge.className = `rt-badge rt-${cls}`;
      badge.textContent = tier;
      ratingTd.appendChild(badge);
      cells.forEach(c => tr.appendChild(c));
      tr.appendChild(ratingTd);
      if (getHasCsv()) tr.appendChild(td(
        m.csvFat != null ? m.csvFat : '—', 'center',
        m.csvFat > 0 ? '#FFD700' : '#8B949E', m.csvFat > 0,
      ));
      tbody.appendChild(tr);
    });
  }

  // Summary bar
  const n      = _filteredRows.length;
  const total  = _reportData.type === 'alliance'
    ? _reportData.corps.reduce((s, c) => s + c.members.length, 0)
    : _reportData.members.length;
  const active = _filteredRows.filter(m => m.totalFats > 0).length;
  const elite  = _filteredRows.filter(m => m.totalFats >= 8).length;
  const ghost  = _filteredRows.filter(m => m.totalFats === 0).length;
  const pct    = n ? Math.round(active / n * 100) : 0;
  document.getElementById('rpt-summary').textContent =
    `${n}${n !== total ? ' / ' + total : ''} pilots  ·  ${pct}% participation  ·  ★${elite}  ○${ghost}`;

  // Pagination controls
  const totalPages = Math.max(1, Math.ceil(_filteredRows.length / PAGE_SIZE));
  const pagesDiv  = document.getElementById('rpt-pages');
  const pageLabel = document.getElementById('rpt-page-label');
  if (totalPages > 1) {
    pagesDiv.style.display = 'flex';
    pageLabel.textContent  = `${_page + 1} / ${totalPages}`;
    document.getElementById('btn-prev').disabled = _page === 0;
    document.getElementById('btn-next').disabled = _page >= totalPages - 1;
  } else {
    pagesDiv.style.display = 'none';
  }
}

// ── Report helpers ────────────────────────────────────────────────────────────
function td(text, align, color, bold = false) {
  const el = document.createElement('td');
  el.textContent = text;
  el.style.textAlign = align;
  el.style.color     = color;
  if (bold) el.style.fontWeight = 'bold';
  return el;
}

function getHasCsv() {
  if (!_reportData) return false;
  const members = _reportData.type === 'alliance'
    ? _reportData.corps.flatMap(c => c.members)
    : (_reportData.members || []);
  return members.some(m => m.csvFat != null);
}

function getMonths(year) {
  const now   = new Date();
  const maxM  = year === now.getFullYear() ? now.getMonth() + 1 : 12;
  const abbrs = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return abbrs.slice(0, maxM).map(m => ({ key: `${year}-${m}`, label: `${m} '${String(year).slice(2)}` }));
}

function tierLabel(n) {
  if (n >= 8) return 'ELITE';
  if (n >= 4) return 'ACTIVE';
  if (n >= 1) return 'PARTIAL';
  return 'GHOST';
}

function tierInfo(n) {
  if (n >= 8) return ['★ ELITE',   'elite'];
  if (n >= 4) return ['◆ ACTIVE',  'active'];
  if (n >= 1) return ['▷ PARTIAL', 'partial'];
  return            ['○ GHOST',   'ghost'];
}

function fatColor(n) {
  if (n >= 8) return '#00E5CC';
  if (n >= 4) return '#27AE60';
  if (n >= 1) return '#FFD700';
  return '#C0392B';
}

// ── Log helpers ───────────────────────────────────────────────────────────────
function logLine(text, tag) {
  const el = document.getElementById('log');
  const span = document.createElement('span');
  span.className = tag ? `t-${tag}` : 't-white';
  span.textContent = text + '\n';
  el.appendChild(span);
  el.scrollTop = el.scrollHeight;
}
function logDivider() { logLine('─'.repeat(56), 'grey'); }
function clearLog()   { document.getElementById('log').innerHTML = ''; }

// ── UI state ──────────────────────────────────────────────────────────────────
function setRunning(state) {
  _running = state;
  document.getElementById('btn-corp').disabled     = state;
  document.getElementById('btn-alliance').disabled = state;
  document.getElementById('btn-csv').disabled      = state;
  status(state ? '⏳ Processing — see log for progress…' : 'Done.');
}
function status(msg) { document.getElementById('statusbar').textContent = msg; }
function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = `status-badge ${cls || ''}`;
}
