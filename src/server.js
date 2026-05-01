'use strict';

const express   = require('express');
const expressWs = require('express-ws');
const session   = require('express-session');
const fs        = require('fs');
const { PORT, STATIC_DIR, REPORTS_DIR, SESSION_SECRET } = require('./config');

fs.mkdirSync(REPORTS_DIR, { recursive: true });

const app = express();
expressWs(app);          // must be called before routes so app.ws() exists

// Trust Railway's reverse proxy so req.secure is correct for cookie flags
app.set('trust proxy', 1);

app.use(express.json());
app.use(session({
  secret:            SESSION_SECRET,
  resave:            false,
  saveUninitialized: false,
  cookie: {
    secure:   process.env.NODE_ENV === 'production',
    httpOnly: true,
    maxAge:   7 * 24 * 60 * 60 * 1000, // 7 days
  },
}));

// Auth routes (unauthenticated)
require('./routes/sso')(app);

// Protected routes
require('./routes/audit')(app);
require('./routes/config')(app);
require('./routes/cache')(app);

// Serve the frontend
app.use(express.static(STATIC_DIR));
app.get('*', (_, res) => res.sendFile(require('path').join(STATIC_DIR, 'index.html')));

app.listen(PORT, () => {
  console.log(`SoB Audit running at http://localhost:${PORT}`);
});
