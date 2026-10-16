# 数据治理平台

**版本：3.4.0 · Vue 3 + FastAPI + SQLite · 结构版本3**

参照原平台重建的可编译数据治理门户。前端包含完整Vue组件、菜单及路由源码；后端负责配置管理、样例治理、质量检测、报告、预警、数据服务与账号权限。当前平台自身数据已使用SQLite持久化。

## 1. 当前状态

| 内容 | 状态 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vue Router、Vite，可修改源码后重新构建 |
| 后端 | Python、FastAPI、Uvicorn，默认仅监听本机 |
| 平台数据库 | **49张SQLite表，结构版本3，真实数据库读写** |
| 旧JSON数据 | 已备份、迁移，成功后不再读取或覆盖数据库 |
| 数据库接入 | PostgreSQL、MySQL、MariaDB、SQL Server、Oracle、SQLite、MongoDB、ClickHouse共8种；统一只读采集到本地原始库 |
| 本地治理扩展 | 21个原说明入口已补齐本地对标、审批、调度、血缘、分析、授权、订阅及本地投递 |

**平台数据库**保存账号、配置、流程和报告等。**本地原始库**保存从外部业务库只读采集的完整逻辑快照，每批一个独立SQLite文件。**治理数据集**是从原始表选取字段和记录生成的工作副本；清洗结果另存，原始库和远程库保持原值。

## 数据库接入与首次真实治理

在“数据接入 → 数据库接入”选择数据库类型并保存连接参数 → “连接与采集”输入本次密码（SQLite无需密码） → 测试只读连接 → 扫描并批量选择表，或直接“采集全部业务表” → 在“本地原始库”查看完成的快照 → 选表、字段和行区间创建治理副本 → “编排治理流程”配置质量规则并执行。

新增其他数据库重复上述步骤即可。界面按类型设置默认端口，提供Oracle服务名/SID、MongoDB认证库、SQLite本机文件路径及可选CA证书。ClickHouse和MongoDB单机须使用“尽力读取”，快照会记录无整批一致性。详见[数据库兼容矩阵](docs/数据库兼容矩阵.md)。

验证范围：PostgreSQL 15.17已真实采集训练库；MySQL 9.3在独立测试实例验证TLS、只读、10,021行完整采集和治理；SQLite已做真实文件端到端测试。其他5种完成驱动契约及配置测试，尚无对应真实实例联调，不代表所有版本均已认证。

此前已完成真实业务库接入与考试记录治理验证；2026-10-16按要求备份并清空本地业务数据，供重新体验完整流程。Git仓库只包含代码、表结构和文档，不包含业务数据库、原始快照、账号会话、连接配置及备份。首次安装会生成独立的演示数据。

[数据库采集操作指南](docs/数据库接入与原始库操作指南.md) · [本轮采集验收](docs/数据库采集验收-2026-10-15.md)。

## 2. 快速使用

- 首页：http://127.0.0.1:4173/home
- 治理流程：http://127.0.0.1:4173/develop/flows
- 质量概览：http://127.0.0.1:4173/quality/overview
- 运行环境：http://127.0.0.1:4173/system/status
- FastAPI接口文档：http://127.0.0.1:4173/docs
- 健康检查：http://127.0.0.1:4173/api/health

当前机器已完成安装、建表、迁移和构建，双击 **启动项目.cmd** 即可使用，双击 **停止项目.cmd** 停止。命令行也可使用npm start、npm run stop，服务终端可按Ctrl+C。

双击启动使用后台进程，启动窗口关闭后服务继续运行，日志保存在`.data-v3/logs/`（自定义GOV_DATA_DIR时在对应目录）。后台命令为`node scripts/platform.mjs start --background --no-open`，仍只监听127.0.0.1，不安装系统服务、不设置开机启动。`npm start`保留前台模式，关闭其终端会停止服务。服务断开时页面显示“本地服务未连接”和中文操作提示，保留尚未提交的表单；恢复后先检查是否已保存，再重试，避免重复提交。

旧/workbench地址跳转新版治理流程，原/zt-*主模块地址跳转新版对应入口。所有活动页面使用本项目Vue源码，不执行旧Vue 2抓取包或iframe工作台。

## 3. 安装、建库与运行

要求Node.js22.14及以上、Python3.11及以上。Windows PowerShell进入项目根目录：

```powershell
npm.cmd ci
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
npm.cmd run build
npm.cmd run db:init
npm.cmd start
```

无需安装额外数据库服务。SQLite使用Python标准库，自身数据库默认位置：

