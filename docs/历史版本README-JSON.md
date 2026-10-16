# 数据治理平台 · Vue 3 + FastAPI

当前默认运行版本为3.0：参照原平台重建的Vue 3门户和Python FastAPI后端。活动页面全部由本项目源码构建，不执行原抓取的Vue 2编译包，也没有iframe工作台。

业务数据库暂不配置。配置、样例、结果和审计保存在.data-v3/state.json，不初始化SQLite、不连接MySQL。默认仅监听127.0.0.1，本机自动管理员会话用于开发。

## 访问入口

- 首页：http://127.0.0.1:4173/home
- 治理流程：http://127.0.0.1:4173/develop/flows
- 质量概览：http://127.0.0.1:4173/quality/overview
- FastAPI接口文档：http://127.0.0.1:4173/docs
- 健康检查：http://127.0.0.1:4173/api/health

/workbench跳转新版流程；原/zt-*主模块地址跳转新版对应模块。

## 首次准备与启动

环境：Node.js22.14及以上、Python3.11及以上。Windows PowerShell在项目根目录执行：

```powershell
npm.cmd ci
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
npm.cmd run build
npm.cmd start
```

当前机器已完成安装和构建，可以直接双击启动项目.cmd。停止项目.cmd或npm run stop可停止默认服务，服务终端也可按Ctrl+C。不要同时运行两个后端进程。

requirements.txt记录依赖范围，requirements.lock.txt锁定本次验证版本；升级需要重新测试。无需配置数据库。

## 开发与编译

先停止已运行的生产服务，两个终端分别启动：

```powershell
# 终端1：FastAPI，Python修改自动重启
npm.cmd run api:dev
# 终端2：Vue，组件修改即时更新
npm.cmd run dev
```

前端开发地址http://127.0.0.1:5173，API代理到4173。生产模式FastAPI直接提供dist文件。

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd test
npm.cmd run format
```

修改源码后重新构建并刷新4173页面。npm start只在dist不存在时自动构建，已有dist不随源码自动更新。

## 当前能力

| 模块 | 已实现 |
| --- | --- |
| 首页 | 今日任务、资源和标准计数、模块入口、最近运行 |
| 数据标准 | 业务分类、数据元、限定词、代码集、标准配置 |
| 数据接入 | 接入草稿（不连接、不保存密码）、JSON数据集、预览、元数据配置 |
| 数据处理 | Vue画布添加/拖入/移动节点、连线、参数、保存、执行、结果和CSV |
| 数据治理 | 质量概览、五种规则、自定义任务、预警生成、详情和处理 |
| 数据资产 | 目录、资源登记、来源、分级及登记数据概览 |
| 数据服务 | 样例/运行结果服务、字段白名单、密钥、重新发布、调用审计 |
| 系统管理 | 管理员/只读角色、登录、创建账号、审计、环境信息 |

标准对标、审批、时效调度、实时血缘、关系和资金分析入口已用Vue重建，页面明确显示尚未启用。这些业务引擎未实现，不把页面迁移视为业务能力完成。

演示流程：8条JSON样例 → 名称去空格 → 编号去重 → 非空/范围检查 → 7条输出，2条问题，71.43%合格率。默认质量节点报告问题，勾选排除不合格记录才过滤。

单数据源线性流程，最多10,000行、45秒、2个并发任务。独立Python进程执行，取消或超时终止进程。结果不写入业务数据库。

## 源码与扩展位置

```text
src/
  App.vue                  门户外壳、登录、顶部导航和侧栏
  router/pages.ts          模块和页面注册表
  router/index.ts          Vue Router、旧地址重定向
  api/client.ts            HTTP客户端
  stores/platform.ts       账号、统计、公共状态和通知
  components/              表格、弹窗和图标
  views/                   首页、配置、画布、报告、质量、账号、审计
  styles/main.css          样式与响应式布局
api/
  main.py                  FastAPI路由、认证及权限依赖
  config.py                环境和路径
  storage.py               文件仓储、初始化及审计
  engine.py                流程校验和规则执行
  jobs.py / runner.py       独立进程、取消、超时、结果
  connectors.py            未来数据库接入边界，当前未启用
  serve.py                 本机生产启动和停止
  tests/                   隔离测试
vite.config.ts / tsconfig.json
requirements.txt / requirements.lock.txt
```

新增页面：在views创建Vue组件，pages.ts登记菜单，router/index.ts登记组件。通用配置复用EntityView和DataTable。

新增后端资源：storage.py登记kind，main.py的save_entity加入校验。复杂业务宜拆分模块，用APIRouter挂载。新增节点需同步engine.py、FlowView及测试。

后续数据库接入从connectors.py实现连接和访问，再替换storage.py仓储或增加数据库仓储。当前JSON文件仅用于本机、单进程开发，不支持多人生产或Uvicorn多worker模式。

## 环境配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| PORT | 4173 | 后端端口，Vite代理读取相同变量 |
| GOV_DATA_DIR | .data-v3 | 配置文件目录 |
| LOCAL_AUTO_LOGIN | true | false关闭本机会话 |
| ADMIN_PASSWORD | 首次随机 | 初始管理员口令，已有账号不重置 |
| JOB_TIMEOUT_SECONDS | 45 | 0.1至45秒 |
| PYTHON | .venv内Python | 覆盖启动Python路径 |

.env.v3.example只是示例，默认启动不自动读取.env。PowerShell用$env:变量名='值'设置。关闭自动登录前先创建已知密码的管理员。备份时停止服务、复制完整.data-v3。会话在内存中，重启重新登录。

## 旧版本保留情况

mock、public、backend、server.mjs及旧.data保留用于对照，没有自动导入旧SQLite配置、账号和结果。新版工作目录独立。Vite publicDir=false，不复制旧包。旧Node后端不参与默认运行，数据库驱动依赖已移除。

start:replay为历史录制回放，先停止新版再运行；回放不保存业务。build:har需要原HAR，当前缺失，不是Vue构建。旧审计、测试及分析报告仅代表历史版本，当前API见docs/API.md和/docs。旧README和API已备份到docs/历史版本README.md、历史版本API.md。

## 验证

类型检查及生产构建通过，按页面懒加载并生成源码映射。FastAPI测试覆盖权限、保存、重启、无数据库、实际执行、预警、引用保护、密钥、CSV、取消、超时及SPA。

浏览器验证首页入口、规则保存及示例运行：8条输入、7条输出、2条问题。

参考：[Vue官方构建说明](https://vuejs.org/guide/quick-start)、[FastAPI静态资源](https://fastapi.tiangolo.com/tutorial/static-files/)、[FastAPI测试](https://fastapi.tiangolo.com/tutorial/testing/)。
