import { Worker } from 'node:worker_threads';
import { randomBytes, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { Store, AppError, requireValue, publicSource, page, KINDS, now, hash } from './store.mjs';
import { tables, columns, previewRows, withConnection, writeNewTable } from './connectors.mjs';
import { validateWorkflow, NODE_TYPES } from './engine.mjs';
import { seed } from './seed.mjs';
import { legacy } from './legacy.mjs';

export class Backend {
  constructor({ dataDir, menus = [] }) {
    this.store = new Store(dataDir); seed(this.store);
    this.menus = menus; this.active = new Map(); this.loginAttempts = new Map(); this.serviceUsage = new Map();
    for (const run of this.store.runs().filter(r => ['QUEUED','RUNNING'].includes(r.status))) this.store.saveRun({ ...run, status: 'INTERRUPTED', error: '服务重启，上次任务已中断', finishedAt: now() });
  }
  envelope(data, message = '成功') { return { code: 200, success: true, message, msg: message, serverTime: now(), responseTime: Date.now(), data }; }
  token(request) {
    const cookie = /(?:^|;\s*)gov_session=([^;]+)/.exec(request.headers.cookie || '')?.[1];
    return cookie || /^Bearer\s+(.+)$/i.exec(request.headers.authorization || '')?.[1] || '';
  }
  user(request) { return this.store.userForToken(this.token(request)); }
  cookie(response, token) { response.setHeader('Set-Cookie', `gov_session=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800`); }
  admin(user) { requireValue(user?.role === 'admin', '此操作需要管理员权限', 403); }
  issue(user, response) { const token = this.store.session(user.id); this.cookie(response, token); return user; }
  account(user) { return { id: user.id, userName: user.name, accountName: user.name, nickName: user.name, officeId: 'local-office', officeName: '本地工作空间', officeCode: 'LOCAL', authOfficeCode: 'LOCAL', deptCode: 'LOCAL', deptName: '数据治理', officeParentIds: [], config: {}, detail: {}, details: {}, accountInfoMap: {}, loginTime: new Date().toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'}), projectId: 'local-project', envType: '0', role: user.role, authNum: 0, num: 1, img: '' }; }
  saveSource(data, id) {
    const existing = id ? this.store.get('sources', id) : null;
    if (id) requireValue(existing, '数据源不存在', 404);
    const type = String(data.type || existing?.type || '').toLowerCase();
    requireValue(['sqlite','mysql','postgresql','postgres'].includes(type), '支持SQLite、MySQL和PostgreSQL');
    requireValue(!existing || String(existing.type).toLowerCase() === type, '已有数据源不能变更数据库类型');
    const value = { ...existing, name: data.name || data.nameAlias || existing?.name, type, allowWrite: data.allowWrite === undefined ? existing?.allowWrite === true : data.allowWrite === true, hierarchy: data.hierarchy || existing?.hierarchy || '汇聚库', hierarchyId: data.hierarchyId || existing?.hierarchyId || '604' };
    requireValue(typeof value.name === 'string' && value.name.trim() && value.name.length <= 120, '请输入数据源名称');
    value.nameAlias = value.name;
    if (type === 'sqlite') {
      value.file = existing?.file || randomUUID() + '.sqlite';
      const db = new DatabaseSync(path.join(this.store.dir, 'sources', value.file)); db.close();
    } else {
      value.host = data.host || data.ipAddress || existing?.host;
      value.port = Number(data.port || existing?.port || (type === 'mysql' ? 3306 : 5432));
      value.user = data.user || data.userName || existing?.user;
      value.database = data.database || existing?.database;
      value.tls = data.tls === undefined ? existing?.tls === true : data.tls === true;
      requireValue(typeof value.host === 'string' && value.host.length < 254 && !/[\s/@?#]/.test(value.host), '数据库主机地址无效');
      requireValue(Number.isInteger(value.port) && value.port > 0 && value.port <= 65535, '数据库端口无效');
      requireValue(typeof value.user === 'string' && value.user && typeof value.database === 'string' && value.database, '请输入数据库名和用户名');
      const password = data.password ?? data.passwd;
      if (password != null && password !== '') value.passwordSecret = this.store.encrypt(password);
    }
    return this.store.save('sources', value, id);
  }
  saveEntity(kind, data, id) {
    if (id) requireValue(this.store.get(kind, id), '记录不存在', 404);
    if (kind === 'sources') return this.saveSource(data, id);
    const value = { ...(id ? this.store.get(kind, id) : {}), ...data };
    requireValue(typeof (value.name || value.name2 || value.templateName || value.gzlName || value.projectName || value.resourceName) === 'string' && (value.name || value.name2 || value.templateName || value.gzlName || value.projectName || value.resourceName).trim(), '请输入名称');
    if (kind === 'workflows') { const graph = validateWorkflow(value); delete graph.order; return this.store.save(kind, { ...graph, gzlName: graph.name }, id); }
    if (kind === 'rules') requireValue(['required','unique','regex','range','enum'].includes(value.type) && typeof value.field === 'string' && value.field.trim(), '质量规则需要字段和支持的检查类型');
    if (kind === 'services') {
      requireValue(value.sourceId && value.table, '数据服务需要数据源和表');
      requireValue(this.store.get('sources', value.sourceId), '数据源不存在', 404);
      delete value.apiKeyHash; delete value.apiKey; value.apiKeyHash = id ? this.store.get(kind,id).apiKeyHash : undefined;
      value.published = false;
    }
    return this.store.save(kind, value, id);
  }
  startRun(workflow, user) {
    this.admin(user); validateWorkflow(workflow);
    requireValue(this.active.size < 2, '已有两个任务运行，请完成后再执行', 429);
    const id = randomUUID(), run = { id, workflowId: workflow.id, name: workflow.name || workflow.gzlName, status: 'RUNNING', createTime: now(), startedAt: now(), steps: [], reports: [], actor: user.name };
    this.store.saveRun(run); this.store.audit(user.name, 'run.start', id, { workflowId: workflow.id });
    const worker = new Worker(new URL('./job-worker.mjs', import.meta.url), { workerData: { dataDir: this.store.dir, workflow }, resourceLimits: { maxOldGenerationSizeMb: 192 } });
    const timeoutMs = Math.min(45000, Math.max(500, Number(process.env.JOB_TIMEOUT_MS) || 45000));
    const timeout = setTimeout(() => this.stopRun(id, 'TIMED_OUT', `执行超过${timeoutMs/1000}秒，任务已停止`), timeoutMs);
    this.active.set(id, { worker, timeout });
    worker.on('message', event => {
      if (!this.active.has(id)) return;
      const current = this.store.run(id);
      if (event.type === 'progress') {
        const steps = current.steps.filter(x => x.nodeId !== event.step.nodeId); steps.push(event.step);
        this.store.saveRun({ ...current, steps });
      } else if (event.type === 'result') {
        try {
          const { rows, ...result } = event.result;
          this.store.saveRows(id, rows);
          this.store.saveRun({ ...current, ...result, status: 'SUCCESS', finishedAt: now() });
          this.store.audit(user.name, 'run.complete', id, { sourceCount: result.sourceCount, outputCount: result.outputCount });
          this.releaseRun(id);
        } catch (error) { this.failRun(id, '保存运行结果失败'); }
      } else if (event.type === 'failed') this.failRun(id, event.message);
    });
    worker.on('error', () => this.failRun(id, '执行进程异常，任务失败'));
    worker.on('exit', code => { if (this.active.has(id)) this.failRun(id, `执行进程提前退出（${code}）`); });
    return run;
  }
  releaseRun(id) { const entry = this.active.get(id); if (entry) clearTimeout(entry.timeout); this.active.delete(id); }
  failRun(id, error) { if (!this.active.has(id)) return; const run = this.store.run(id); this.store.saveRun({ ...run, status: 'FAILED', error, finishedAt: now() }); this.store.audit(run.actor, 'run.failed', id, { error }); this.releaseRun(id); }
  stopRun(id, status = 'CANCELLED', error = '用户取消执行') {
    const entry = this.active.get(id); requireValue(entry, '任务已经结束或不存在', 409);
    const run = this.store.run(id); this.store.saveRun({ ...run, status, error, finishedAt: now() }); this.store.audit(run.actor, 'run.stop', id, { status });
    this.releaseRun(id); void entry.worker.terminate(); return this.store.run(id);
  }
  async close() { for (const id of [...this.active.keys()]) { const worker = this.active.get(id).worker; this.stopRun(id, 'INTERRUPTED', '服务停止'); await worker.terminate(); } this.store.close(); }
  async handle(request, response, url, readBody, sendJson) {
    const send = (data, message) => { response.setHeader('X-Governance-Backend', 'live'); sendJson(response, 200, this.envelope(data, message)); };
    try {
      const host = request.headers.host || '';
      requireValue(/^(127\.0\.0\.1|localhost|\[::1\]):\d+$/.test(host), '仅允许本机地址访问', 403);
      const origin = request.headers.origin;
      requireValue(!origin || origin === `http://${host}`, '请求来源不允许', 403);
      requireValue(!['cross-site','same-site'].includes(request.headers['sec-fetch-site']), '仅允许同源请求', 403);
      const method = request.method || 'GET', p = url.pathname;
      if (p === '/api/health' && method === 'GET') { send({ mode: 'live', version: '2.0.0', dataDir: path.basename(this.store.dir), connectors: ['SQLite','MySQL','PostgreSQL'], nodeTypes: NODE_TYPES }); return; }
      let body = {};
      if (!['GET','HEAD'].includes(method)) {
        const raw = await readBody(request); const type = request.headers['content-type'] || '';
        if (raw.length) {
          if (type.includes('application/json')) { try { body = JSON.parse(raw.toString()); } catch { throw new AppError('请求JSON格式错误'); } }
          else if (type.includes('application/x-www-form-urlencoded')) body = Object.fromEntries(new URLSearchParams(raw.toString()));
          else throw new AppError('请使用JSON或表单请求');
          requireValue(body && typeof body === 'object' && !Array.isArray(body), '请求体必须为对象');
        }
      }
      let user = this.user(request);
      if (p === '/api/auth/local-session' && method === 'POST') {
        requireValue(origin === `http://${host}`, '本机会话只能由当前页面创建', 403);
        requireValue(process.env.LOCAL_AUTO_LOGIN !== 'false', '本机自动登录已关闭，请使用账号密码登录', 403);
        if (!user) { const admin = this.store.db.prepare("SELECT id,name,role FROM users WHERE role='admin' ORDER BY name LIMIT 1").get(); user = this.issue(admin, response); }
        send(user); return;
      }
      if (p === '/api/auth/login' && method === 'POST') {
        const key = request.socket.remoteAddress || 'local', state = this.loginAttempts.get(key) || { count: 0, until: Date.now() + 60000 };
        if (state.until < Date.now()) { state.count = 0; state.until = Date.now() + 60000; }
        requireValue(state.count < 10, '登录尝试过多，请稍后再试', 429); state.count++; this.loginAttempts.set(key,state);
        user = this.store.authenticate(body.name || body.username, body.password);
        requireValue(user, '账号或密码错误', 401); this.loginAttempts.delete(key); this.issue(user, response); this.store.audit(user.name,'auth.login',user.id); send(user); return;
      }
      if (p.startsWith('/api/published/') && method === 'GET') {
        const id = p.split('/')[3], service = this.store.get('services',id), key = request.headers['x-api-key'];
        requireValue(service?.published && typeof key === 'string' && key.length <= 256 && service.apiKeyHash === hash(key), '服务未发布或授权密钥无效', 403);
        const bucket = this.serviceUsage.get(id) || { count: 0, since: Date.now() };
        if (Date.now() - bucket.since > 60000) { bucket.count = 0; bucket.since = Date.now(); }
        requireValue(bucket.count < 60, '服务调用超过每分钟60次',429); bucket.count++; this.serviceUsage.set(id,bucket);
        const result = await previewRows(this.store,service,Object.fromEntries(url.searchParams));
        if (Array.isArray(service.fields) && service.fields.length) result.list = result.list.map(row=>Object.fromEntries(service.fields.map(field=>[field,row[field]])));
        this.store.audit('api-key','service.query',id); send(result); return;
      }
      requireValue(user, '请登录后操作', 401);
      const params = { ...Object.fromEntries(url.searchParams), ...body };
      if (p === '/api/auth/me' && method === 'GET') { send(user); return; }
      if (p === '/api/auth/logout' && method === 'POST') { this.store.revoke(this.token(request)); response.setHeader('Set-Cookie','gov_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'); send(null); return; }
      if (p === '/api/auth/users') {
        this.admin(user);
        if (method === 'GET') send(this.store.db.prepare('SELECT id,name,role FROM users ORDER BY name').all());
        else if (method === 'POST') { const value = this.store.createUser(body.name,body.password,body.role); this.store.audit(user.name,'user.create',value.id); send(value); }
        else throw new AppError('此请求方法不支持',405);
        return;
      }
      if (p === '/api/governance/audit' && method === 'GET') { this.admin(user); send(this.store.audits(params.limit)); return; }
      if (p === '/api/governance/shutdown' && method === 'POST') { this.admin(user); this.store.audit(user.name,'server.stop','local'); send(null,'本地服务正在停止'); setTimeout(()=>this.onShutdown?.(),150); return; }
      if (p === '/api/governance/summary' && method === 'GET') {
        send({ sources: this.store.all('sources').length, workflows: this.store.all('workflows').length, assets: this.store.all('assets').length, rules: this.store.all('rules').length, runs: this.store.runs().length, running: this.active.size }); return;
      }
      const match = /^\/api\/governance\/([\w-]+)(?:\/([^/]+))?(?:\/([\w-]+))?$/.exec(p);
      if (match) {
        let [, kind, id, action] = match; id = id ? decodeURIComponent(id) : undefined;
        if (kind === 'runs') {
          if (id) requireValue(this.store.run(id), '运行记录不存在',404);
          if (action === 'cancel' && method === 'POST') { this.admin(user); send(this.stopRun(id)); }
          else if (action === 'rows' && method === 'GET') { const paging = page([],params); send(this.store.rows(id,paging.pageNum,paging.pageSize)); }
          else if (action === 'export' && method === 'GET') {
            const rows = this.store.rows(id,1,10000).list, keys = Object.keys(rows[0] || {});
            const quote = value => '"' + String(value ?? '').replace(/^\s*[=+@-]/,'\'$&').replaceAll('"','""') + '"';
            const csv = '\uFEFF' + [keys.map(quote).join(','),...rows.map(row=>keys.map(key=>quote(row[key])).join(','))].join('\r\n');
            response.writeHead(200, { 'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="governance-${id}.csv"`,'Cache-Control':'no-store' }); response.end(csv);
          } else if (method === 'GET' && !action) send(id ? this.store.run(id) : page(this.store.runs(),params));
          else throw new AppError('运行记录接口不支持该操作',405);
          return;
        }
        requireValue(KINDS.has(kind), '未知资源类型',404);
        if (id) requireValue(this.store.get(kind,id), '记录不存在',404);
        if (kind === 'sources' && action) {
          if (action === 'test' && method === 'POST') { await withConnection(this.store,id,c=>c.query('SELECT 1 AS connected')); this.store.save('sources',{ connectionStatus:'1',lastTestAt:now() },id); send({ connected:true }); }
          else if (action === 'tables' && method === 'GET') send(await tables(this.store,id));
          else if (action === 'columns' && method === 'GET') send(await columns(this.store,id,params.table));
          else if (action === 'sync' && method === 'POST') {
            this.admin(user); const list = await tables(this.store,id), records = [];
            for (const table of list) {
              const fields = await columns(this.store,id,table.qualifiedName);
              records.push({ id:hash(id + ':' + table.qualifiedName).slice(0,32), name:table.qualifiedName, name2:table.name, dataBaseId:id, sourceId:id, columns:fields, schemaName:table.schema });
            }
            this.store.transaction(()=>{ for (const old of this.store.all('tables').filter(t=>t.sourceId===id)) this.store.remove('tables',old.id); for (const record of records) this.store.save('tables',record); });
            this.store.audit(user.name,'source.sync',id,{tables:records.length}); send(records);
          }
          else if (action === 'preview' && method === 'GET') send(await previewRows(this.store,{sourceId:id,table:params.table,sql:params.sql},params));
          else if (action === 'import' && method === 'POST') { this.admin(user); requireValue(Array.isArray(body.rows) && body.rows.length <= 10000,'需要不超过10000行的记录数组'); const result = await writeNewTable(this.store,id,body.table,body.rows); this.store.audit(user.name,'source.import',id,{table:body.table,rows:body.rows.length}); send(result); }
          else throw new AppError('数据源接口不支持该操作',405);
          return;
        }
        if (kind === 'workflows' && action === 'run' && method === 'POST') { send(this.startRun(this.store.get(kind,id),user)); return; }
        if (kind === 'qualityTasks' && action === 'run' && method === 'POST') {
          const task = this.store.get(kind,id); const nodes = [{id:'source',type:'source',config:{sourceId:task.sourceId,table:task.table}},{id:'quality',type:'quality',config:{ruleIds:task.ruleIds}},{id:'output',type:'output',config:{}}];
          send(this.startRun({ id:task.id,name:task.name,nodes,edges:[{source:'source',target:'quality'},{source:'quality',target:'output'}] },user)); return;
        }
        if (kind === 'services' && action === 'publish' && method === 'POST') {
          this.admin(user); const key = randomBytes(24).toString('hex'); const service = this.store.get(kind,id);
          const fields = await columns(this.store,service.sourceId,service.table);
          requireValue(fields.length > 0, '数据表不存在或没有字段');
          requireValue(!service.fields || Array.isArray(service.fields) && service.fields.every(name=>fields.some(field=>field.name===name)), '发布字段不在数据表中');
          this.store.save(kind,{...service,published:true,apiKeyHash:hash(key)},id); this.store.audit(user.name,'service.publish',id);
          send({ id,endpoint:`/api/published/${id}/query`,apiKey:key },'服务已发布，密钥仅本次显示'); return;
        }
        if (action) throw new AppError('未实现的资源操作',501);
        const visible = record => kind === 'sources' ? publicSource(record) : kind === 'services' ? (({apiKeyHash,...rest})=>rest)(record) : record;
        if (method === 'GET') send(id ? visible(this.store.get(kind,id)) : page(this.store.all(kind).map(visible),params));
        else {
          this.admin(user);
          if (method === 'POST' && !id) { const value=this.saveEntity(kind,body); this.store.audit(user.name,`${kind}.create`,value.id); send(visible(value)); }
          else if (['PUT','PATCH'].includes(method) && id) { const value=this.saveEntity(kind,body,id); this.store.audit(user.name,`${kind}.update`,id); send(visible(value)); }
          else if (method === 'DELETE' && id) {
            if (kind === 'sources') requireValue(!this.store.all('workflows').some(w=>w.nodes?.some(n=>n.config?.sourceId===id)) && !this.store.all('services').some(s=>s.sourceId===id) && !this.store.all('qualityTasks').some(t=>t.sourceId===id), '数据源仍被流程、检测任务或服务引用',409);
            this.store.remove(kind,id); this.store.audit(user.name,`${kind}.delete`,id); send(null);
          } else throw new AppError('请求方法不支持',405);
        }
        return;
      }
      if (await legacy(this,{ request,response,url,body,params,user,send })) return;
      throw new AppError(`该接口尚未实现：${p}`,501);
    } catch (error) {
      const status = error instanceof AppError ? error.status : 500;
      if (!response.headersSent) sendJson(response,status,{code:status,success:false,message:error instanceof AppError?error.message:'后端处理异常',msg:error instanceof AppError?error.message:'后端处理异常'});
    }
  }
}
