'use strict';

/**
 * Provider registry.
 *
 * To add a new data source:
 *   1. Create src/providers/yourSource.js extending BaseProvider
 *   2. Instantiate and push to EXTRA_PROVIDERS below
 *   3. The audit engine will call provider.enrich() for every corp automatically
 */
const { AllianceAuthProvider } = require('./authScraper');
const { ESIProvider }          = require('./esi');

// Add future providers here, e.g.:
// const { ZKillProvider } = require('./zkill');
const EXTRA_PROVIDERS = [
  // new ZKillProvider(),
];

module.exports = { AllianceAuthProvider, ESIProvider, EXTRA_PROVIDERS };
