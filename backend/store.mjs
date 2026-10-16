import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { randomBytes, randomUUID, scryptSync, timingSafeEqual, createHash, createCipheriv, createDecipheriv } from 'node:crypto';

export const KINDS = new Set(['sources', 'workflows', 'elements', 'businessTypes', 'qualifiers', 'dictionaries', 'catalogs', 'assets', 'rules', 'qualityTasks', 'services', 'projects', 'tables']);
export class AppError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}
export const now = () => new Date().toISOString();
export const hash = value => createHash('sha256').update(value).digest('hex');
export function requireValue(condition, message, status = 400) { if (!condition) throw new AppError(message, status); }

export class Store {
  constructor(dir) {
    this.dir = path.resolve(dir);
    mkdirSync(this.dir, { recursive: true });
    mkdirSync(path.join(this.dir, 'sources'), { recursive: true });
    const keyFile = path.join(this.dir, 'secret.key');
    if (!existsSync(keyFile)) writeFileSync(keyFile, randomBytes(32), { mode: 0o600, flag: 'wx' });
    this.key = readFileSync(keyFile);
    requireValue(this.key.length === 32, '本地密钥文件无效', 500);
    this.db = new DatabaseSync(path.join(this.dir, 'platform.sqlite'));
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS entities(kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind,id));
      CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, digest TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS run_rows(run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,ordinal));
      CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS runs_workflow ON runs(workflow_id,created_at);
      CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);`);
  }
  close() { this.db.close(); }
  transaction(fn) {
    this.db.exec('BEGIN IMMEDIATE');
    try { const result = fn(); this.db.exec('COMMIT'); return result; }
    catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  setting(key, value) {
    if (value !== undefined) this.db.prepare('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key, JSON.stringify(value));
    const row = this.db.prepare('SELECT value FROM settings WHERE key=?').get(key);
    return row ? JSON.parse(row.value) : undefined;
  }
  get(kind, id) {
    const row = this.db.prepare('SELECT payload FROM entities WHERE kind=? AND id=?').get(kind, String(id));
    return row ? JSON.parse(row.payload) : null;
  }
  all(kind) { return this.db.prepare('SELECT payload FROM entities WHERE kind=? ORDER BY created_at,id').all(kind).map(row => JSON.parse(row.payload)); }
  save(kind, data, id = data.id) {
    requireValue(KINDS.has(kind), '未知资源类型');
    requireValue(data && typeof data === 'object' && !Array.isArray(data), '配置必须为对象');
    id = String(id || randomUUID());
    const previous = this.get(kind, id);
    const record = { ...previous, ...data, id, createTime: previous?.createTime || data.createTime || now(), updateTime: now() };
    this.db.prepare('INSERT INTO entities VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at')
      .run(kind, id, JSON.stringify(record), previous?.createTime || now(), now());
    return record;
  }
  remove(kind, id) { return this.db.prepare('DELETE FROM entities WHERE kind=? AND id=?').run(kind, String(id)).changes > 0; }
  audit(actor, action, target, details = {}) {
    this.db.prepare('INSERT INTO audit(actor,action,target,details,created_at) VALUES(?,?,?,?,?)')
      .run(actor || 'system', action, String(target), JSON.stringify(details), now());
  }
  audits(limit = 100) { return this.db.prepare('SELECT * FROM audit ORDER BY id DESC LIMIT ?').all(Math.min(500, Math.max(1, Number(limit) || 100))); }
  encrypt(value) {
    const iv = randomBytes(12), cipher = createCipheriv('aes-256-gcm', this.key, iv);
    const encrypted = Buffer.concat([cipher.update(String(value), 'utf8'), cipher.final()]);
    return { iv: iv.toString('base64'), value: encrypted.toString('base64'), tag: cipher.getAuthTag().toString('base64') };
  }
  decrypt(secret) {
    if (!secret) return '';
    const decipher = createDecipheriv('aes-256-gcm', this.key, Buffer.from(secret.iv, 'base64'));
    decipher.setAuthTag(Buffer.from(secret.tag, 'base64'));
    return Buffer.concat([decipher.update(Buffer.from(secret.value, 'base64')), decipher.final()]).toString('utf8');
  }
  createUser(name, password, role = 'reader') {
    requireValue(typeof name === 'string' && /^[a-zA-Z0-9_-]{3,40}$/.test(name), '账号需为3至40位字母、数字、下划线');
    requireValue(typeof password === 'string' && password.length >= 10 && password.length <= 200, '密码需为10至200位');
    requireValue(['admin', 'reader'].includes(role), '无效角色');
    requireValue(!this.db.prepare('SELECT id FROM users WHERE name=?').get(name), '账号已经存在', 409);
    const id = randomUUID(), salt = randomBytes(16).toString('hex');
    this.db.prepare('INSERT INTO users VALUES(?,?,?,?,?)').run(id, name, role, salt, scryptSync(password, salt, 64).toString('hex'));
    return { id, name, role };
  }
  authenticate(name, password) {
    const user = this.db.prepare('SELECT * FROM users WHERE name=?').get(String(name));
    const salt = user?.salt || 'unmatched-user-salt';
    const digest = scryptSync(String(password).slice(0,200), salt, 64);
    if (!user || !timingSafeEqual(digest, Buffer.from(user.digest, 'hex'))) return null;
    return { id: user.id, name: user.name, role: user.role };
  }
  session(userId) {
    this.db.prepare('DELETE FROM sessions WHERE expires<?').run(Date.now());
    const token = randomBytes(32).toString('hex');
    this.db.prepare('INSERT INTO sessions VALUES(?,?,?)').run(hash(token), userId, Date.now() + 8 * 3600_000);
    return token;
  }
  userForToken(token) {
    if (!token || typeof token !== 'string' || token.length > 256) return null;
    const user = this.db.prepare('SELECT u.id,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.digest=? AND s.expires>?').get(hash(token), Date.now());
    return user || null;
  }
  revoke(token) { this.db.prepare('DELETE FROM sessions WHERE digest=?').run(hash(token)); }
  run(id) { const row = this.db.prepare('SELECT payload FROM runs WHERE id=?').get(id); return row ? JSON.parse(row.payload) : null; }
  runs() { return this.db.prepare('SELECT payload FROM runs ORDER BY created_at DESC').all().map(x => JSON.parse(x.payload)); }
  saveRun(run) {
    const value = { ...run, updateTime: now() };
    this.db.prepare('INSERT INTO runs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at')
      .run(value.id, value.workflowId, value.status, JSON.stringify(value), value.createTime, value.updateTime);
    return value;
  }
  saveRows(id, rows) {
    this.transaction(() => {
      this.db.prepare('DELETE FROM run_rows WHERE run_id=?').run(id);
      const insert = this.db.prepare('INSERT INTO run_rows VALUES(?,?,?)');
      rows.forEach((row, ordinal) => insert.run(id, ordinal, JSON.stringify(row)));
    });
  }
  rows(id, page = 1, size = 50) {
    const total = this.db.prepare('SELECT count(*) AS total FROM run_rows WHERE run_id=?').get(id).total;
    const list = this.db.prepare('SELECT payload FROM run_rows WHERE run_id=? ORDER BY ordinal LIMIT ? OFFSET ?').all(id, size, (page - 1) * size).map(x => JSON.parse(x.payload));
    return { list, total, pageNum: page, pageSize: size };
  }
}

export function page(items, params = {}) {
  const pageNum = Math.max(1, Math.floor(Number(params.pageNum || params.pageNumber) || 1));
  const pageSize = Math.min(500, Math.max(1, Math.floor(Number(params.pageSize) || 10)));
  const search = String(params.searchContent || params.search || '').toLowerCase();
  const ignored = new Set(['pageNum', 'pageNumber', 'pageSize', 'search', 'searchContent', 'orderField', 'orderByColumn', 'createTimeOrder', 'seType', 'isAsc', 'function', 'envType', 'projectId']);
  let filtered = items.filter(item => (!search || JSON.stringify(item).toLowerCase().includes(search)) && Object.entries(params).every(([key, value]) => {
    if (ignored.has(key) || value === '' || value == null || !(key in item)) return true;
    return String(item[key] ?? '').toLowerCase().includes(String(value).toLowerCase());
  }));
  const key = params.orderField || params.orderByColumn;
  if (key) filtered.sort((a,b) => String(a[key] ?? '').localeCompare(String(b[key] ?? '')) * (/desc/i.test(params.seType || params.isAsc || '') ? -1 : 1));
  const total = filtered.length, list = filtered.slice((pageNum - 1) * pageSize, pageNum * pageSize);
  return { list, rows: list, content: list, total, totalElements: total, pageNum, pageNumber: pageNum, pageSize, pages: Math.ceil(total / pageSize) };
}

export function publicSource(source) {
  if (!source) return source;
  const { passwordSecret, ...value } = source;
  return { ...value, hasPassword: Boolean(passwordSecret), passwd: '', password: '' };
}
