'use strict';

const { makeCorp } = require('./models');

async function collectCorp(auth, esi, extraProviders, corpId, corpName, year, log = console.log) {
  log(`  [+] Collecting ${corpName} (ID ${corpId})…`, 'cyan');
  const corp    = makeCorp(corpId, corpName);
  const members = await auth.listCorpMembers(corpName);
  log(`      found ${members.length} mains`, 'grey');
  if (!members.length) return corp;

  await auth.enrich(members, corpId, corpName, year, log);
  await esi.enrich(members, corpId, corpName, year, log);

  for (const provider of extraProviders) {
    try {
      log(`      [${provider.name}] enriching…`, 'grey');
      await provider.enrich(members, corpId, corpName, year, log);
    } catch (e) {
      log(`      [${provider.name}] failed: ${e.message}`, 'red');
    }
  }

  corp.members = members;
  log(`  [✓] ${corpName} — ${members.length} members collected`, 'green');
  return corp;
}

async function collectAlliance(auth, esi, extraProviders, year, log = console.log) {
  const today    = new Date();
  const corpList = await auth.listAllianceCorps(today.getFullYear(), today.getMonth() + 1);
  log(`  Discovered ${corpList.length} corps in SONS of BANE`, 'cyan');

  const corps = [];
  for (const [corpId, corpName] of corpList) {
    try {
      const corp = await collectCorp(auth, esi, extraProviders, corpId, corpName, year, log);
      corps.push(corp);
    } catch (e) {
      log(`  ! ${corpName} failed: ${e.message}`, 'red');
    }
  }
  return corps;
}

module.exports = { collectCorp, collectAlliance };
