'use strict';

// Standalone test — run with:  node test/reportAccess.test.js
//
// Validates report access control:
//   - non-admins may download only their own corp's corp-report
//   - non-admins may download only CSV reports they generated themselves
//   - alliance reports are admin-only
//   - admins may access everything
//   - missing/unverifiable sidecars deny non-admins

const assert = require('assert');
const fs     = require('fs');
const path   = require('path');
const { REPORTS_DIR } = require('../src/config');
const { canAccessReport } = require('../src/routes/audit');

function pass(msg) { console.log(`  ✓  ${msg}`); }
function check(label, actual, expected) {
  try { assert.strictEqual(actual, expected); pass(label); }
  catch { console.error(`  ✗  ${label}`); throw new Error(`expected ${expected}, got ${actual}`); }
}

fs.mkdirSync(REPORTS_DIR, { recursive: true });

// ── Fixtures: write report sidecars exactly as the routes do ──────────────────
function writeSidecar(pdfName, obj) {
  fs.writeFileSync(path.join(REPORTS_DIR, pdfName.replace('.pdf', '.json')), JSON.stringify(obj));
}

const corpPdf     = 'test_acl_corp_x.pdf';
const otherCorpPdf= 'test_acl_corp_y.pdf';
const alliancePdf = 'test_acl_alliance.pdf';
const csvMinePdf  = 'test_acl_csv_mine.pdf';
const csvOtherPdf = 'test_acl_csv_other.pdf';
const created = [corpPdf, otherCorpPdf, alliancePdf, csvMinePdf, csvOtherPdf];

writeSidecar(corpPdf,      { type: 'corp', corpId: 98000001, ownerCharId: 91000010, corpName: 'My Corp', members: [{ name: 'a' }] });
writeSidecar(otherCorpPdf, { type: 'corp', corpId: 98000999, ownerCharId: 91000999, corpName: 'Other Corp', members: [{ name: 'b' }] });
writeSidecar(alliancePdf,  { type: 'alliance', ownerCharId: 91000010, corps: [{ corpId: 98000001 }] });
writeSidecar(csvMinePdf,   { type: 'csv', ownerCharId: 91000010, reportName: 'mine', members: [{ name: 'c' }] });
writeSidecar(csvOtherPdf,  { type: 'csv', ownerCharId: 91000999, reportName: 'theirs', members: [{ name: 'd' }] });

// ── Users ─────────────────────────────────────────────────────────────────────
const member  = { role: 'member',  charId: 91000010, corpId: 98000001 };
const officer = { role: 'officer', charId: 91000010, corpId: 98000001 };
const admin   = { role: 'admin',   charId: 91000010, corpId: 98000001 };

try {
  console.log('\n[1] corp reports — own vs other');
  check('member can access own corp report',        canAccessReport(member,  corpPdf),      true);
  check('member cannot access other corp report',   canAccessReport(member,  otherCorpPdf), false);
  check('officer cannot access other corp report',  canAccessReport(officer, otherCorpPdf), false);

  console.log('\n[2] alliance reports — admin only');
  check('member cannot access alliance report',     canAccessReport(member,  alliancePdf),  false);
  check('officer cannot access alliance report',    canAccessReport(officer, alliancePdf),  false);
  check('admin can access alliance report',         canAccessReport(admin,   alliancePdf),  true);

  console.log('\n[3] csv reports — generator only');
  check('member can access own csv report',         canAccessReport(member,  csvMinePdf),   true);
  check('member cannot access others csv report',   canAccessReport(member,  csvOtherPdf),  false);

  console.log('\n[4] admin override + missing sidecar');
  check('admin can access any corp report',         canAccessReport(admin,   otherCorpPdf), true);
  check('member denied when sidecar missing',       canAccessReport(member,  'test_acl_nonexistent.pdf'), false);

  console.log('\n✓ All tests passed\n');
} catch (e) {
  console.error('\n✗ FAILED:', e.message, '\n');
  process.exitCode = 1;
} finally {
  for (const f of created) {
    try { fs.unlinkSync(path.join(REPORTS_DIR, f.replace('.pdf', '.json'))); } catch {}
  }
}
