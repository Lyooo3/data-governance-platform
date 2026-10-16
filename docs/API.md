# Vue 3 + FastAPI接口（3.4）

基址http://127.0.0.1:4173。交互文档/docs、规范/openapi.json。成功为{code:200,success:true,message,data}；错误使用对应HTTP状态及success:false。CSV除外。

认证为HttpOnly、SameSite=Strict的gov_v3_session Cookie，也支持Bearer会话令牌。会话哈希保存在SQLite，8小时有效，重启后未过期会话仍可使用，退出立即撤销。修改、执行和发布要求管理员。

## 身份

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/health | 前后端、存储和数据库状态，无需登录 |
| POST | /api/auth/local-session | 同源本机管理员会话，需要LOCAL_AUTO_LOGIN |
| POST | /api/auth/login | name/password |
| GET | /api/auth/me | 当前账号 |
| POST | /api/auth/logout | 撤销会话 |
| GET/POST | /api/auth/users | 管理员列表/新增；密码至少10位，角色admin/reader |

## 通用配置

/api/governance/{kind}支持GET列表、POST新增；/{kind}/{id}支持GET详情、PUT/PATCH修改、DELETE删除。列表参数pageNum/pageNumber、pageSize（最多500）、search/searchContent，部分支持status/type/catalogId。data为list/total/pageNum/pageSize。

kind：sources、workflows、elements、businessTypes、qualifiers、dictionaries、catalogs、assets、rules、qualityTasks、services、projects、tables、datasets、alertPolicies。

| 类型 | 核心字段 |
| --- | --- |
| sources | name/type及对应连接参数、consistencyMode；8类连接器，具体字段见下文；不保存口令 |
| datasets | name/description/rows：最多10,000行、100字段的基础类型对象数组，各行字段一致 |
| workflows | name/nodes/edges |
| rules | name/field/type及pattern、min/max或values |
| qualityTasks | name/datasetId/ruleIds |
| services | name/datasetId或runId或viewId/fields/description；来源优先级viewId、runId、datasetId，前端切换来源时清空另外两项 |
| dictionaries | name/code/version/dictionaryDetails，条目code/name |
| assets | name/datasetId/catalogId/dataLevelName/sourceSystem/region/description |
| elements | name/field/code/dataType/version/description |
| tables | name/datasetId/columns/description，登记配置，非自动采集 |
| alertPolicies | name/severity/description，管理说明，非通知/定时引擎 |

所有实体需要name，新增由服务器生成id。被流程、任务、服务、资产、元数据引用的数据集不可删除；被流程/任务引用的规则不可删除。数据集列表省略rows，详情返回完整rows便于编辑。

GET /api/governance/datasets/{id}/rows分页预览。旧sources/{id}/{action}接口返回501并提示迁移到下述/api/ingestion；保存数据源参数本身不建立网络连接。

## 流程结构

```json
{
  "name": "清洗检测",
  "nodes": [
    {"id":"a","type":"source","label":"读取样例","x":30,"y":140,"config":{"datasetId":"demo-dataset"}},
    {"id":"b","type":"clean","label":"去空格","x":245,"y":140,"config":{"fields":["org_name"],"operation":"trim"}},
    {"id":"c","type":"quality","label":"质量检查","x":460,"y":140,"config":{"ruleIds":["rule-required"],"dropInvalid":false}},
    {"id":"d","type":"output","label":"保存结果","x":675,"y":140,"config":{}}
  ],
  "edges":[{"source":"a","target":"b"},{"source":"b","target":"c"},{"source":"c","target":"d"}]
}
```

2至50节点，一个source和一个output，全部线性连接，拒绝循环、分支和多表合并。

| 节点 | 参数 |
| --- | --- |
| source | datasetId，外部sourceId/sql未支持 |
| select | mappings:[{from,to}]，目标不得重名 |
| clean | fields/operation，trim/upper/lower/number/fill，fill用value |
| filter | field/operator/value，eq/ne/contains/notEmpty/gt/lt |
| dedupe | fields组合键，保留第一条 |
| quality | ruleIds或rules，dropInvalid控制问题过滤 |
| output | 结果写入平台SQLite，不写外部业务数据库 |

规则type为required/unique/regex/range/enum。正则为Python语法，迁移旧JS表达式需要核验差异。重复键所有记录计为唯一性问题。合格率0至100，空数据为null。failedIndexes为质量节点输入的0起始索引，最多100项；多个节点的预警不可直接相加作为唯一问题行数。

## 执行和预警

以下路径均以/api/governance开头：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /workflows/{id}/run | 执行流程 |
| POST | /qualityTasks/{id}/run | 对数据集执行规则 |
| GET | /runs | 列表，省略rows |
| GET | /runs/{id} | 状态、步骤、报告 |
| POST | /runs/{id}/cancel | 取消运行任务 |
| GET | /runs/{id}/rows | 结果分页 |
| GET | /runs/{id}/export | CSV，公式起始字符保护 |
| GET | /alerts | 质量问题生成的预警 |
| GET | /alerts/{id} | 详情 |
| POST | /alerts/{id}/resolve | {note}标记处理，不修复源数据 |
| GET | /summary | 资源数、今日/历史任务、最近成功运行、待处理预警 |
| GET | /audit | 管理员审计 |
| POST | /shutdown | 默认服务停止；开发服务用Ctrl+C |

