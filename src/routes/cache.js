'use strict';

const { cacheStats, cacheClear } = require('../cache');

module.exports = (app) => {

  app.get('/api/cache/stats', async (req, res) => {
    res.json(await cacheStats());
  });

  app.delete('/api/cache/clear', async (req, res) => {
    const cleared = await cacheClear();
    res.json({ cleared });
  });

};
