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
    totalFats:     0,
    fatsByYear:    {},
    fatsByMonth:   {},
    topAssetSystem: '',
    altCount:       0,
    csvFat:         null,   // set when an AFAT CSV supplement was provided
  };
}

module.exports = { makeCharacter };
