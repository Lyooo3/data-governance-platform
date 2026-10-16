import { DatabaseSync } from 'node:sqlite';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

export function seed(store) {
  if (store.setting('initialized')) return;
  store.transaction(() => {
    store.createUser('admin', process.env.ADMIN_PASSWORD || randomBytes(24).toString('hex'), 'admin');
    store.save('projects', { id: 'local-project', projectId: 'local-project', name: '本地数据治理', projectName: '本地数据治理', projectCode: 'local_governance', envType: '0' });
    store.save('businessTypes', { id: 'local-business', name: '示例业务', code: 'DEMO', parentId: '' });
    store.save('elements', { id: 'local-element', name: 'DWMC', name2: '单位名称', code: 'DE00000001', businessType: 'local-business', businessTypeEntity: { id: 'local-business', name: '示例业务' }, formatType: '字符型', dataFormat: 'c..100', status: '1', publish: '1', version: '1.0', createPerson: 'admin' });
    store.save('qualifiers', { id: 'local-qualifier', name: '名称', code: 'Q0001', version: '1.0' });
    store.save('dictionaries', { id: 'local-dictionary', name: '示例类别代码', code: 'DEMO_CATEGORY', version: '1.0', dictionaryDetails: [{ code: 'A', name: '类别A' }, { code: 'B', name: '类别B' }] });
    store.save('catalogs', { id: 'local-catalog', name: '示例记录目录', code: 'LOCAL-001', version: '1.0', tradeCode: '示例业务', dataItemList: [], createPerson: 'admin' });
    store.save('rules', { id: 'rule-required', name: '单位名称不能为空', templateName: '单位名称不能为空', type: 'required', field: 'org_name', ruleTypeId: 'completeness', ruleTypeName: '完整性', templateStatus: '1' });
    store.save('rules', { id: 'rule-score', name: '分值应在0至100之间', templateName: '分值范围检查', type: 'range', field: 'score', min: 0, max: 100, ruleTypeId: 'validity', ruleTypeName: '有效性', templateStatus: '1' });
    store.save('sources', { id: 'demo-source', name: '本地示例数据库', nameAlias: '本地示例数据库', type: 'SQLite', file: 'demo.sqlite', allowWrite: true, hierarchy: '汇聚库', hierarchyId: '604', status: '0', connectionStatus: '1', demo: true });
    store.save('tables', {id:'demo-table',name:'demo_records',name2:'示例记录',dataBaseId:'demo-source',sourceId:'demo-source',columns:[{name:'id',type:'INTEGER',primaryKey:true},{name:'record_code',type:'TEXT'},{name:'org_name',type:'TEXT'},{name:'score',type:'REAL'},{name:'category',type:'TEXT'}]});
    const nodes = [
      { id: 'n1', type: 'source', label: '读取示例表', x: 40, y: 70, config: { sourceId: 'demo-source', table: 'demo_records' } },
      { id: 'n2', type: 'clean', label: '去除单位名称空格', x: 290, y: 70, config: { fields: ['org_name'], operation: 'trim' } },
      { id: 'n3', type: 'dedupe', label: '按记录编号去重', x: 540, y: 70, config: { fields: ['record_code'] } },
      { id: 'n4', type: 'quality', label: '完整性与分值检查', x: 790, y: 70, config: { ruleIds: ['rule-required', 'rule-score'] } },
      { id: 'n5', type: 'output', label: '保存治理结果', x: 1040, y: 70, config: {} },
    ];
    store.save('workflows', { id: 'demo-workflow', name: '示例：清洗、去重与质量检查', gzlName: '示例：清洗、去重与质量检查', nodes, edges: nodes.slice(1).map((n, i) => ({ source: nodes[i].id, target: n.id })), description: '示例库包含空格、重复记录、空单位名称和超范围分值。运行结果：8条输入、7条输出、2条问题记录。' });
    store.setting('initialized', true);
  });
  const demo = path.join(store.dir, 'sources', 'demo.sqlite');
  if (!existsSync(demo)) {
    const db = new DatabaseSync(demo);
    db.exec('CREATE TABLE demo_records(id INTEGER PRIMARY KEY,record_code TEXT,org_name TEXT,score REAL,category TEXT);');
    const insert = db.prepare('INSERT INTO demo_records VALUES(?,?,?,?,?)');
    [[1,'R001',' 示例单位甲 ',90,'A'],[2,'R002','示例单位乙',80,'B'],[3,'R002','示例单位乙',80,'B'],[4,'R003','',70,'A'],[5,'R004','示例单位丙',120,'B'],[6,'R005','示例单位丁',60,'A'],[7,'R006',' 示例单位戊 ',85,'B'],[8,'R007','示例单位己',75,'A']].forEach(row => insert.run(...row));
    db.close();
  }
}
