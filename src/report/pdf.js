'use strict';

const fs      = require('fs');
const path    = require('path');
const PDFDoc  = require('pdfkit');
const { MONTH_ABBRS } = require('../config');

// DejaVu Sans has full Unicode coverage (◈ ★ ◆ ▷ ○ etc.).
// Helvetica (built-in) only covers WinAnsi and silently corrupts those glyphs.
// Fonts are bundled in src/fonts/ so they're available on any deployment target.
const FONT      = 'DejaVuSans';
const FONT_BOLD = 'DejaVuSans-Bold';
const FONT_PATH      = path.join(__dirname, '../fonts/DejaVuSans.ttf');
const FONT_BOLD_PATH = path.join(__dirname, '../fonts/DejaVuSans-Bold.ttf');

// ── Palette ───────────────────────────────────────────────────────────────────
const C = {
  BG_DARK:   '#0D1117',
  BG_MID:    '#161B22',
  BG_LIGHT:  '#1F2937',
  CYAN:      '#00BFFF',
  TEAL:      '#00E5CC',
  GOLD:      '#FFD700',
  RED:       '#C0392B',
  GREEN:     '#27AE60',
  GREY:      '#8B949E',
  WHITE:     '#FFFFFF',
  HEADER_BG: '#0A3D62',
  BORDER:    '#2D3748',
};

const MARGIN      = 20;
const ROW_H       = 15;   // table row height (pt)
const HDR_H       = 18;   // header row height (pt)
const FONT_SIZE   = 7;
const TITLE_SIZE  = 20;
const SUB_SIZE    = 9;

// ── Helpers ───────────────────────────────────────────────────────────────────

function yearMonths(year) {
  const today = new Date();
  return MONTH_ABBRS.slice(0, year === today.getFullYear() ? today.getMonth() + 1 : 12);
}

function tierInfo(n) {
  if (n >= 8) return ['★ ELITE',   C.TEAL];
  if (n >= 4) return ['◆ ACTIVE',  C.GREEN];
  if (n >= 1) return ['▷ PARTIAL', C.GOLD];
  return            ['○ GHOST',   C.RED];
}

function fatColor(n) {
  if (n >= 8) return C.TEAL;
  if (n >= 4) return C.GREEN;
  if (n >= 1) return C.GOLD;
  return C.RED;
}

// ── Table drawing ─────────────────────────────────────────────────────────────
//
// Cell object: { text, color?, bold?, align? }  or bare string/number.
// Returns the new y after the last row.

function drawRow(doc, cells, colWidths, x, y, rowH, isHeader, rowIdx) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
  const bg = isHeader ? C.HEADER_BG : (rowIdx % 2 === 0 ? C.BG_MID : C.BG_LIGHT);

  doc.save().rect(x, y, totalW, rowH).fill(bg).restore();

  let cx = x;
  cells.forEach((cell, ci) => {
    const cw    = colWidths[ci];
    const text  = String(typeof cell === 'object' ? (cell.text ?? '') : (cell ?? ''));
    const color = (typeof cell === 'object' && cell.color) ? cell.color
                : isHeader ? C.CYAN : C.WHITE;
    const bold  = isHeader || (typeof cell === 'object' && cell.bold);
    const align = (typeof cell === 'object' && cell.align) ? cell.align : 'center';

    doc.save()
       .font(bold ? FONT_BOLD : FONT)
       .fontSize(FONT_SIZE)
       .fillColor(color)
       .text(text, cx + 2, y + Math.max(1, (rowH - FONT_SIZE) / 2), {
         width: cw - 4,
         align,
         lineBreak: false,
         ellipsis: true,
       })
       .restore();

    cx += cw;
  });

  // Bottom border
  doc.save()
     .moveTo(x, y + rowH).lineTo(x + totalW, y + rowH)
     .strokeColor(C.BORDER).lineWidth(0.3).stroke()
     .restore();

  return y + rowH;
}

function drawTable(doc, rows, colWidths, x, startY) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
  let y = startY;
  rows.forEach((row, ri) => {
    const h = ri === 0 ? HDR_H : ROW_H;
    // Auto page-break: if row won't fit, add a page and redraw header
    if (ri > 0 && y + h > doc.page.height - MARGIN) {
      doc.addPage();
      y = MARGIN;
      y = drawRow(doc, rows[0], colWidths, x, y, HDR_H, true, 0);
    }
    y = drawRow(doc, row, colWidths, x, y, h, ri === 0, ri);
  });

  // Right border
  doc.save()
     .moveTo(x + totalW, startY).lineTo(x + totalW, y)
     .strokeColor(C.BORDER).lineWidth(0.3).stroke()
     .restore();

  // Vertical separators
  let vx = x;
  colWidths.slice(0, -1).forEach(w => {
    vx += w;
    doc.save()
       .moveTo(vx, startY).lineTo(vx, y)
       .strokeColor(C.BORDER).lineWidth(0.3).stroke()
       .restore();
  });

  return y;
}

