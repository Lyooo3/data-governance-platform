import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { AppError, requireValue } from './store.mjs';

export function identifier(name, dialect = 'sqlite') {
  requireValue(typeof name === 'string' && /^[\p{L}_][\p{L}\p{N}_$]{0,127}$/u.test(name), '表名或字段名包含不支持的字符');
  return dialect === 'mysql' ? '`' + name + '`' : '"' + name + '"';
}
export function qualified(name, dialect) { return String(name).split('.').map(x => identifier(x, dialect)).join('.'); }
export function readSql(sql) {
  requireValue(typeof sql === 'string' && sql.length <= 20_000, '查询语句无效');
  sql = sql.trim().replace(/;\s*$/, '');
  requireValue(/^(select|with)\b/i.test(sql) && !/;|--|\/\*|\b(insert|update|delete|drop|alter|create|attach|detach|pragma|copy|call|grant|revoke|vacuum|into|outfile|load_file)\b/i.test(sql), '只允许单条只读SELECT查询');
  return sql;
}

export async function connect(store, source, write = false) {
  requireValue(source, '数据源不存在', 404);
  const type = String(source.type || '').toLowerCase();
  if (write) requireValue(source.allowWrite === true, '此数据源未启用目标表写入');
  let connection;
  if (type === 'sqlite') {
    requireValue(/^[a-zA-Z0-9_-]+\.sqlite$/.test(source.file || ''), '本地数据源路径无效');
    connection = new DatabaseSync(path.join(store.dir, 'sources', source.file), { readOnly: !write });
    connection.exec('PRAGMA busy_timeout=5000;');
    if (!write) connection.exec('PRAGMA query_only=ON;');
    return {
      type,
      query: async (sql, params = []) => connection.prepare(sql).all(...params),
      execute: async (sql, params = []) => connection.prepare(sql).run(...params),
      begin: async () => connection.exec('BEGIN'), commit: async () => connection.exec('COMMIT'), rollback: async () => connection.exec('ROLLBACK'),
      close: async () => connection.close(),
    };
  }
  requireValue(['mysql', 'postgresql', 'postgres'].includes(type), '目前支持SQLite、MySQL和PostgreSQL');
  const password = store.decrypt(source.passwordSecret);
  if (type === 'mysql') {
    const { default: mysql } = await import('mysql2/promise');
    connection = await mysql.createConnection({ host: source.host, port: Number(source.port || 3306), user: source.user, password, database: source.database, connectTimeout: 8000, multipleStatements: false, supportBigNumbers: true, bigNumberStrings: true, dateStrings: true, ...(source.tls ? { ssl: { rejectUnauthorized: true } } : {}) });
    if (!write) {
      await connection.query('SET SESSION MAX_EXECUTION_TIME=15000');
      await connection.query('START TRANSACTION READ ONLY');
    }
    return {
      type,
      query: async (sql, params = []) => { const [rows] = await connection.query({ sql, timeout: 16000 }, params); return rows; },
      execute: async (sql, params = []) => connection.execute({ sql, timeout: 16000 }, params),
      begin: async () => connection.beginTransaction(), commit: async () => connection.commit(), rollback: async () => connection.rollback(),
      close: async () => connection.end(),
    };
  }
  const { default: pg } = await import('pg');
  connection = new pg.Client({ host: source.host, port: Number(source.port || 5432), user: source.user, password, database: source.database, connectionTimeoutMillis: 8000, query_timeout: 16000, statement_timeout: 15000, ...(source.tls ? { ssl: { rejectUnauthorized: true } } : {}) });
  await connection.connect();
  if (!write) await connection.query('BEGIN READ ONLY');
  return {
    type: 'postgresql',
    query: async (sql, params = []) => (await connection.query(sql, params)).rows,
    execute: async (sql, params = []) => connection.query(sql, params),
    begin: async () => connection.query('BEGIN'), commit: async () => connection.query('COMMIT'), rollback: async () => connection.query('ROLLBACK'),
    close: async () => connection.end(),
  };
}

export async function withConnection(store, sourceId, fn, write = false) {
  let connection;
  try { connection = await connect(store, store.get('sources', sourceId), write); return await fn(connection); }
  catch (error) {
    if (error instanceof AppError) throw error;
    // Return the error category, never driver messages containing host, user, SQL or credentials.
    const safeCodes = new Set(['ECONNREFUSED','ETIMEDOUT','ENOTFOUND','ER_ACCESS_DENIED_ERROR','ER_BAD_DB_ERROR','ER_TABLE_EXISTS_ERROR','42P07','28P01','3D000']);
    if (error.code === 'ER_TABLE_EXISTS_ERROR' || error.code === '42P07' || /already exists/i.test(error.message || '')) throw new AppError('目标表已存在，请使用新的表名；原表没有被覆盖',409);
    throw new AppError(`数据库操作失败${safeCodes.has(error.code) ? '（' + error.code + '）' : ''}，请检查连接配置、权限或表结构`, 422);
  } finally { if (connection) await connection.close().catch(() => {}); }
}

