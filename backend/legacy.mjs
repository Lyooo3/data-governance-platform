import { AppError, requireValue, page, publicSource } from './store.mjs';
import { tables, columns, previewRows } from './connectors.mjs';

const ENTITY_ROUTES = [
  ['/api/standard/metadata/dataElement','elements'],
  ['/api/standard/metadata/businessType','businessTypes'],
  ['/api/standard/business/businessType','businessTypes'],
  ['/api/standard/metadata/qualifiers','qualifiers'],
  ['/api/standard/metadata/dictionary','dictionaries'],
  ['/api/resource/standardCatalog','catalogs'],
  ['/api/resource/dataResourceManage','assets'],
  ['/api/data-manage/database/dataBase','sources'],
  ['/api/ztOtherQuality/ruleTemplate','rules'],
  ['/api/ztOtherQuality/qualityTask','qualityTasks'],
  ['/api/data/handle/sjcl/gzl','workflows'],
  ['/api/apiService/apiManage','services'],
];

export async function legacy(backend, ctx) {
  const {request,url,params,body,user,send} = ctx, p = url.pathname, method = request.method, s = backend.store;
  const runs = () => s.runs(), count = kind => s.all(kind).length;
  if (p === '/api/login/login/isLoginedByToken' || p === '/api/login/login/isLogined') { send(true); return true; }
  if (p === '/api/login/login/getAccount' || p === '/api/xtgl/account/info/detail') { send(backend.account(user)); return true; }
  if (p === '/api/login/login/getAllNumOfOnLine') { send({number:s.db.prepare('SELECT count(*) AS count FROM sessions WHERE expires>?').get(Date.now()).count}); return true; }
  if (p === '/api/login/login/getTreeResources') {
    const name = String(params.clientName || params.headerMenuClientName || '');
    let menu;
    if (name === '数据标准') menu = backend.menus.find(list=>list.some(x=>x.resourceName === 'dtEle'));
    else if (name === '数据资产') menu = backend.menus.find(list=>list.some(x=>x.children?.some(y=>y.resourceName === 'standardPortal')));
    else if (name === '数据治理') menu = backend.menus.find(list=>list.some(x=>JSON.stringify(x).includes('质量概览')));
    else if (name.startsWith('数据服务')) menu = backend.menus.find(list=>list.some(x=>x.resourceName === 'apiMarket'));
    else menu = backend.menus.find(list=>list.some(x=>x.resourceName === 'zt-sjbz'));
    send(menu || []); return true;
  }
  if (p === '/api/tenant/tenantProject/queryAllProject') { send(s.all('projects')); return true; }
  if (p === '/api/tenant/account/info/permissionPerson') { send([{...backend.account(user),name:user.name}]); return true; }
  if (p === '/api/xtgl/oper/action/findOperActionsByAccIdAndOthers') { send(user.role === 'admin' ? ['add','edit','delete','export','publish','run'].map(name=>({id:name,btnCode:name,btnName:name,btnClass:name,resourceId:params.resourceId,actionName:name,actionCode:name,operActionName:name,operActionVal:name})) : []); return true; }
  if (p.startsWith('/api/xtgl/dict/')) {
    const type = String(params.type || params.dictType || '').toLowerCase();
    if (/db|database/.test(type)) send(['SQLite','MySQL','PostgreSQL'].map(name=>({name,code:name,id:name,children:[]})));
    else send(s.all('dictionaries').flatMap(d=>d.dictionaryDetails || []));
    return true;
  }
  if (p === '/api/track/api/monitor/instanceOverview/today' || p === '/api/track/api/monitor/instanceOverview') {
    const values = runs();
    const counts={TOTAL:values.length,SUCCESS:values.filter(x=>x.status==='SUCCESS').length,FAILURE:values.filter(x=>['FAILED','TIMED_OUT','INTERRUPTED'].includes(x.status)).length,RUNNING:values.filter(x=>x.status==='RUNNING').length,STOP:values.filter(x=>x.status==='CANCELLED').length,OTHER:0};
    send(p.endsWith('/today') ? counts : {totalCount:counts.TOTAL,taskCountDtos:[{taskStateType:'SUCCESS',count:counts.SUCCESS},{taskStateType:'FAILURE',count:counts.FAILURE},{taskStateType:'RUNNING_EXECUTION',count:counts.RUNNING},{taskStateType:'STOP',count:counts.STOP}]}); return true;
  }
  if (p === '/api/resource/bigScreen/dataresourceStatusCount') { send({registerNum:count('assets'),stopNum:s.all('assets').filter(x=>x.status==='stopped').length,logOffNum:0}); return true; }
  if (p === '/api/resource/bigScreen/dataresourceSjbzCount') { send({dataElement:count('elements'),dataElementTmp:0,dictionary:count('dictionaries'),dictionaryTmp:0,qualifiers:count('qualifiers'),qualifiersTmp:0,dataResource:count('catalogs')}); return true; }
  if (p === '/api/resource/bigScreen/dataresourceFjflCount') {
    const grouped=new Map();for(const item of s.all('assets')) {const key=item.dataLevelName||'未分类';grouped.set(key,(grouped.get(key)||0)+1);}
    send({dataLevelCount:[...grouped].map(([name,count])=>({name,code:name,count})),daorgFirstCount:[]}); return true;
  }
  if (p === '/api/resource/bigScreen/dataresourceLyxtCount' || p === '/api/resource/bigScreen/dataresourceLydqCount') { send([]); return true; }
  if (p === '/api/standard/overview/benchmarking') { send({GenerateStandardTableNum:0,alreadyCodeTable:0,benchmarkingCode:0,benchmarkingStandardTableNum:0,dataBaseStatisticsNum:count('sources'),tablesColumnsMapper:0}); return true; }
  if (p === '/api/standard/overview/standardStatistics') { send({codeSetNum:count('dictionaries'),dataSourceNum:count('elements'),qualifiersNum:count('qualifiers')}); return true; }
  if (p === '/api/standard/overview/tableNum' || p === '/api/standard/overview/standardRate') { send([]); return true; }
  if (p === '/api/data-manage/dataStation/dataBase/dbType' || p === '/api/data-manage/dataStation/dataBase/type') { send(['SQLite','MySQL','PostgreSQL']); return true; }
  if (p === '/api/data-manage/dataStation/dataBase/databaseTree' || p === '/api/data-manage/database/dataBase/hierarchyTree' || p === '/api/data-manage/dataStation/dataBase/db/tree' || p === '/api/data-manage/dataStation/db/all/list') {
    send(['604','605'].map((id,i)=>({id,key:id,name:i?'组织库':'汇聚库',alias:i?'组织库':'汇聚库',title:i?'组织库':'汇聚库',level:1,children:s.all('sources').filter(x=>String(x.hierarchyId||'604')===id).map(x=>({id:x.id,key:x.id,name:x.name,title:x.name,alias:x.name,type:x.type,level:2,children:s.all('tables').filter(t=>t.sourceId===x.id).map(t=>({id:t.id,key:t.id,name:t.name,title:t.name2||t.name,level:3,children:[]}))}))}))); return true;
  }
  if (p === '/api/data-manage/dataStation/dataBase/tables') {
    const id=params.dataBaseId||params.databaseId;send(id?await tables(s,id):[]);return true;
  }
  if (p === '/api/data-manage/dataStation/dataBase/tableColumns') { send(await columns(s,params.dataBaseId||params.databaseId,params.tableName||params.name)); return true; }
  if (p.startsWith('/api/data-manage/database/tables')) {
    const suffix=p.slice('/api/data-manage/database/tables'.length).replace(/^\//,'');
    if (!suffix || suffix==='queryPage') send(page(s.all('tables'),params));
    else if (suffix==='dataPreview' || suffix==='partitionOrDatas') {
      const table=s.get('tables',params.tablesId||params.tableId);requireValue(table,'元数据表不存在',404);
      const result=await previewRows(s,{sourceId:table.sourceId,table:table.name},params);send({col:table.columns,colData:result.list});
    } else if (suffix.startsWith('tc/')) { const table=s.get('tables',suffix.slice(3));requireValue(table,'元数据表不存在',404);send({tablesColumns:table.columns.map((c,i)=>({...c,id:String(i),name:c.name,type:c.type})),relevance:[]}); }
    else if (suffix==='partition') send([]);
    else { const table=s.get('tables',suffix);requireValue(table,'元数据表不存在',404);send(table); }
    return true;
  }
  if (p === '/api/data-manage/metadata/dictionaryCommon' || p === '/api/standard/metadata/dictionaryCommon/queryDictionaryCommon') { send(s.all('dictionaries')); return true; }
  if (p === '/api/tenant/apiServer/getCurrentJobType' || p === '/api/tenant/apiServer/getCurrentJobTypeByProjectIdAndEnvType') { send({isFlink:false,list:['local']}); return true; }
  if (p === '/api/tenant/apiServer/dataBase/databases') { send(s.all('sources').map(publicSource)); return true; }
  if (p === '/api/data/handle/sjcl/wjj/findTree' || p === '/api/data/handle/sjcl/wjj/findAllDatasByTree') { send(s.all('workflows').map(w=>({...w,key:w.id,title:w.name,nodeT:'workflow',gzlName:w.name}))); return true; }
  if (p === '/api/data/handle/sjcl/wjj/findAllFunctionsByTree') { send([]); return true; }
  if (p === '/api/track/api/monitor/resource/tree') { send([]); return true; }
  if (p === '/api/ztOtherQuality/ruleType/findAll') { send([{id:'completeness',name:'完整性'},{id:'validity',name:'有效性'},{id:'uniqueness',name:'唯一性'}]); return true; }
  if (p === '/api/ztOtherQuality/qualitySummary/selectByResultSummary' || p === '/api/ztOtherQuality/qualitySummary/totalStatus') {
    const latest=runs().find(r=>r.status==='SUCCESS'&&r.reports?.length),reports=latest?.reports||[],rules=reports.flatMap(r=>r.rules);
    const ruleCount={ruleTotal:rules.length,ruleNormal:rules.filter(r=>!r.failed).length,ruleError:rules.filter(r=>r.failed).length,ruleOrange:0,ruleRed:0};
    const tableCount={tableTotal:reports.length,tableNormal:reports.filter(r=>!r.invalidRows).length,tableError:reports.filter(r=>r.invalidRows).length,tableOrange:0,tableRed:0};
    send({ruleCount,tableCount});return true;
  }
  if (p === '/api/ztOtherQuality/qualitySummary/selectByResultBeforeSort') { send({ruleCount:[],tableCount:[]}); return true; }
  if (p === '/api/ztOtherQuality/qualitySummary/selectByResultBeforeReport') { send(runs().filter(r=>r.reports?.length)); return true; }
  if (p === '/api/ztOtherQuality/qualityTask/selectByQualityReport') { send(page(runs().filter(r=>r.reports?.length),params)); return true; }
  if (p === '/api/ztOtherQuality/data/warnings') { send(page(runs().filter(r=>r.reports?.some(p=>p.invalidRows>0)),params)); return true; }
  if (p === '/api/ztOtherQuality/data/warningsDetail') { send(s.run(params.id||params.runId)); return true; }
  if (p === '/api/ztOtherQuality/data/warnings/listAllDbName') { send(s.all('sources').map(x=>({id:x.id,name:x.name}))); return true; }
  if (p === '/api/apiService/overview/totalAmount') { send({apiTotalAmount:count('services'),transferAmount:s.db.prepare("SELECT count(*) AS total FROM audit WHERE action='service.query'").get().total,ascriptionAppAmount:1,warrantAppAmount:1}); return true; }
  if (p === '/api/apiMonitorUrl/api/monitor/api/apiOverview') { const list=s.all('services');send({sum:list.length,normal:list.filter(x=>x.published).length,abnormal:list.filter(x=>!x.published).length});return true; }
  if (/^\/api\/apiService\/overview\/(monitorCallNum|monitorCallError|monitorCallTime|publishApiNum|publishApiList|ascriptionAppRank|warrantAppRank)$/.test(p) || p === '/api/monitorCall/api/apiCallTrend') { send([]); return true; }
  if (p === '/api/apiService/ApiMarket/queryPage') { send({page:page(s.all('services').filter(x=>x.published),params),sortCount:[]}); return true; }
  if (p === '/api/apiService/ApiMarket/powerOffice') { send([{id:'local-office',name:'本地工作空间'}]); return true; }
  if (p === '/api/resource/dataResourceManage/getPage') { send(page(s.all('assets'),params));return true; }

  for (const [prefix,kind] of ENTITY_ROUTES) {
    if (p!==prefix && !p.startsWith(prefix+'/')) continue;
    const suffix=p.slice(prefix.length).replace(/^\//,''), id=params.id||params.dataElementId||params.dictionaryId||params.gzlId;
    const listActions=['queryPage','queryList','list','getAll','all','allBusinessType','queryAllApiPage','queryAccessApiPage','selectByRuleTypeId','queryByDictList'];
    const visible=record=>kind==='sources'?publicSource(record):kind==='services'?(({apiKeyHash,...rest})=>rest)(record):record;
    if (method==='GET' || (method==='POST' && listActions.includes(suffix))) {
      if (suffix==='export') {
        const list=s.all(kind).map(visible);ctx.response.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Content-Disposition':`attachment; filename="${kind}.json"`});ctx.response.end(JSON.stringify(list,null,2));return true;
      }
      if (suffix==='all' || suffix==='allBusinessType') {send(s.all(kind).map(visible));return true;}
      if (suffix==='queryDetail' || suffix==='detail' || (suffix && !listActions.includes(suffix))) {
        const record=s.get(kind,id||decodeURIComponent(suffix));requireValue(record,'记录不存在',404);send(visible(record));return true;
      }
      const result=page(s.all(kind).map(visible),params);send(kind==='services'?{page:result,sortCount:[]}:result);return true;
    }
    backend.admin(user);
    if (method==='DELETE' || /^(delete|remove)$/.test(suffix)) {
      const key=id||suffix;requireValue(s.get(kind,key),'记录不存在',404);s.remove(kind,key);s.audit(user.name,kind+'.delete',key);send(null);return true;
    }
    if (kind==='workflows' && /^(run|execute|start)$/.test(suffix)) {requireValue(s.get(kind,id),'流程不存在',404);send(backend.startRun(s.get(kind,id),user));return true;}
    if (method==='POST' || method==='PUT' || method==='PATCH') {
      requireValue(!suffix || ['save','add','insert','update','edit'].includes(suffix),'该业务操作尚未实现',501);
      const key=(method==='PUT'||method==='PATCH'||['update','edit'].includes(suffix))?id:undefined;
      const value=backend.saveEntity(kind,body,key);s.audit(user.name,kind+'.save',value.id);send(visible(value));return true;
    }
  }
  return false;
}
