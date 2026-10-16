import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { Store, page } from '../backend/store.mjs';
import { identifier, readSql } from '../backend/connectors.mjs';
import { validateWorkflow } from '../backend/engine.mjs';

const dir = await mkdtemp(path.join(os.tmpdir(),'governance-test-'));
const project = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let child, base, cookie, adminPassword = 'Test-only-admin-2026', failureLog = '';
async function launch() {
  child=spawn(process.execPath,['server.mjs'],{cwd:project,env:{...process.env,PORT:'0',DATA_DIR:dir,ADMIN_PASSWORD:adminPassword,JOB_TIMEOUT_MS:'1200'},stdio:['ignore','pipe','pipe'],windowsHide:true});
  child.stderr.on('data',data=>failureLog+=data.toString());
  base=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('服务启动超时 '+failureLog)),10000);child.stdout.on('data',data=>{const match=/已启动：(http:\/\/127\.0\.0\.1:\d+)/.exec(data.toString());if(match){clearTimeout(timer);resolve(match[1])}});child.once('exit',code=>{clearTimeout(timer);reject(Error('服务退出 '+code+' '+failureLog))})});
}
async function stop() { if(!child||child.exitCode!=null)return;const exited=new Promise(resolve=>child.once('exit',resolve));child.kill('SIGTERM');await exited; }
async function request(route,method='GET',body,session=cookie,headers={}) {
  const response=await fetch(base+route,{method,headers:{...(session?{Cookie:session}:{}),...(body?{'Content-Type':'application/json'}:{}),...headers},body:body?JSON.stringify(body):undefined});
  const json=await response.json();return {response,json,data:json.data};
}
async function waitRun(id) {for(let attempt=0;attempt<100;attempt++){const result=await request('/api/governance/runs/'+id);if(result.data.status!=='RUNNING')return result.data;await new Promise(resolve=>setTimeout(resolve,50));}throw Error('任务未结束');}
before(async()=>{await launch();const session=await request('/api/auth/local-session','POST',{},null,{Origin:base});cookie=session.response.headers.get('set-cookie').split(';')[0];});
after(stop);