// ── Title / subtitle ─────────────────────────────────────────────────────────

function drawTitle(doc, title, subtitle, y) {
  const pw = doc.page.width;
  doc.save()
     .font(FONT_BOLD).fontSize(TITLE_SIZE).fillColor(C.CYAN)
     .text(title, MARGIN, y, { width: pw - 2 * MARGIN, align: 'center', lineBreak: false })
     .restore();
  y += TITLE_SIZE + 4;
  doc.save()
     .font(FONT).fontSize(SUB_SIZE).fillColor(C.GREY)
     .text(subtitle, MARGIN, y, { width: pw - 2 * MARGIN, align: 'center', lineBreak: false })
     .restore();
  return y + SUB_SIZE + 10;
}

// ── Column definitions ────────────────────────────────────────────────────────

function rosterCols(year) {
  // Landscape A4 usable width ≈ 802pt
  const usable  = 841.89 - 2 * MARGIN;
  const months  = yearMonths(year);
  // Fixed columns: #, name, joined, alliance, sp, login, sec, total, rating
  const fixed   = [14, 100, 57, 70, 33, 57, 27, 33, 42];
  const fixedW  = fixed.reduce((a, b) => a + b, 0);
  const moW     = Math.floor((usable - fixedW) / months.length);
  return { fixed, moW, months, usable };
}

function rosterHeader(year) {
  const { fixed, moW, months } = rosterCols(year);
  return [
    '#', 'PILOT NAME', 'CORP JOINED', 'IN ALLIANCE',
    'SP (M)', 'LAST LOGIN', 'SEC', 'FATs',
    ...months.map(m => `${m} '${String(year).slice(2)}`),
    'RATING',
  ];
}

function rosterColWidths(year) {
  const { fixed, moW, months } = rosterCols(year);
  return [...fixed.slice(0, -1), ...months.map(() => moW), fixed[fixed.length - 1]];
}

function rosterRow(ch, idx, year) {
  const [tier, tc] = tierInfo(ch.totalFats);
  const sp   = ch.skillpointsM ? `${ch.skillpointsM.toFixed(1)}` : '—';
  const spC  = ch.skillpointsM >= 80 ? C.TEAL : ch.skillpointsM >= 30 ? C.GOLD : C.WHITE;
  const secC = ch.secStatus < 0 ? C.RED : ch.secStatus < 2 ? C.GOLD : C.GREEN;
  const months = yearMonths(year);

  return [
    { text: idx + 1,      color: C.GREY,            align: 'center' },
    { text: ch.name,      color: C.WHITE, bold: true, align: 'left'  },
    { text: ch.joinDate  || '—', color: C.GREY,      align: 'center' },
    { text: ch.timeInCorp || ch.born || '—', color: C.GREY, align: 'center' },
    { text: sp,           color: spC,                align: 'center' },
    { text: ch.lastLogin || '—', color: C.GREY,      align: 'center' },
    { text: ch.secStatus.toFixed(1), color: secC,    align: 'center' },
    { text: ch.totalFats, color: fatColor(ch.totalFats), bold: true, align: 'center' },
    ...months.map(mo => {
      const n = ch.fatsByMonth[`${year}-${mo}`] || 0;
      return { text: n || '—', color: n ? C.TEAL : C.GREY, align: 'center' };
    }),
    { text: tier, color: tc, bold: true, align: 'center' },
  ];
}

// ── Summary stats table ───────────────────────────────────────────────────────

function summaryRows(members, year) {
  const n        = members.length;
  const anyFats  = members.filter(m => m.totalFats > 0).length;
  const ghosts   = n - anyFats;
  const total    = members.reduce((s, m) => s + m.totalFats, 0);
  const ytd      = members.reduce((s, m) => s + (m.fatsByYear[year] || 0), 0);
  const prev     = members.reduce((s, m) => s + (m.fatsByYear[year - 1] || 0), 0);
  const elite    = members.filter(m => m.totalFats >= 8).length;
  const active   = members.filter(m => m.totalFats >= 4 && m.totalFats < 8).length;
  const partial  = members.filter(m => m.totalFats >= 1 && m.totalFats < 4).length;
  const pct      = n ? `${Math.round(anyFats / n * 100)}%` : '—';

  const row = (label, value, vc = C.WHITE) => [
    { text: label, color: C.GREY, align: 'left' },
    { text: String(value), color: vc, bold: true, align: 'left' },
  ];

  return [
    ['METRIC', 'VALUE'],
    row('Total Mains',              n,       C.TEAL),
    row('FAT Participation Rate',   pct,     C.GOLD),
    row('Members with ANY FATs',    anyFats, C.GREEN),
    row('Ghost Members (0 FATs)',   ghosts,  C.RED),
    row('★ Elite (8+ FATs)',        elite,   C.TEAL),
    row('◆ Active (4–7 FATs)',      active,  C.GREEN),
    row('▷ Partial (1–3 FATs)',     partial, C.GOLD),
    row('Total FATs (3-yr window)', total,   C.TEAL),
    row(`FATs ${year - 1}`,         prev,    C.WHITE),
    row(`FATs ${year} YTD`,         ytd,     C.TEAL),
    row('Audit Date', new Date().toISOString().slice(0, 10), C.GREY),
  ];
}