状态RUNNING/SUCCESS/FAILED/CANCELLED/TIMED_OUT/INTERRUPTED。独立Python进程执行，最多45秒、2并发、10,000条输入。重启中断不自动重试，进度通过前端轮询。

## 数据服务

POST /api/governance/services/{id}/publish返回endpoint和一次显示的apiKey。GET /api/published/{id}/query使用X-API-Key，或已获批且启用的应用X-App-Key，不需要平台Cookie。仅分页和字段白名单，无任意SQL。每服务单进程每分钟60次，查询写入审计。

重新发布撤销旧服务密钥，修改配置取消发布；只保存密钥哈希。数据来自本地数据集、成功运行或本地视图，不来自外部数据库。撤销应用授权或停用应用立即拒绝其调用。

## 本地治理扩展

以下以`/api/local`开头，均需平台会话。读取为登录用户，除个人申请/撤回外的变更和执行均需管理员。reader只可查看自己的应用及其授权；订阅、通道、事件、投递和收件箱管理仅管理员可用。

| 方法 | 路径 | 内容 |
| --- | --- | --- |
| GET | /bootstrap | 可选数据集字段/计数、标准、流程、服务、视图、自己的应用等 |
| GET | /records/{kind} | list/total；可按operation、status、targetKind、subscriptionId过滤 |
| GET | /records/{kind}/{id} | 完整详情，包含结果行、快照或消息 |
| POST | /records/{kind} | 新增可编辑配置 |
| PUT | /records/{kind}/{id} | 编辑可编辑配置 |
| DELETE | /records/{kind}/{id} | 删除可编辑配置或分析报告；受外键保护 |
| POST | /analyze/{operation} | 实际执行本地分析并保存报告 |
| POST | /approvals | targetKind/targetId/reason，保存目标快照和指纹 |
| POST | /grants | appId/serviceId/reason，发起逐服务授权申请 |
| POST | /action/{kind}/{id}/{action} | 下表所列业务动作 |
| POST | /adapters/{id}/receive | {rows:[...]}，认证接收，映射后生成新数据集及报告 |
| GET | /lineage | 可选workflowId；nodes/edges/mappings实际本地关联 |
| GET | /chain | 各次运行的每个质量节点报告 |
| GET | /contracts/{serviceId} | 对应服务OpenAPI 3.1规范，含白名单、凭据和限流说明 |

kind包括reports、approvals、schedules、views、apps、grants、adapters、channels、subscriptions、events、deliveries、inbox。可编辑配置仅schedules/views/apps/adapters/channels/subscriptions。列表省略大结果；目前读取全量配置后由前端搜索分页，非大规模服务端分页。

| 可编辑类型 | 主要参数 |
| --- | --- |
| schedules | name/workflowId/enabled/intervalSeconds（60至31536000）/maxRetries（0至3） |
| views | name/datasetId/fields（字段数组）/filters（最多20个AND条件，使用流程filter参数） |
| apps | name/ownerId/enabled；创建返回一次apiKey，后续只返回公开信息 |
| adapters | name/datasetId/mappings:[{from,to}] |
| channels | name/enabled/recipient；本地收件箱通道 |
| subscriptions | name/datasetId/keys（唯一非空复合业务键）/channelId/enabled/intervalSeconds |

| operation | 参数与结果 |
| --- | --- |
| standard | datasetId/可选elementIds/mapping（标准字段→数据字段），检查字段存在性与实际类型 |
| code | datasetId/field/dictionaryId/apply/outputField，统计匹配及未匹配；apply生成带名称字段的副本 |
| timeliness | datasetId/field/maxAgeHours/可选referenceTime；及时、超期、未来、无效时间 |
| relations | datasetId/fromField/toField；有向边及重复频次 |
| funds | datasetId/fromField/toField/amountField；Decimal金额汇总及无效行计数 |
| operate | datasetId/action（clean/filter/dedupe/select）/config（对应节点参数），生成副本 |

分析可传name；保存config、metrics、rows和可选outputDatasetId。所有输入为本地基础类型对象数组，最多10000行。不支持用户SQL、Python脚本或出站请求。

| kind | action | 行为 |
| --- | --- | --- |
| approvals | approve/reject/withdraw | 意见传note；仅pending可操作，approve需目标版本与快照一致；withdraw限本人或管理员 |
| grants | approve/reject/revoke | 管理员决定应用服务范围；授权查询需要approved |
| schedules/subscriptions/apps/channels | enable/disable | 保存启停状态 |
| schedules | run | 提交一次真实流程任务，返回运行关联；后台另按间隔执行 |
| subscriptions | compare/reset | 比较前后快照生成真实变化，或以当前数据重建基线 |
| views | preview | 条件过滤与字段投影的真实行 |
| adapters | replay | 对已选本地数据执行映射，生成新数据集 |
| events | enqueue | body.channelId，排队；相同事件/通道不重复 |
| deliveries | deliver | 实际投递或失败重试，成功后插入唯一收件记录 |

