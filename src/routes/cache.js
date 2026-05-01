'use strict';

const { cacheStats, cacheClear } = require('../cache');
const { requireAdmin } = require('../middleware');

module.exports = (app) => {

  app.get('/api/cache/stats', requireAdmin, async (req, res) => {
    res.json(await cacheStats());
  });

  app.delete('/api/cache/clear', requireAdmin, async (req, res) => {
    const cleared = await cacheClear();
    res.json({ cleared });
  });

};
