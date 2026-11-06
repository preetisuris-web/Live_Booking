'use strict';
const fs = require('fs');

/* Column aliases, so the bot works with the existing sheet layout
 * (Image Link, Design No, Price, Available Sizes, Position, Video Link)
 * and with extra columns you may add (Description, Fabric, Colour, ...). */
const ALIASES = {
  design: ['design no', 'design no.', 'design number', 'design', 'design #', 'sku', 'code'],
  image: ['image link', 'image', 'image url', 'photo', 'picture'],
  price: ['price', 'mrp', 'rate', 'selling price'],
  sizes: ['available sizes', 'sizes', 'size'],
  video: ['video link', 'video', 'video url'],
  description: ['description', 'details', 'product description', 'name', 'title', 'product name'],
  buyLink: ['buy link', 'buy now link', 'product link', 'url', 'link', 'payment link'],
  position: ['position', 'sort', 'order'],
};
const KNOWN = new Set(Object.values(ALIASES).flat());

function key(s) {
  return String(s ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Normalize a design number so "D-501", "d 501", "#501", "0501" and "501" all match. */
function normalizeDesign(raw) {
  let s = String(raw ?? '').trim().toUpperCase();
  s = s.replace(/^(DESIGN\s*(NO\.?|NUMBER|#)?|DNO\.?|D\.?\s*NO\.?)\s*[:#-]?\s*/, '');
  s = s.replace(/^#/, '');
  s = s.replace(/[\s\-_/.]+/g, '');
  if (/^\d+$/.test(s)) s = String(Number(s)); // strip leading zeros
  // "D501" -> also matchable as "501" via the alt key below
  return s;
}

function designKeys(raw) {
  const n = normalizeDesign(raw);
  const keys = new Set([n]);
  const m = n.match(/^[A-Z]{1,3}(\d+)$/);
  if (m) keys.add(String(Number(m[1])));
  return [...keys].filter(Boolean);
}

function driveToDirect(url) {
  if (!url) return '';
  url = String(url).trim();
  if (!/drive\.google\.com|docs\.google\.com/.test(url)) return url;
  const m = url.match(/\/d\/([a-zA-Z0-9_-]+)/) || url.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  return m ? `https://drive.google.com/uc?export=download&id=${m[1]}` : url;
}

function parseSizes(raw) {
  if (raw === undefined || raw === null || raw === '') return [];
  return String(raw).split(/[,\s/|]+/).map((s) => s.trim()).filter(Boolean);
}

/** Turn a raw row object (header -> value) into a product. */
function toProduct(row) {
  const byKey = {};
  for (const [k, v] of Object.entries(row)) byKey[key(k)] = v;
  const pick = (field) => {
    for (const a of ALIASES[field]) {
      const v = byKey[a];
      if (v !== undefined && v !== null && String(v).trim() !== '') return String(v).trim();
    }
    return '';
  };
  const extras = [];
  for (const [k, v] of Object.entries(row)) {
    if (!k || KNOWN.has(key(k)) || /^col\d+$/.test(k)) continue;
    if (v === undefined || v === null || String(v).trim() === '') continue;
    extras.push([String(k).trim(), String(v).trim()]);
  }
  return {
    designNo: pick('design'),
    image: driveToDirect(pick('image')),
    price: pick('price'),
    sizes: parseSizes(pick('sizes')),
    video: pick('video'),
    description: pick('description'),
    buyLink: pick('buyLink'),
    extras,
  };
}

/** Small RFC-4180-ish CSV parser (quoted fields, escaped quotes, CRLF). */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  text = String(text).replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some((f) => f !== '')) rows.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((f) => f !== '')) rows.push(row);
  if (!rows.length) return [];
  const headers = rows[0].map((h) => h.trim());
  return rows.slice(1).map((r) => Object.fromEntries(headers.map((h, i) => [h || `col${i}`, r[i] ?? ''])));
}

/** Parse Google's gviz JSON response into row objects. */
function parseGviz(text) {
  const json = JSON.parse(text.substring(text.indexOf('{'), text.lastIndexOf('}') + 1));
  if (json.status === 'error') {
    throw new Error('Google Sheet error: ' + JSON.stringify(json.errors || json));
  }
  const cols = json.table.cols.map((c, i) => c.label || `col${i}`);
  return (json.table.rows || []).map((r) => {
    const obj = {};
    cols.forEach((col, i) => {
      const cell = r.c && r.c[i];
      let v = cell ? cell.v : '';
      if (v === null || v === undefined) v = '';
      // Whole numbers come back as 501 (fine); keep formatted value for dates etc.
      if (cell && typeof cell.v !== 'number' && cell.f) v = cell.f;
      obj[col] = v;
    });
    return obj;
  });
}

class Catalog {
  constructor({ sheetId, sheetName, csv, cacheMs = 120000 }, { fetchImpl = fetch, logger = console } = {}) {
    this.sheetId = sheetId;
    this.sheetName = sheetName;
    this.csv = csv;
    this.cacheMs = cacheMs;
    this.fetch = fetchImpl;
    this.log = logger;
    this.products = [];
    this.index = new Map();
    this.loadedAt = 0;
    this.source = '';
    this.loading = null;
  }

  async loadRows() {
    const errors = [];
    if (this.sheetId) {
      try {
        const url = `https://docs.google.com/spreadsheets/d/${this.sheetId}/gviz/tq?tqx=out:json&sheet=${encodeURIComponent(this.sheetName)}`;
        const res = await this.fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const rows = parseGviz(await res.text());
        return { rows, source: `google-sheet:${this.sheetId}/${this.sheetName}` };
      } catch (e) {
        errors.push(`sheet: ${e.message}`);
      }
    }
    if (this.csv) {
      try {
        let text;
        if (/^https?:/i.test(this.csv)) {
          const res = await this.fetch(this.csv);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          text = await res.text();
        } else {
          text = fs.readFileSync(this.csv, 'utf8');
        }
        return { rows: parseCsv(text), source: `csv:${this.csv}` };
      } catch (e) {
        errors.push(`csv: ${e.message}`);
      }
    }
    throw new Error('Could not load catalogue (' + errors.join('; ') + ')');
  }

  async refresh() {
    if (this.loading) return this.loading;
    this.loading = (async () => {
      try {
        const { rows, source } = await this.loadRows();
        const products = rows.map(toProduct).filter((p) => p.designNo);
        const index = new Map();
        for (const p of products) for (const k of designKeys(p.designNo)) if (!index.has(k)) index.set(k, p);
        this.products = products;
        this.index = index;
        this.loadedAt = Date.now();
        this.source = source;
        this.log.info?.(`[catalog] loaded ${products.length} products from ${source}`);
      } finally {
        this.loading = null;
      }
    })();
    return this.loading;
  }

  async ensureFresh() {
    if (!this.loadedAt || Date.now() - this.loadedAt > this.cacheMs) {
      try {
        await this.refresh();
      } catch (e) {
        if (!this.loadedAt) throw e; // nothing cached at all
        this.log.warn?.(`[catalog] refresh failed, using cached data: ${e.message}`);
      }
    }
  }

  /** Find a product by design number. Re-reads the sheet once on a miss (new rows). */
  async find(designNo) {
    await this.ensureFresh();
    let hit = this.lookup(designNo);
    if (!hit && Date.now() - this.loadedAt > 10000) {
      try { await this.refresh(); } catch (e) { /* keep cached */ }
      hit = this.lookup(designNo);
    }
    return hit;
  }

  lookup(designNo) {
    for (const k of designKeys(designNo)) {
      const p = this.index.get(k);
      if (p) return p;
    }
    return null;
  }

  /** Closest design numbers, for "did you mean" hints. */
  suggest(designNo, limit = 3) {
    const target = normalizeDesign(designNo);
    if (!target) return [];
    return this.products
      .map((p) => ({ p, d: distance(target, normalizeDesign(p.designNo)) }))
      .filter((x) => x.d <= Math.max(1, Math.floor(target.length / 3)))
      .sort((a, b) => a.d - b.d)
      .slice(0, limit)
      .map((x) => x.p.designNo);
  }
}

function distance(a, b) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return dp[a.length][b.length];
}

module.exports = { Catalog, parseCsv, parseGviz, toProduct, normalizeDesign, designKeys, driveToDirect, parseSizes };
