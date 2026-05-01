'use strict';

function makeCharacter(pk, name) {
  return {
    pk,
    name,
    eveId:        null,
    corpName:     '',
    corpId:       null,
    allianceName: '',
    mainName:     '',
    isMain:       false,
    joinDate:     '',
    timeInCorp:   '',
    born:         '',
    skillpointsM: 0,
    lastLogin:    '',
    secStatus:    0,
    walletB:      0,
    assetsB:      0,
    location:     '',
    ship:         '',
    totalFats:    0,
    fatsByYear:   {},
    fatsByMonth:  {},
    // Extensible bucket — new providers write keyed sub-objects here,
    // e.g. providerData.zkillboard = { kills: 42, efficiency: 0.87 }
    providerData: {},
  };
}

function makeCorp(corpId, name) {
  return { corpId, name, members: [] };
}

module.exports = { makeCharacter, makeCorp };