```text
.data-v3/platform.sqlite3
```

若未单独执行db:init，首次启动后端也会自动建表并初始化。已经初始化的数据库不会被重复导入、覆盖或重置。**db:init应在服务停止时执行。**

首次空工作空间创建本地管理员及演示数据。默认启用本机自动管理员会话；需要密码登录时，首次初始化前设置ADMIN_PASSWORD并关闭LOCAL_AUTO_LOGIN。已存在账号不会因更改环境变量重置密码；可先在账号管理创建已知密码的管理员，再关闭自动登录。

## 4. 数据库与表结构

### 系统与标准

| 表 | 保存内容 |
| --- | --- |
| schema_migrations | 数据库结构版本 |
| platform_settings | 初始化及JSON迁移记录 |
| platform_users | 账号、角色、密码哈希 |
| platform_sessions | 会话令牌哈希和8小时有效期 |
| projects | 项目配置 |
| business_types | 业务分类 |
| data_elements | 数据元 |
| qualifiers | 限定词 |
| dictionaries / dictionary_items | 代码集及代码项 |
| catalogs | 标准目录 |

### 数据接入、资产与编排

| 表 | 保存内容 |
| --- | --- |
| data_sources | 连接参数及上次测试状态；密码只在本次连接/采集内存中使用 |
| datasets / dataset_rows | 样例或导入数据集及逐行数据 |
| data_assets | 资源登记、数据集、目录、来源与分级 |
| metadata_tables / metadata_columns | 元数据表及字段登记 |
| governance_workflows | 流程配置 |
| workflow_nodes / workflow_edges | 节点、参数、位置和连线 |
| workflow_node_rules | 质量节点与规则关联 |
| quality_rules | 非空、唯一、范围、格式、允许值规则 |
| quality_tasks / quality_task_rules | 检测任务及规则关联 |
| alert_policies | 预警管理说明，不代表外部通知已启用 |

### 执行、服务与追踪

| 表 | 保存内容 |
| --- | --- |
| job_runs | 运行状态、输入输出数量及时间 |
| job_steps | 每个节点的实际处理步骤 |
| quality_reports | 每个质量节点的检查汇总 |
| quality_rule_results | 每条规则的结果及问题索引 |
| job_result_rows | 逐行治理结果 |
| data_alerts | 预警、处理状态和说明 |
| data_services | 服务配置、数据关联、发布状态和密钥哈希 |
| audit_logs | 配置、运行、预警及服务调用审计 |

基础结构33张，版本2新增以下13张，版本3再增加3张，平台合计49张：

| 新表 | 保存内容 |
| --- | --- |
| governance_reports | 对标、时效、关系、资金、数据操作、适配及比对报告 |
| governance_approvals | 对象快照、版本指纹、审批意见及状态 |
| local_schedules | 执行间隔、启停、下次执行、重试与运行关联 |
| local_views | 字段白名单及AND筛选条件 |
| local_applications / application_service_grants | 应用凭据哈希、归属及逐服务授权 |
| interface_adapters | 本地数据映射及接收配置 |
| local_push_channels | 本地收件通道 |
| data_subscriptions / subscription_snapshots | 唯一业务键订阅及上次快照 |
| subscription_events / event_deliveries / local_inbox_messages | 变化事件、投递队列、真实收件记录 |
| raw_snapshots | 采集批次、来源参数快照、状态、进度、实际行数 |
| raw_snapshot_tables | 各原始表的模式、类型、主键、行数及摘要 |
| raw_dataset_links | 治理数据集与原始库/表/选取范围的外键关联 |

DDL见[基础结构](db/schema.sql)、[版本2](db/schema-v2.sql)、[版本3](db/schema-v3.sql)。启动时幂等升级，不清空原数据。原始文件位于`.data-v3/raw/<批次ID>.sqlite3`，其中raw_tables/raw_rows/manifest保存源表元数据、逐行原值及采集清单。它是SQLite逻辑数据快照，不包含PostgreSQL索引执行结构、触发器、序列状态、权限或存储过程。详细说明见[数据库设计](docs/数据库设计.md)。

数据库启用WAL、外键、10秒锁等待及事务。节点/连线、代码项、字段、规则关联和结果行在更新时与主记录一起提交；失败回滚。被引用的数据集、规则及目录受保护，删除返回冲突信息。审计长期保存，不再只保留最近10,000条。

