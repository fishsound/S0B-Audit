'use strict';

// Standalone test — run with:  node test/altCount.test.js
//
// Validates the entire alt-count pipeline for a known character:
//   - _parseNameCell handles anchor, img+anchor, and plain-text column-2 formats
//   - _buildAltCountMap counts alts correctly (target: brahiem = 5)
//   - enrich() alt assignment survives Object.assign overwriting the character shell

const assert = require('assert');
const { AllianceAuthProvider } = require('../src/providers/authScraper');
const { makeCharacter } = require('../src/models');

// ── helpers ───────────────────────────────────────────────────────────────────

function pass(msg) { console.log(`  ✓  ${msg}`); }
function fail(msg, err) { console.error(`  ✗  ${msg}`); throw err; }

function check(label, actual, expected) {
  try {
    assert.strictEqual(actual, expected);
    pass(label);
  } catch (e) {
    fail(label, new Error(`expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`));
  }
}

// ── Build a provider instance (no real HTTP needed for unit tests) ─────────────
const provider = new AllianceAuthProvider('dummy-session', 'dummy-csrf');

// ── Section 1: _parseNameCell formats ─────────────────────────────────────────
console.log('\n[1] _parseNameCell — column-2 format variants');

{
  // Standard aa-memberaudit format: anchor only
  const html = `<a href="/member-audit/character_viewer/111/">Brahiem</a>`;
  const [pk, name] = provider._parseNameCell(html);
  check('anchor-only → pk=111',    pk,   111);
  check('anchor-only → name=Brahiem', name, 'Brahiem');
}
{
  // Common format: portrait img + anchor
  const html = `<img src="/eve/chars/111?size=32" alt="Portrait"> `
             + `<a href="/member-audit/character_viewer/111/">Brahiem</a>`;
  const [pk, name] = provider._parseNameCell(html);
  check('img+anchor → pk=111',      pk,   111);
  check('img+anchor → name=Brahiem', name, 'Brahiem');
}
{
  // Plain text (some Alliance Auth installs render without hyperlink)
  const html = `Brahiem`;
  const [pk, name] = provider._parseNameCell(html);
  // _parseNameCell alone can't extract a pk-less plain name — that's the
  // fallback path that _buildAltCountMap must handle separately.
  check('plain-text → pk=null',  pk,   null);
  check('plain-text → name=""',  name, '');
}

// ── Section 2: _buildAltCountMap with mock data ───────────────────────────────
console.log('\n[2] _buildAltCountMap — brahiem should have 5 alts');

async function testBuildAltCountMap() {
  // Simulate what character_finder_data returns.
  // Row layout (13 cols):
  //   [0]=nameCell  [1]=? [2]=mainCell [3..9]=misc [10]=main_str [11]=? [12]=charId
  //
  // We test three column-2 formats to ensure at least one works:
  //   rows 0-1  : anchor format
  //   rows 2-3  : img+anchor format
  //   row  4    : plain-text format  ← currently broken in original code

  function makeMainRow(pk, name) {
    const row = new Array(13).fill('');
    row[0]  = `<a href="/member-audit/character_viewer/${pk}/">${name}</a>`;
    row[10] = 'yes';
    row[12] = String(pk);
    return row;
  }

  function makeAltRow(altPk, altName, mainPk, mainName, format = 'anchor') {
    const row = new Array(13).fill('');
    row[0]  = `<a href="/member-audit/character_viewer/${altPk}/">${altName}</a>`;
    row[10] = 'no';
    row[12] = String(altPk);
    if (format === 'anchor') {
      row[2] = `<a href="/member-audit/character_viewer/${mainPk}/">${mainName}</a>`;
    } else if (format === 'img+anchor') {
      row[2] = `<img src="/eve/${mainPk}" alt="Portrait"> `
             + `<a href="/member-audit/character_viewer/${mainPk}/">${mainName}</a>`;
    } else {
      row[2] = mainName;  // plain text
    }
    return row;
  }

  const finderData = [
    makeMainRow(1000, 'Brahiem'),
    makeMainRow(2000, 'OtherMain'),
    // 5 alts for Brahiem: mix of formats
    makeAltRow(1001, 'BrahiemAlt1', 1000, 'Brahiem', 'anchor'),
    makeAltRow(1002, 'BrahiemAlt2', 1000, 'Brahiem', 'anchor'),
    makeAltRow(1003, 'BrahiemAlt3', 1000, 'Brahiem', 'img+anchor'),
    makeAltRow(1004, 'BrahiemAlt4', 1000, 'Brahiem', 'img+anchor'),
    makeAltRow(1005, 'BrahiemAlt5', 1000, 'Brahiem', 'plain-text'),
    // 2 alts for OtherMain
    makeAltRow(2001, 'OtherAlt1', 2000, 'OtherMain', 'anchor'),
    makeAltRow(2002, 'OtherAlt2', 2000, 'OtherMain', 'anchor'),
  ];

  // Monkey-patch _finderRaw to return mock data
  provider._finderRaw = async () => finderData;

  const altMap = await provider._buildAltCountMap();

  console.log('  altMap contents:', Object.fromEntries(altMap));

  // Map is now keyed by Auth PK (integer), not by name.
  check('Brahiem altCount = 5',    altMap.get(1000) ?? 0, 5);
  check('OtherMain altCount = 2',  altMap.get(2000) ?? 0, 2);
  check('no false positives',       altMap.size,           2);
}

// ── Section 3: enrich() — altCount survives Object.assign ────────────────────
async function testEnrichPreservesAltCount() {
  console.log('\n[3] enrich() — altCount must not be reset to 0 by Object.assign');

  const brahiem  = makeCharacter(1000, 'Brahiem');
  const other    = makeCharacter(2000, 'OtherMain');
  const chars    = [brahiem, other];

  // Stub out everything enrich() calls except the alt-count path
  provider._overview = async (pk) => ({
    Character:   pk === 1000 ? 'Brahiem' : 'OtherMain',
    Corporation: 'Test Corp',
    Alliance:    'Test Alliance',
  });
  provider._topAssetSystem = async () => '';
  provider._fatMonth       = async () => ({});

  // Keep the mock _finderRaw from section 2
  await provider.enrich(chars, 99, 'Test Corp', new Date().getFullYear(), () => {});

  console.log('  Brahiem.altCount =', brahiem.altCount);
  console.log('  OtherMain.altCount =', other.altCount);

  check('Brahiem.altCount = 5 after enrich',    brahiem.altCount, 5);
  check('OtherMain.altCount = 2 after enrich',  other.altCount,   2);
}

// ── Run ───────────────────────────────────────────────────────────────────────
(async () => {
  try {
    await testBuildAltCountMap();
    await testEnrichPreservesAltCount();
    console.log('\n✓ All tests passed\n');
  } catch (e) {
    console.error('\n✗ FAILED:', e.message, '\n');
    process.exit(1);
  }
})();