审批状态pending→approved/rejected/withdrawn，授权pending→approved/rejected，approved→revoked。审批通过不自动发布API；编辑已通过的对象会将其状态置draft。订阅按变化类别生成事件，事件明细保留每条变化的before/after。通道停用会留下failed投递记录，修复后手动重试；队列pending由后台投递。后台仅在平台进程运行期间工作，单实例，重启恢复持久化配置。

## 边界

本机、SQLite平台仓储（49表，结构版本3），支持8种数据库只读采集为独立本地原始库，见兼容矩阵。health中databaseConfigured表示是否有上次测试通过的数据源，非实时在线保证；externalConnectors列出已安装只读连接器，connectorCatalog为能力目录。跨表JOIN、CDC、多租户未实现。推送仅到本地收件箱；未实现外部通知或跨部门审批。未知API返回404，不回放成功。数据库结构、迁移与备份见数据库设计.md和根目录README。

## 多数据库只读采集与原始库（3.4）

以下接口均以`/api/ingestion`开头，**全部需要管理员会话**。远程密码使用password字段，仅当次请求/后台任务内存持有；验证错误不返回该字段。无原始库编辑/覆盖接口。

| 方法 | 路径 | 参数与返回 |
| --- | --- | --- |
| GET | /connectors | list：type/label/port/module/available/note/consistency/passwordOptional，前端按驱动能力显示选项 |
| POST | /sources/{id}/test | {password}；返回版本、当前库、read_only、实际isolation/consistent_snapshot/read_only_enforcement；保存上次成功测试状态 |
| POST | /sources/{id}/tables | {password}；返回可读业务表list/total，含oid/schema/name/estimated_rows/comment |
| POST | /sources/{id}/snapshots | {password,name,tables:null或整数标识数组}；null采集全部业务对象，数组采集所选，最多2000；返回RUNNING批次 |
| GET | /snapshots | 可选sourceId；批次列表及实际进度 |
| GET | /snapshots/{id} | 进度、状态、源参数快照、实际行数、完整表结构和各表行数 |
| POST | /snapshots/{id}/cancel | 请求取消读取，返回cancelRequested；后台最终状态CANCELLED |
| GET | /snapshots/{id}/tables/{tableId}/rows | pageNum/pageSize，最多100行/页；原始文本值与SQL空值，仅读取本地文件 |
| POST | /snapshots/{id}/tables/{tableId}/datasets | {name,fields,offset,limit}；offset从0计，limit为1至10000，最多100字段；返回数据集id/rowCount/rawOrigin |
| GET | /snapshots/{id}/download | 下载独立原始库SQLite文件，非JSON封装 |

快照状态RUNNING→SUCCESS/FAILED/CANCELLED，非正常重启时未完成批次转INTERRUPTED。只有SUCCESS允许读取、下载和创建治理副本。失败或取消删除临时文件和不完整表目录，保留失败进度供排查；重新采集生成新ID。单实例只允许同时一个采集任务，所选表失效或任意表读取失败导致整批失败。

源配置通过`/api/governance/sources`保存，type为postgresql/mysql/mariadb/sqlserver/oracle/sqlite/mongodb/clickhouse。共用name/description/consistencyMode（strict或best_effort）。网络源用host/port/database/user/sslmode（prefer或require）/caFile；Oracle增加serviceMode（service或sid），database表示连接服务；MongoDB增加authDatabase；SQLite仅需filePath绝对路径。只保存公开字段，不接受保存密码。SQLite请求可为`{}`；MongoDB、ClickHouse密码可留空，其余类型需本次非空密码。

读取按方言建立只读事务/会话，每批500行；各驱动连接超时8秒、读取超时60秒（具体超时语义由驱动提供）。SQL Server严格模式需SNAPSHOT已启用；MySQL/MariaDB严格只采集InnoDB；MongoDB严格需5.0+副本集/分片；ClickHouse只读但无跨表一致事务，strict采集拒绝，须显式best_effort。快照transaction保存实际能力，不伪造统一隔离级别。仅引用转义目录标识符、参数化元数据查询，不执行用户SQL。最多2000表、2GiB记录文本，超过限制不会截断后标成功。读取范围详见[兼容矩阵](数据库兼容矩阵.md)。

原始库逐行保留源值文本表示与列类型，NULL区别于空字符串；二进制base64，MongoDB整文档为Canonical Extended JSON。治理副本将安全范围整数、短精度数值和布尔转换为基础类型；超出JS安全范围的大整数、高精度数值及JSON/数组等保持文本，避免原始值损失。rawOrigin与raw_dataset_links记录批次、原始表、字段及范围；血缘可追到原始库。治理副本可编辑，原始库不受影响。
