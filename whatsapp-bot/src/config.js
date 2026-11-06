'use strict';
const fs = require('fs');
const path = require('path');

/** Minimal .env loader (no dependencies). Existing process.env values win. */
function loadDotEnv(file = path.join(__dirname, '..', '.env')) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    let value = m[2];
    if (/^(['"]).*\1$/.test(value)) value = value.slice(1, -1);
    if (process.env[m[1]] === undefined) process.env[m[1]] = value;
  }
}

/** Digits only; a bare 10-digit Indian mobile number gets the 91 country code. */
function normalizePhone(raw) {
  let digits = String(raw || '').replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
  if (digits.length === 10) digits = '91' + digits;
  return digits;
}

function list(value, fallback) {
  return String(value ?? fallback)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function loadConfig(env = process.env) {
  const rootDir = path.join(__dirname, '..');
  const csv = env.CATALOG_CSV ?? 'data/catalog.csv';
  return {
    port: Number(env.PORT || 3000),
    whatsapp: {
      token: env.WHATSAPP_TOKEN || '',
      phoneNumberId: env.WHATSAPP_PHONE_NUMBER_ID || '',
      verifyToken: env.WEBHOOK_VERIFY_TOKEN || '',
      appSecret: env.WHATSAPP_APP_SECRET || '',
      apiVersion: env.GRAPH_API_VERSION || 'v23.0',
    },
    adminNumbers: list(env.ADMIN_NUMBERS, '9636314866').map(normalizePhone),
    triggerMessage: env.TRIGGER_MESSAGE || 'Team - Status Query to be Answered',
    stopMessages: list(env.STOP_MESSAGES, 'stop,exit,end,done'),
    sessionTimeoutMs: Number(env.SESSION_TIMEOUT_HOURS ?? 12) * 3600 * 1000,
    catalog: {
      sheetId: env.SHEET_ID ?? '1wcR2TDqy24SALIkHTnwXpLe0RHKeu2EXZoPyraZBtdM',
      sheetName: env.SHEET_NAME || 'Products',
      csv: csv && !/^https?:/i.test(csv) ? path.resolve(rootDir, csv) : csv,
      cacheMs: Number(env.CATALOG_CACHE_SECONDS ?? 120) * 1000,
    },
    orderNumber: normalizePhone(env.ORDER_WHATSAPP_NUMBER || '919928377710'),
    catalogPageUrl: env.CATALOG_PAGE_URL || '',
    businessName: env.BUSINESS_NAME || "Preeti Suri's",
    currency: env.CURRENCY_SYMBOL || '₹',
    stateFile: path.join(rootDir, 'data', 'state.json'),
  };
}

module.exports = { loadConfig, loadDotEnv, normalizePhone };
