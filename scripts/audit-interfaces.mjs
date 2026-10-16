// Read-only interface inventory. Never runs workflows, writes configurations, or contacts user business databases.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = 'http://127.0.0.1:' + (process.env.PORT || '4173');
const manifest = JSON.parse(await readFile(path.join(project,'mock/manifest.json'),'utf8'));
const session = await fetch(base+'/api/auth/local-session',{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:'{}'});
if (!session.ok) throw Error('本机会话不可用，请使用已有会话执行审计');
const cookie = session.headers.get('set-cookie').split(';')[0];
async function probe(method,pathname,query=[],body) {
  const url=new URL(pathname,base);for(const [key,value] of query)url.searchParams.append(key,value);
  const response=await fetch(url,{method,headers:{Cookie:cookie,Origin:base,...(method==='POST'?{'Content-Type':'application/json'}:{})},body:method==='POST'?JSON.stringify(body||Object.fromEntries(query)):undefined,signal:AbortSignal.timeout(5000)});
  const type=response.headers.get('content-type')||'';
  const payload=type.includes('json')?await response.json():null;
  const data=payload?.data;
  return {method,path:pathname,status:response.status,code:payload?.code??null,message:payload?.message||payload?.msg||'',dataShape:Array.isArray(data)?'array':data&&typeof data==='object'?Object.keys(data).sort().join(','):data===null?'null':typeof data,total:data?.total??data?.totalElements??null,binary:!type.includes('json')};
}
const unique=new Map();for(const entry of manifest.apiEntries){const key=entry.method+' '+entry.path;if(!unique.has(key))unique.set(key,entry);}
const legacy=[];
for (const entry of unique.values()) {
  const safePost=/\/(?:isLoginedByToken|getTreeResources|getAccount|getAllNumOfOnLine|getCurrentJobType.*|query[^/]*|select[^/]*|find[^/]*|get[^/]*|detail|obtainProcess|apiCallTrend|permissionPerson|bxyqueryQcListsx|alarmResults|result|impactAnalysis|conversionAnalysis|traceabilityAnalysis|inheritAnalysis|taskListByTablesId)$/.test(entry.path);
  if(entry.method!=='GET'&&!(entry.method==='POST'&&safePost)){legacy.push({method:entry.method,path:entry.path,status:null,message:'未执行：避免潜在业务写操作'});continue;}
  try{legacy.push({...await probe(entry.method,entry.path,entry.query),namespace:entry.path.split('/')[2]});}
  catch(error){legacy.push({method:entry.method,path:entry.path,status:null,message:error.name==='TimeoutError'?'请求超时':'请求失败'});}
}
const kinds=['sources','workflows','elements','businessTypes','qualifiers','dictionaries','catalogs','assets','rules','qualityTasks','services','projects','tables'];
const modern=[];
for(const route of ['/api/health','/api/auth/me','/api/governance/summary','/api/auth/users','/api/governance/audit',...kinds.map(k=>'/api/governance/'+k)])modern.push(await probe('GET',route));
const sources=await fetch(base+'/api/governance/sources?pageSize=500',{headers:{Cookie:cookie}}).then(r=>r.json());
const sourceSummary=sources.data.list.map(({id,name,type,demo})=>({id,name,type,demo:Boolean(demo)}));
if(sourceSummary.some(s=>s.id==='demo-source'&&s.demo&&s.type.toLowerCase()==='sqlite'))for(const suffix of ['tables','columns?table=demo_records','preview?table=demo_records&pageSize=2'])modern.push(await probe('GET','/api/governance/sources/demo-source/'+suffix));
const runResponse=await fetch(base+'/api/governance/runs?pageSize=100',{headers:{Cookie:cookie}}).then(r=>r.json());
const runSummary=runResponse.data.list.map(({id,workflowId,name,status,sourceCount,outputCount,reports})=>({id,workflowId,name,status,sourceCount,outputCount,invalidRows:reports?.at(-1)?.invalidRows}));
const sample=runSummary.find(r=>r.workflowId==='demo-workflow'&&r.status==='SUCCESS');
if(sample)for(const suffix of ['', '/rows','/export'])modern.push(await probe('GET','/api/governance/runs/'+sample.id+suffix));
const templates=[];
const add=(method,path,purpose)=>templates.push({method,path,purpose});
for(const [method,route] of [['GET','/api/health'],['POST','/api/auth/local-session'],['POST','/api/auth/login'],['GET','/api/auth/me'],['POST','/api/auth/logout'],['GET','/api/auth/users'],['POST','/api/auth/users']])add(method,route,'身份或健康检查');
for(const kind of kinds)for(const [method,suffix] of [['GET',''],['POST',''],['GET','/{id}'],['PUT','/{id}'],['PATCH','/{id}'],['DELETE','/{id}']])add(method,'/api/governance/'+kind+suffix,'资源配置CRUD');
for(const [method,action] of [['POST','test'],['GET','tables'],['GET','columns'],['GET','preview'],['POST','sync'],['POST','import']])add(method,'/api/governance/sources/{id}/'+action,'数据源操作');
for(const [method,route,purpose] of [['POST','/api/governance/workflows/{id}/run','流程执行'],['POST','/api/governance/qualityTasks/{id}/run','质量检测'],['GET','/api/governance/runs','运行列表'],['GET','/api/governance/runs/{id}','运行详情'],['POST','/api/governance/runs/{id}/cancel','取消任务'],['GET','/api/governance/runs/{id}/rows','结果分页'],['GET','/api/governance/runs/{id}/export','结果导出'],['GET','/api/governance/summary','资源统计'],['GET','/api/governance/audit','操作审计'],['POST','/api/governance/shutdown','停止服务'],['POST','/api/governance/services/{id}/publish','服务发布'],['GET','/api/published/{id}/query','授权查询']])add(method,route,purpose);
const tally=rows=>rows.reduce((a,row)=>{const key=row.status??'notProbed';a[key]=(a[key]||0)+1;return a;},{});
const namespaces={};for(const row of legacy){const key=row.namespace||row.path.split('/')[2];namespaces[key]??={paths:0,statuses:{}};namespaces[key].paths++;const code=row.status??'notProbed';namespaces[key].statuses[code]=(namespaces[key].statuses[code]||0)+1;}
const result={checkedAt:new Date().toISOString(),base,legacyRecords:manifest.apiEntries.length,legacyPaths:unique.size,modernOperations:templates.length,modernPathTemplates:new Set(templates.map(x=>x.path)).size,legacyStatus:tally(legacy),modernStatus:tally(modern),namespaces,sourceSummary,runSummary,legacy,modern,templates};
await mkdir(path.join(project,'docs'),{recursive:true});
await writeFile(path.join(project,'docs/interface-audit.json'),JSON.stringify(result,null,2));
const statusNote=row=>row.status===200?(row.binary?'静态图片或导出响应':'有响应，需结合业务语义判断'):row.status===501?'明确未实现':row.status===404?'原ID不存在，或动作路径误入详情路由':row.status===400?'需要有效参数，或请求结构尚不兼容':row.message;
const lines=['# 接口实测清单','',`检查基址：${base}。时间：${new Date().toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'})}（北京时间）。`,'','检查只读取配置和本地示例库，不执行业务任务、不修改配置、不读取用户业务数据库。写接口功能由隔离的自动测试验证。','','## 新后端读取接口','', '| 方法 | 路径 | HTTP | 返回结构 / 说明 |','| --- | --- | --- | --- |',...modern.map(r=>`| ${r.method} | \`${r.path}\` | ${r.status} | ${r.dataShape} ${r.total==null?'':'；总数'+r.total} |`),'','## 新后端完整方法与路径模板','',`共${templates.length}个方法×路径模板；其中${kinds.length*6}个来自${kinds.length}类通用资源CRUD。数量不代表独立业务完成比例。`,'','| 方法 | 路径 | 职责 |','| --- | --- | --- |',...templates.map(r=>`| ${r.method} | \`${r.path}\` | ${r.purpose} |`),'','## 原接口逐条检查','',`原${manifest.apiEntries.length}条记录对应${unique.size}个不重复方法与具体路径，含带ID路径和图片。`,'','200不等于完整实现；部分统计返回固定空结构。404不能全部判定为数据缺失，未知动作可能被通用详情路由误识别。POST查询缺少原请求正文时使用空对象，400可能源于参数。','', '| 方法 | 原路径 | HTTP | 本次检查说明 |','| --- | --- | --- | --- |',...legacy.map(r=>`| ${r.method} | \`${r.path}\` | ${r.status??'未探测'} | ${statusNote(r)}${r.message&&r.status!==200?'；'+r.message.replaceAll('|','/'):''} |`)];
await writeFile(path.join(project,'docs/接口实测清单.md'),lines.join('\n'));
console.log(JSON.stringify({legacyStatus:result.legacyStatus,modernStatus:result.modernStatus,modernOperations:templates.length,modernPathTemplates:result.modernPathTemplates,namespaces,sourceSummary,runSummary},null,2));