[db/schema-postgresql.sql](db/schema-postgresql.sql)提供历史版本1模型的独立PostgreSQL建表参考，未包含版本2扩展。**当前应用仓储只支持SQLite；这个脚本不会自动启用PostgreSQL，也未在远程训练库执行。**

## 5. JSON迁移规则

首次初始化若发现.data-v3/state.json：

1. 先复制到.data-v3/backups/state-before-sqlite-时间-随机标识.json。
2. 在一个事务里导入15类配置、账号、数据集记录、流程子项、历史运行、报告、结果、预警和审计。
3. 校验导入数量，成功才写初始化及迁移标记；任何错误都回滚，保留原文件和备份。
4. 后续以SQLite为唯一数据源，修改旧state.json不会影响平台。
5. 原ID、账号密码哈希和已发布服务密钥哈希保留；旧内存会话不迁移，新会话保存在数据库，可跨重启使用。

本次迁移保留1个账号、3条质量规则、1个流程、1个数据集的8行记录、1次历史运行的7行输出、2条预警、4条原审计记录。迁移之后新操作会继续增加数据。

旧Node版本的.data不在自动迁移范围，仍保留原文件。不要删除数据库来实现升级，否则可能重新导入已归档的旧JSON。后续表结构变化应增加明确的版本迁移，不自动清空数据。

## 6. 数据库管理与备份

```powershell
npm.cmd run db:status
npm.cmd run db:check
npm.cmd run db:backup
# 指定新的备份文件；已存在的文件不会被覆盖
npm.cmd run db:backup -- --output E:/platform-backups/platform-2026-10-14.sqlite3
```

- status显示49张平台表的实际记录数、数据库版本及迁移信息。
- check执行完整性和外键检查，正常结果为integrity=["ok"]、foreignKeyViolations=[]。
- backup使用SQLite备份API，默认写到.data-v3/backups；同时将备份所关联的已完成原始库复制到同名`.raw`目录，可在运行时备份。RUNNING批次不能作为可用原始库恢复。
- status、check、backup不会把正在执行的任务标记中断。
- 不要在服务运行时只复制platform.sqlite3；WAL日志中可能还有未合并数据。

**恢复到新目录：**停止服务，将备份复制到一个新的恢复目录并命名platform.sqlite3，设置GOV_DATA_DIR指向该目录，执行db:check后启动。先保留原目录，不直接覆盖现有数据库。已恢复的配置和会话保留，恢复快照中仍为RUNNING的任务会在启动时标记INTERRUPTED。

版本3的备份同时包含`platform-时间.sqlite3`与`platform-时间.raw/`。恢复时将后者内的原始库文件复制到新GOV_DATA_DIR的`raw/`下；单独恢复平台文件无法恢复原始记录。原始库下载也可独立留存。

数据库和备份包含账号哈希、服务密钥哈希及业务记录，请仅在受控目录保存；.data-v3默认不提交版本库。采集连接密码不保存到平台数据源配置。

## 7. 已实现业务

| 模块 | 可用功能 |
| --- | --- |
| 首页 | 今日任务、标准/资源计数、模块入口、历史运行 |
| 数据标准 | 分类、数据元、限定词、代码集；字段/类型标准对标、代码覆盖检查和转换副本；版本快照审批 |
| 数据接入 | 8种数据库连接、业务表/集合扫描、整库/多表后台只读采集、进度与取消、本地原始库、字段与分页预览、下载和创建治理副本；JSON导入仍可用 |
| 数据处理 | 拖入和移动节点、连线、参数、保存、执行、报告、CSV；本地间隔调度、启停和失败重试 |
| 数据治理 | 五类规则、检测任务、质量概览、预警处理；按质量节点查看全链路报告；时间字段超期分析 |
| 数据资产 | 目录、资源登记、来源、分级和审批；从实际流程、结果、视图、服务生成本地血缘和数据地图 |
| 数据分析 | 两字段有向关系频次；使用Decimal汇总金额、流入、流出和净额 |
| 数据服务 | 数据集/运行结果/本地视图服务、字段白名单、密钥；应用逐服务申请授权与撤销、API/视图审核、OpenAPI下载和凭据查询测试 |
| 本地交换 | 字段映射适配、接口接收、生成治理副本；唯一键快照比对、新增/修改/删除事件、本地收件箱投递和失败重试 |
| 系统管理 | 管理员/只读账号、登录、账号创建、审计、环境信息 |

页面登记包含59个入口，含“本地原始库”。8种数据库均有采集连接器，具体前提和实测范围见兼容矩阵。21个原说明入口已按本地治理场景实现，部分入口复用业务组件。

