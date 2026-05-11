'use strict';

/**
 * Base class for audit data providers.
 *
 * To add a new data source:
 *   1. Create src/providers/yourSource.js and extend BaseProvider
 *   2. Implement enrich(chars, corpId, corpName, year, log)
 *   3. Instantiate and add to EXTRA_PROVIDERS in src/providers/index.js
 *
 * Write enriched data to char.providerData[this.name] = { ... }
 */
class BaseProvider {
  get name() { return 'base'; }
  get requiresAuth() { return false; }

  async listAllianceCorps(year, month) { return []; }
  async listCorpMembers(corpName) { return []; }

  // Each item: { header, widthPt, align, providerName, dataKey, colorTheme }
  // colorTheme: 'fats' | 'teal' | 'gold' | 'green' | 'grey'
  get extraColumns() { return []; }

  /**
   * Enrich characters in-place. Called once per corp audit.
   * @param {object[]} chars
   * @param {number}   corpId
   * @param {string}   corpName
   * @param {number}   year
   * @param {Function} log  (msg: string, tag: string) => void
   */
  async enrich(chars, corpId, corpName, year, log) {}
}

module.exports = { BaseProvider };