// ── Document factory ──────────────────────────────────────────────────────────

function makePdf(outPath, title) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const doc = new PDFDoc({
    size: 'A4', layout: 'landscape', margin: MARGIN,
    info: { Title: title, Author: 'SoB Audit Tool', Creator: 'SoB-Audit-Tool/2.0' },
  });
  doc.registerFont(FONT,      FONT_PATH);
  doc.registerFont(FONT_BOLD, FONT_BOLD_PATH);
  doc.on('pageAdded', () => {
    doc.save().rect(0, 0, doc.page.width, doc.page.height).fill(C.BG_DARK).restore();
  });
  // Trigger background on first page
  doc.save().rect(0, 0, doc.page.width, doc.page.height).fill(C.BG_DARK).restore();
  return doc;
}

function pipeToFile(doc, outPath) {
  return new Promise((resolve, reject) => {
    const stream = fs.createWriteStream(outPath);
    doc.pipe(stream);
    stream.on('finish', () => resolve(outPath));
    stream.on('error', reject);
  });
}

// ── Corp report ───────────────────────────────────────────────────────────────

async function buildCorpPdf(corpName, members, year, outPath) {
  const sorted = [...members].sort((a, b) => b.totalFats - a.totalFats);
  const doc    = makePdf(outPath, `${corpName} — SoB Audit`);
  const pw     = doc.page.width;
  const finish = pipeToFile(doc, outPath);

  // ── Page 1: Summary ──────────────────────────────────────────────────────
  let y = MARGIN;
  y = drawTitle(doc,
    `◈  ${corpName.toUpperCase()}  ·  CORP AUDIT REPORT  ◈`,
    `Sons of Bane Alliance  ·  EVE Online  ·  Audit: ${new Date().toISOString().slice(0, 10)}  ·  ${sorted.length} Mains  ·  Year: ${year}`,
    y,
  );

  // Two-column layout
  const colGap  = 10;
  const leftW   = (pw - 2 * MARGIN) * 0.42;
  const rightW  = (pw - 2 * MARGIN) - leftW - colGap;
  const leftX   = MARGIN;
  const rightX  = MARGIN + leftW + colGap;

  // Left: stats table
  const statsW = [leftW * 0.62, leftW * 0.38];
  drawTable(doc, summaryRows(sorted, year), statsW, leftX, y);

  // Right: top 10 + ghosts
  let ry = y;
  const topRows = [
    ['PILOT', 'FATs', 'RATING'],
    ...sorted.slice(0, 10).map(m => {
      const [tier, tc] = tierInfo(m.totalFats);
      return [
        { text: m.name, align: 'left', bold: true },
        { text: m.totalFats, color: fatColor(m.totalFats), bold: true },
        { text: tier, color: tc },
      ];
    }),
  ];
  const topW = [rightW * 0.55, rightW * 0.2, rightW * 0.25];
  ry = drawTable(doc, topRows, topW, rightX, ry);

  ry += 8;
  const ghosts = sorted.filter(m => m.totalFats === 0).slice(0, 12);
  if (ghosts.length) {
    const ghostRows = [
      ['⚠ GHOST MEMBER', 'LAST LOGIN'],
      ...ghosts.map(m => [
        { text: m.name, color: C.GREY, align: 'left' },
        { text: m.lastLogin || '—', color: C.RED },
      ]),
    ];
    drawTable(doc, ghostRows, [rightW * 0.6, rightW * 0.4], rightX, ry);
  }

  // ── Page 2+: Full Roster ─────────────────────────────────────────────────
  doc.addPage();
  y = MARGIN;
  y = drawTitle(doc,
    `◈  ${corpName.toUpperCase()}  ·  FULL ROSTER  ◈`,
    `★ ELITE 8+  ◆ ACTIVE 4–7  ▷ PARTIAL 1–3  ○ GHOST 0  ·  ` +
    `Showing ${yearMonths(year).length} months for ${year}`,
    y,
  );

  const colW = rosterColWidths(year);
  const rows = [
    rosterHeader(year),
    ...sorted.map((m, i) => rosterRow(m, i, year)),
  ];
  y = drawTable(doc, rows, colW, MARGIN, y);

  y += 6;
  doc.save().font(FONT).fontSize(6).fillColor(C.GREY)
     .text(
       'IN ALLIANCE = time since character joined corp OR corp joined SoB, whichever is more recent  ·  ' +
       'Data: Alliance Auth (Member Audit + AFAT) + ESI',
       MARGIN, y, { width: pw - 2 * MARGIN, align: 'center', lineBreak: false },
     )
     .restore();

  doc.end();
  return finish;
}