export async function tables(store, sourceId) {
  return withConnection(store, sourceId, async c => {
    if (c.type === 'sqlite') return (await c.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")).map(x => ({ name: x.name, schema: '', qualifiedName: x.name }));
    if (c.type === 'mysql') return (await c.query('SELECT table_name AS name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type=? ORDER BY table_name', ['BASE TABLE'])).map(x => ({ name: x.name, schema: '', qualifiedName: x.name }));
    return (await c.query("SELECT table_schema AS schema,table_name AS name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE' ORDER BY table_schema,table_name")).map(x => ({ ...x, qualifiedName: x.schema + '.' + x.name }));
  });
}

export async function columns(store, sourceId, table) {
  return withConnection(store, sourceId, async c => {
    const parts = String(table).split('.'); parts.forEach(x => identifier(x, c.type));
    if (c.type === 'sqlite') {
      requireValue(parts.length === 1, 'SQLite表名不需要schema');
      return (await c.query(`PRAGMA table_info(${identifier(table)})`)).map(x => ({ name: x.name, type: x.type, nullable: !x.notnull, primaryKey: Boolean(x.pk) }));
    }
    if (c.type === 'mysql') return (await c.query('SELECT column_name AS name,data_type AS type,is_nullable AS nullable,column_key AS columnKey FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position', [parts.at(-1)])).map(x => ({ ...x, nullable: x.nullable === 'YES', primaryKey: x.columnKey === 'PRI' }));
    return (await c.query('SELECT column_name AS name,data_type AS type,is_nullable AS nullable FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position', [parts.length === 2 ? parts[0] : 'public', parts.at(-1)])).map(x => ({ ...x, nullable: x.nullable === 'YES' }));
  });
}

export async function sourceRows(store, config, maxRows = 10000) {
  requireValue(config.sourceId, '请选择数据源');
  requireValue(config.sql || typeof config.table === 'string' && config.table.trim(), '请选择数据表或填写只读查询');
  return withConnection(store, config.sourceId, async c => {
    const sql = config.sql ? readSql(config.sql) : `SELECT * FROM ${qualified(config.table, c.type)}`;
    const rows = await c.query(`SELECT * FROM (${sql}) AS govern_input LIMIT ${maxRows + 1}`);
    requireValue(rows.length <= maxRows, `数据超过本次运行上限${maxRows}行，请通过查询条件缩小范围；本次未生成不完整报告`, 422);
    return JSON.parse(JSON.stringify(rows, (_, value) => typeof value === 'bigint' ? value.toString() : value));
  });
}

export async function previewRows(store, config, params = {}) {
  const pageNum = Math.max(1, Math.floor(Number(params.pageNum || params.pageNumber) || 1));
  const pageSize = Math.min(500,Math.max(1,Math.floor(Number(params.pageSize)||20)));
  requireValue(pageNum <= 1_000_000, '页码过大');
  requireValue(config.sourceId && (config.sql || config.table), '需要数据源和表名或查询');
  return withConnection(store,config.sourceId,async c=>{
    const sql = config.sql ? readSql(config.sql) : `SELECT * FROM ${qualified(config.table,c.type)}`;
    const count = await c.query(`SELECT COUNT(*) AS total FROM (${sql}) AS govern_count`);
    const rows = await c.query(`SELECT * FROM (${sql}) AS govern_page LIMIT ${pageSize} OFFSET ${(pageNum-1)*pageSize}`);
    return {list:JSON.parse(JSON.stringify(rows,(_,value)=>typeof value==='bigint'?value.toString():value)),total:Number(count[0].total),pageNum,pageSize};
  });
}

export async function writeNewTable(store, sourceId, name, rows) {
  requireValue(rows.length > 0, '输出数据为空，未创建目标表');
  const fields = Object.keys(rows[0]);
  requireValue(fields.length > 0 && fields.length <= 200, '输出字段数量无效');
  return withConnection(store, sourceId, async c => {
    const table = qualified(name, c.type), quoted = fields.map(x => identifier(x, c.type));
    const definitions = fields.map((field, index) => {
      const present = rows.map(row=>row[field]).filter(value=>value!=null);
      const numeric = present.length && present.every(value=>typeof value==='number' && Number.isFinite(value));
      const integer = numeric && present.every(Number.isSafeInteger);
      const type = integer ? (c.type==='sqlite'?'INTEGER':'BIGINT') : numeric ? (c.type==='mysql'?'DOUBLE':'DOUBLE PRECISION') : 'TEXT';
      return quoted[index] + ' ' + type;
    });
    let created = false;
    try {
      // CREATE without IF NOT EXISTS intentionally refuses to overwrite or append to existing business tables.
      if (c.type === 'mysql') { await c.execute(`CREATE TABLE ${table} (${definitions.join(',')})`); created = true; }
      await c.begin();
      if (c.type !== 'mysql') await c.execute(`CREATE TABLE ${table} (${definitions.join(',')})`);
      const placeholders = fields.map((_, i) => c.type === 'postgresql' ? '$' + (i + 1) : '?');
      for (const row of rows) await c.execute(`INSERT INTO ${table} (${quoted.join(',')}) VALUES (${placeholders.join(',')})`, fields.map(k => row[k] == null ? null : typeof row[k] === 'object' ? JSON.stringify(row[k]) : row[k]));
      await c.commit();
    } catch (error) {
      await c.rollback().catch(() => {});
      if (c.type === 'mysql' && created) await c.execute(`DROP TABLE ${table}`).catch(() => {});
      throw error;
    }
    return { sourceId, table: name, rows: rows.length };
  }, true);
}
