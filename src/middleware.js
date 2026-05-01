'use strict';

/**
 * Auth middleware — attach to routes to enforce role requirements.
 *
 * Roles (ascending):  member → officer → admin
 *   member  — authenticated S0B alliance member
 *   officer — corp Director or CEO (checked via ESI roles scope)
 *   admin   — character ID listed in ADMIN_CHARS env var
 */
const { SOB_ALLIANCE_ID } = require('./config');

function requireMember(req, res, next) {
  const u = req.session?.user;
  if (!u) return res.status(401).json({ detail: 'Login required.', loginUrl: '/auth/login' });
  if (u.allianceId !== SOB_ALLIANCE_ID)
    return res.status(403).json({ detail: 'SONS of BANE members only.' });
  next();
}

function requireOfficer(req, res, next) {
  requireMember(req, res, () => {
    if (!['officer', 'admin'].includes(req.session.user.role))
      return res.status(403).json({ detail: 'Corp Director or higher required.' });
    next();
  });
}

function requireAdmin(req, res, next) {
  requireMember(req, res, () => {
    if (req.session.user.role !== 'admin')
      return res.status(403).json({ detail: 'Admin access required.' });
    next();
  });
}

module.exports = { requireMember, requireOfficer, requireAdmin };
