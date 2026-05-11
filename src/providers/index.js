'use strict';

const fs   = require('fs');
const path = require('path');
const { AllianceAuthProvider } = require('./authScraper');
const { ESIProvider }          = require('./esi');

/**
 * Drop a .js file into src/providers/extra/ that exports a BaseProvider
 * subclass (default export or named export) and it will be loaded automatically.
 */
const EXTRA_PROVIDERS = [];
const extraDir = path.join(__dirname, 'extra');
if (fs.existsSync(extraDir)) {
  for (const file of fs.readdirSync(extraDir).filter(f => f.endsWith('.js')).sort()) {
    try {
      const mod = require(path.join(extraDir, file));
      const Cls = mod.default || Object.values(mod).find(v => typeof v === 'function' && v.prototype);
      if (Cls) EXTRA_PROVIDERS.push(new Cls());
    } catch (e) {
      console.warn(`[providers/extra] Failed to load ${file}:`, e.message);
    }
  }
}

module.exports = { AllianceAuthProvider, ESIProvider, EXTRA_PROVIDERS };