test('真实模式拒绝无会话请求和跨域请求',async()=>{
  const denied=await request('/api/governance/sources','GET',undefined,null);assert.equal(denied.response.status,401);
  const cross=await request('/api/auth/local-session','POST',{},null,{Origin:'https://example.invalid'});assert.equal(cross.response.status,403);
  const missing=await request('/api/not-implemented','POST',{});assert.equal(missing.response.status,501);assert.equal(missing.json.success,false);
});
test('标准配置支持真实CRUD、分页和原页面响应结构',async()=>{
  const created=await request('/api/standard/metadata/dataElement','POST',{name:'TEST',name2:'测试数据元',code:'TEST-001',version:'1.0'});assert.equal(created.response.status,200);
  const id=created.data.id;const changed=await request('/api/standard/metadata/dataElement','PUT',{id,name:'TEST',name2:'已修改数据元'});assert.equal(changed.data.name2,'已修改数据元');
  const list=await request('/api/standard/metadata/dataElement/queryPage?searchContent='+encodeURIComponent('已修改'));assert.equal(list.data.totalElements,1);assert.equal(list.data.content[0].id,id);
  const deleted=await request('/api/standard/metadata/dataElement/'+id,'DELETE');assert.equal(deleted.response.status,200);
  assert.equal((await request('/api/standard/metadata/dataElement/'+id)).response.status,404);
  const paged=page([{name:'甲'},{name:'乙'},{name:'丙'}],{pageNumber:2,pageSize:1});assert.deepEqual(paged.content,[{name:'乙'}]);
});
test('数据库元数据和预览从真实SQLite读取，拒绝写SQL和非法表名',async()=>{
  assert.equal((await request('/api/governance/sources/demo-source/test','POST',{})).data.connected,true);
  const tables=await request('/api/governance/sources/demo-source/tables');assert.equal(tables.data[0].name,'demo_records');
  const columns=await request('/api/governance/sources/demo-source/columns?table=demo_records');assert.equal(columns.data.length,5);
  const preview=await request('/api/governance/sources/demo-source/preview?table=demo_records&pageSize=3&pageNum=2');assert.equal(preview.data.total,8);assert.equal(preview.data.list[0].id,4);
  assert.throws(()=>readSql('DELETE FROM demo_records'),/只允许/);assert.throws(()=>readSql('SELECT 1; DROP TABLE demo_records'),/只允许/);assert.throws(()=>identifier('demo_records;drop'),/字符/);
  const bad=await request('/api/governance/sources/demo-source/preview?sql='+encodeURIComponent('DELETE FROM demo_records'));assert.equal(bad.response.status,400);
  const bigSql='SELECT a.id AS a,b.id AS b FROM demo_records a CROSS JOIN demo_records b CROSS JOIN demo_records c CROSS JOIN demo_records d CROSS JOIN demo_records e';
  const bigPreview=await request('/api/governance/sources/demo-source/preview?pageSize=2&sql='+encodeURIComponent(bigSql));assert.equal(bigPreview.data.total,32768);assert.equal(bigPreview.data.list.length,2);
});
test('MySQL连接口令加密保存且不会从接口泄漏',async()=>{
  const created=await request('/api/governance/sources','POST',{name:'待联调MySQL',type:'mysql',host:'127.0.0.1',port:3306,database:'test',user:'test_user',password:'TEST-secret-no-real-credential'});
  assert.equal(created.response.status,200);assert.equal(created.data.hasPassword,true);assert.equal(created.data.passwordSecret,undefined);assert.equal(created.data.password,'');
  const store=new Store(dir);const source=store.get('sources',created.data.id);assert.equal(store.decrypt(source.passwordSecret),'TEST-secret-no-real-credential');assert.ok(!JSON.stringify(source).includes('TEST-secret-no-real-credential'));store.close();
});
test('流程真实执行清洗、去重、质量检查并生成结果和统计',async()=>{
  const started=await request('/api/governance/workflows/demo-workflow/run','POST',{});assert.equal(started.response.status,200);
  const run=await waitRun(started.data.id);assert.equal(run.status,'SUCCESS',run.error);assert.equal(run.sourceCount,8);assert.equal(run.outputCount,7);assert.equal(run.reports[0].invalidRows,2);assert.equal(run.steps.length,5);
  const rows=await request('/api/governance/runs/'+run.id+'/rows');assert.equal(rows.data.total,7);assert.equal(rows.data.list[0].org_name,'示例单位甲');
  const overview=await request('/api/track/api/monitor/instanceOverview/today');assert.ok(overview.data.SUCCESS>=1);
  const quality=await request('/api/ztOtherQuality/qualitySummary/selectByResultSummary');assert.equal(quality.data.ruleCount.ruleTotal,2);
});
test('无效连线、字段错误不会报告成功，写入新表后可查询且拒绝覆盖',async()=>{
  const graph=(await request('/api/governance/workflows/demo-workflow')).data;
  assert.throws(()=>validateWorkflow({...graph,edges:[...graph.edges,{source:'n5',target:'n1'}]}));
  const bad=structuredClone(graph);delete bad.id;bad.name='字段错误流程';bad.nodes[1].config.fields=['unknown_column'];
  const saved=await request('/api/governance/workflows','POST',bad);const started=await request('/api/governance/workflows/'+saved.data.id+'/run','POST',{});const failed=await waitRun(started.data.id);assert.equal(failed.status,'FAILED');assert.match(failed.error,/字段/);
  const output=structuredClone(graph);delete output.id;output.name='新表输出流程';output.nodes.at(-1).config={sourceId:'demo-source',table:'governed_records'};
  const newFlow=await request('/api/governance/workflows','POST',output);const first=await request('/api/governance/workflows/'+newFlow.data.id+'/run','POST',{});assert.equal((await waitRun(first.data.id)).status,'SUCCESS');
  const result=await request('/api/governance/sources/demo-source/preview?table=governed_records');assert.equal(result.data.total,7);
  const again=await request('/api/governance/workflows/'+newFlow.data.id+'/run','POST',{});assert.equal((await waitRun(again.data.id)).status,'FAILED');assert.equal((await request('/api/governance/sources/demo-source/preview?table=governed_records')).data.total,7);
});
test('只读用户能查询但不能修改配置或执行任务',async()=>{
  await request('/api/auth/users','POST',{name:'readonly_test',password:'Test-reader-2026',role:'reader'});
  const login=await request('/api/auth/login','POST',{name:'readonly_test',password:'Test-reader-2026'},null);const reader=login.response.headers.get('set-cookie').split(';')[0];
  assert.equal((await request('/api/governance/workflows','GET',undefined,reader)).response.status,200);
  assert.equal((await request('/api/governance/workflows/demo-workflow/run','POST',{},reader)).response.status,403);
  assert.equal((await request('/api/governance/elements','POST',{name:'x'},reader)).response.status,403);
});
test('耗时质量规则可超时或取消，HTTP服务保持可响应',async()=>{
  const flow={name:'超时验证',nodes:[{id:'a',type:'source',config:{sourceId:'demo-source',sql:"SELECT '"+'a'.repeat(1000)+"!' AS org_name"}},{id:'b',type:'quality',config:{rules:[{type:'regex',field:'org_name',pattern:'(a+)+$'}]}},{id:'c',type:'output',config:{}}],edges:[{source:'a',target:'b'},{source:'b',target:'c'}]};
  const saved=await request('/api/governance/workflows','POST',flow);
  const started=await request('/api/governance/workflows/'+saved.data.id+'/run','POST',{});
  assert.equal((await request('/api/health','GET',undefined,null)).response.status,200);
  assert.equal((await waitRun(started.data.id)).status,'TIMED_OUT');
  const again=await request('/api/governance/workflows/'+saved.data.id+'/run','POST',{});
  const cancelled=await request('/api/governance/runs/'+again.data.id+'/cancel','POST',{});assert.equal(cancelled.data.status,'CANCELLED');
});
test('数据服务需要真实密钥，查询结果来自数据库，审计保存调用',async()=>{
  const created=await request('/api/governance/services','POST',{name:'示例查询服务',sourceId:'demo-source',table:'demo_records',fields:['record_code','org_name']});
  const published=await request('/api/governance/services/'+created.data.id+'/publish','POST',{});assert.equal(published.response.status,200);
  assert.equal((await request(published.data.endpoint,'GET',undefined,null)).response.status,403);
  const queried=await request(published.data.endpoint+'?pageSize=2','GET',undefined,null,{'X-API-Key':published.data.apiKey});assert.equal(queried.data.total,8);assert.equal(queried.data.list.length,2);assert.deepEqual(Object.keys(queried.data.list[0]),['record_code','org_name']);
  assert.equal((await request('/api/governance/services/'+created.data.id)).data.apiKeyHash,undefined);
});
test('配置和治理结果在后端重启后仍然存在',async()=>{
  const before=(await request('/api/governance/runs')).data.total;assert.ok(before>=4);await stop();await launch();
  const session=await request('/api/auth/local-session','POST',{},null,{Origin:base});cookie=session.response.headers.get('set-cookie').split(';')[0];
  assert.equal((await request('/api/governance/runs')).data.total,before);
  assert.equal((await request('/api/governance/services')).data.total,1);
  assert.ok((await request('/api/governance/audit')).data.some(x=>x.action==='service.query'));
});
test('管理员可通过停止接口正常关闭后端',async()=>{
  const exit=new Promise(resolve=>child.once('exit',resolve));
  const result=await request('/api/governance/shutdown','POST',{});assert.equal(result.response.status,200);
  await exit;assert.equal(child.exitCode,0);
});