// ── Alliance report ───────────────────────────────────────────────────────────

async function buildAlliancePdf(corps, year, outPath) {
  const sorted  = [...corps].sort(
    (a, b) => b.members.reduce((s, m) => s + m.totalFats, 0)
            - a.members.reduce((s, m) => s + m.totalFats, 0)
  );
  const allM    = corps.flatMap(c => c.members);
  const doc     = makePdf(outPath, 'SONS of BANE — Alliance Audit');
  const pw      = doc.page.width;
  const finish  = pipeToFile(doc, outPath);

  // ── Page 1: Alliance Summary ──────────────────────────────────────────────
  let y = MARGIN;
  y = drawTitle(doc,
    '◈  SONS OF BANE  ·  ALLIANCE AUDIT REPORT  ◈',
    `EVE Online  ·  Audit: ${new Date().toISOString().slice(0, 10)}  ·  ${sorted.length} Corps  ·  ${allM.length} Mains  ·  Year: ${year}`,
    y,
  );

  const aHdr = ['#', 'CORPORATION', 'MAINS', 'TOTAL FATs', `${year} FATs`,
                '★ ELITE', '◆ ACTIVE', '▷ PARTIAL', '○ GHOST'];
  const usable = pw - 2 * MARGIN;
  const aW = [
    Math.round(usable * 0.03), Math.round(usable * 0.22),
    Math.round(usable * 0.07), Math.round(usable * 0.09), Math.round(usable * 0.09),
    Math.round(usable * 0.10), Math.round(usable * 0.10), Math.round(usable * 0.10), Math.round(usable * 0.10),
  ];

  const allianceRows = [
    aHdr,
    ...sorted.map((corp, i) => {
      const ms      = corp.members;
      const total   = ms.reduce((s, m) => s + m.totalFats, 0);
      const ytd     = ms.reduce((s, m) => s + (m.fatsByYear[year] || 0), 0);
      const elite   = ms.filter(m => m.totalFats >= 8).length;
      const active  = ms.filter(m => m.totalFats >= 4 && m.totalFats < 8).length;
      const partial = ms.filter(m => m.totalFats >= 1 && m.totalFats < 4).length;
      const ghost   = ms.filter(m => m.totalFats === 0).length;
      return [
        { text: i + 1,      color: C.GREY },
        { text: corp.name,  color: C.WHITE, bold: true, align: 'left' },
        { text: ms.length },
        { text: total, color: total >= 50 ? C.TEAL : total >= 20 ? C.GREEN : C.WHITE, bold: true },
        { text: ytd,   color: ytd   > 0 ? C.TEAL  : C.GREY },
        { text: elite,   color: elite   ? C.TEAL  : C.GREY },
        { text: active,  color: active  ? C.GREEN : C.GREY },
        { text: partial, color: partial ? C.GOLD  : C.GREY },
        { text: ghost,   color: ghost   ? C.RED   : C.GREY },
      ];
    }),
  ];
  drawTable(doc, allianceRows, aW, MARGIN, y);

  // ── Per-corp roster pages ─────────────────────────────────────────────────
  for (const corp of sorted) {
    if (!corp.members.length) continue;
    const ms = [...corp.members].sort((a, b) => b.totalFats - a.totalFats);
    doc.addPage();
    y = MARGIN;
    y = drawTitle(doc,
      `◈  ${corp.name.toUpperCase()}  ◈`,
      `${ms.length} Mains  ·  Total FATs: ${ms.reduce((s, m) => s + m.totalFats, 0)}  ·  ${year} YTD: ${ms.reduce((s, m) => s + (m.fatsByYear[year] || 0), 0)}`,
      y,
    );
    const rows = [rosterHeader(year), ...ms.map((m, i) => rosterRow(m, i, year))];
    drawTable(doc, rows, rosterColWidths(year), MARGIN, y);
  }

  doc.end();
  return finish;
}

module.exports = { buildCorpPdf, buildAlliancePdf };