本地闭环：在“样例数据集”导入JSON → 标准/代码/时效对标或拖拽编排 → 查看实际报告 → 视图预览与服务发布 → 应用申请/管理员授权 → 在服务规约测试查询 → 修改自己的本地数据集后按唯一键比对 → 查看变化事件、投递记录和本地收件箱。清洗、代码转换与适配均生成新数据集，保留原数据。

审批为本机管理员单级审核，保存目标快照；目标编辑后旧审批不能通过，已通过对象再编辑会回到草稿。审核记录与实际发布操作分别保存，发布仍由管理员执行。应用只有获批且启用时才能查询对应服务，停用或撤销立即生效。

调度和订阅最低间隔60秒，仅在单个后端运行时执行；关闭期间不执行，重启保留启停状态。调度支持最多3次失败重试。血缘来自本地登记、流程映射与成功运行；图形最多展示80个节点，可在关系表查看全部关联。关系和资金分析是本地数据统计，不包含案件研判或金融决策模型。

“外部接口”实现本地映射回放及认证接收；“数据推送”仅投递本地收件箱。采集按驱动分批读取，远程只查询；单次最多2000表、2GiB原始记录文本，超过限制整批失败。严格一致模式按数据库能力建立读取快照，不自动启用SQL Server服务器级SNAPSHOT设置；不能满足条件则失败。PostgreSQL排除系统表、视图、外部表与分区子表，分区根表包含其分区。其他类型的采集范围见兼容矩阵。大于10,000行的原始表可完整保存，但当前治理引擎须分批创建工作副本。跨部门多人审批、跨表JOIN、实时CDC、跨系统实时血缘、分布式调度和多租户仍未实现。

示例操作：数据处理 → 治理流程 → 选择演示流程 → 执行。8行样例经过清洗、去重输出7行，发现2行问题，合格率71.43%，结果和报告保存到SQLite。默认质量检查保留问题行；勾选“排除不合格记录”才过滤。

当前支持一个数据源、一个输出、线性流程，最多10,000行、45秒、2个并发任务。任务在独立Python进程执行，支持取消和超时，不执行用户脚本。重启不自动重跑，活动任务标记中断。结果仅写平台数据库，不写远程训练库。

## 8. 接口与权限

接口详见[docs/API.md](docs/API.md)及/docs。成功返回code/success/message/data；错误返回对应HTTP状态。配置CRUD和读取报告保持原Vue 3接口形状，数据库迁移无需前端重写。

管理员可修改和执行；reader只能读取。会话使用HttpOnly、SameSite=Strict Cookie，可用Bearer会话令牌，数据库仅保存令牌哈希；8小时有效，退出立即撤销。重启后未过期会话仍有效。

已发布查询使用服务X-API-Key，或已获批应用的X-App-Key；密钥仅显示一次、数据库只存哈希。重新发布撤销旧服务密钥，修改服务配置取消发布。每服务每分钟60次调用，登录及调用限流计数当前为进程内存，重启重置。本地收件箱、通道、订阅、投递管理仅管理员可用。

health中storage="sqlite"且platformDatabase.configured=true表示平台库已就绪；databaseConfigured表示是否存在上次测试通过的数据源，非实时在线探测；externalConnectors列出已安装驱动的只读连接器，connectorCatalog给出能力目录。采集和原始库API仅管理员可用，完成后的本地读取无需密码。

## 9. 开发与源码

先停止生产服务，两个终端分别启动：

```powershell
npm.cmd run api:dev
npm.cmd run dev
```

前端http://127.0.0.1:5173，API代理到4173。Python代码自动重载；Windows使用支持子进程的专用事件循环。生产模式修改Vue后需要重新构建并刷新4173页面。

已经打开的浏览器标签页会继续运行原先加载的页面代码；页面内“刷新”只更新业务列表，升级后需整页刷新（F5，必要时Ctrl+F5）。页脚显示当前页面和服务版本；恢复窗口焦点/可见状态及每60秒检查服务版本，发现不同后提示先保存再重新加载，不自动清空正在填写的内容。同一版本内重新构建仍须主动整页刷新。

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd test
npm.cmd run format
```

```text
src/
  App.vue                    门户、登录和导航
  router/pages.ts / index.ts  菜单注册与路由
  api/client.ts              HTTP接口
  stores/platform.ts         公共状态
  components/                表格、弹窗、图标
  views/                     首页、配置、画布、结果、预警、账号、审计
  styles/main.css            样式与响应式布局
