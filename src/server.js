'use strict';

const express   = require('express');
const expressWs = require('express-ws');
const fs        = require('fs');
const { PORT, STATIC_DIR, REPORTS_DIR } = require('./config');

fs.mkdirSync(REPORTS_DIR, { recursive: true });

const app = express();
expressWs(app);          // must be called before routes so app.ws() exists
app.use(express.json());

// Routes (pass app directly so WS routes can be registered)
require('./routes/audit')(app);
require('./routes/config')(app);
require('./routes/cache')(app);

// Serve the frontend
app.use(express.static(STATIC_DIR));
app.get('*', (_, res) => res.sendFile(require('path').join(STATIC_DIR, 'index.html')));

app.listen(PORT, () => {
  console.log(`SoB Audit running at http://localhost:${PORT}`);
});