api/
  main.py                    FastAPI业务、身份与权限
  storage.py                 SQLite仓储、事务、子表、会话和迁移
  seed.py                    空工作空间初始化样例
  database_cli.py            建库、状态、检查和一致备份
  engine.py                  节点与质量规则
  local_api.py               /api/local扩展接口
  local_store.py             扩展仓储与版本2迁移
  local_engine.py            本地分析、视图、快照比较和血缘
  local_governance.py        审批、授权、调度、订阅及投递
  jobs.py / runner.py         独立进程执行
  connectors.py              PostgreSQL只读连接、目录与服务端游标
  connector_common.py        8类连接器目录、参数校验及原值规范
  db_readers.py               MySQL/MariaDB、SQL Server、Oracle、SQLite、MongoDB、ClickHouse
  ingestion_api.py           认证采集、原始库和治理副本接口
  raw_store.py               版本3迁移、独立原始库文件与后台采集
  config.py / serve.py        环境和本机启动
  tests/                     隔离测试
db/
  schema.sql                 实际SQLite DDL
  schema-v2.sql              本地治理扩展DDL
  schema-v3.sql              原始库及来源关联DDL
  schema-postgresql.sql      PostgreSQL参考DDL
docs/
  数据库设计.md              表结构和关系说明
  API.md                     当前接口
```

新增页面在views创建Vue组件并登记pages.ts及router。新增存储类型要同步schema版本、storage.py的TABLES/FIELDS和子项方法、业务校验和测试，不能只增加前端按钮。已有接口从仓储读取数据，没有JSON内存镜像。

平台数据库支持当前单进程、本机部署，不直接启用多worker；采集单任务、治理最多2并发。PostgreSQL为被采集源，平台SQLite和本地原始库独立，所有治理不回写远程库。采集连接密码不存入配置；原始业务记录可能包含业务自身的敏感字段，文件和备份应受控保存。

## 10. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| PORT | 4173 | 后端端口，开发代理使用相同值 |
| GOV_DATA_DIR | 根目录.data-v3 | platform.sqlite3、旧JSON备份和SQLite备份目录 |
| LOCAL_AUTO_LOGIN | true | 本机自动管理员会话，false关闭 |
| ADMIN_PASSWORD | 首次随机 | 首次空库初始化密码；已有用户不会重置 |
| JOB_TIMEOUT_SECONDS | 45 | 0.1至45秒 |
| PYTHON | .venv内Python | 启动解释器 |

.env.example只是示例，默认不自动加载。PowerShell用$env:GOV_DATA_DIR='E:/your-platform-data'等方式设置。关闭自动登录前先创建已知密码的管理员。SQLite文件及备份必须与旧训练服务器数据分开。

## 11. 验证与历史材料

此前76项自动回归测试通过，另1项可选MySQL实库测试已在独立实例单独通过（默认未提供测试实例时跳过）。覆盖原业务、迁移、角色、取消/超时、本地分析与投递、8种配置、驱动调用、标识符转义、TLS校验、类型保真、一致性保护，以及SQLite超过10000行的实际全流程。类型检查、生产构建和依赖检查通过。历史验收记录反映当时状态，不表示新安装包含现场业务数据。详见[多数据库验收](docs/多数据库验收-2026-10-15.md)。

[2026-10-15浏览器验收记录](docs/浏览器验收记录-2026-10-15.md)：**约定的本地SQLite场景验收通过**。58个页面逐页复测，7项既有缺陷已修复，21个缺失入口已补齐；真实鼠标拖入、移动、保存后刷新，确认删除、引用保护、授权查询及本地投递均已验证。已按用户授权清理本次“验收测试-*”配置、结果和测试账号；保留测试审计与证据，原有业务记录逐项对照验收前备份未改变。此结论不包括未配置的外部系统集成。

原抓取包、旧Node后端和旧.data在本机保留用于参考，新构建不复制旧public资源。Git仓库排除旧mock/public录制资源、现场截图和验收JSON；历史回放及依赖这些本地材料的审计脚本不属于仓库的独立运行范围。默认Vue 3 + FastAPI版本可通过源码正常构建与运行。旧分析和接口实测清单属于历史版本；当前API以API.md和在线/docs为准。此前JSON版README备份为docs/历史版本README-JSON.md。

参考：[Vue构建说明](https://vuejs.org/guide/quick-start)、[FastAPI测试](https://fastapi.tiangolo.com/tutorial/testing/)、[SQLite在线备份](https://www.sqlite.org/backup.html)。
