# Vue 3 + FastAPI Implementation Plan

**Goal:** 将抓取页面和独立工作台迁移为有源码、可构建的统一Vue 3门户，使用FastAPI后端，不配置外部数据库。

**Architecture:** Vue 3单文件组件、TypeScript、Vue Router、Vite；FastAPI提供业务接口、OpenAPI及生产前端资源。平台配置原子保存为本地JSON，内置样例为普通文件数据，不初始化SQLite或连接MySQL。旧录制资源与旧.data保留但不参与新默认运行。

**Tech Stack:** Vue 3、Vite、TypeScript、Python 3.11、FastAPI、Uvicorn、pytest。

## 设计与取舍

完整原Vue工程缺失，重新包装旧JS无法达到可维护目标。采用重写组件而非iframe或编译包补丁。参照蓝色门户、顶部模块、左侧菜单、首页统计和链路图；新代码不依赖原厂组件或远程服务。

保留数据标准、接入、处理、治理、资产、服务及设置入口。通用配置用共享表格/编辑组件，流程用独立Vue画布。原厂复杂对标、实时链路、时效调度、关系/资金分析以明确能力说明页面承接，不伪造业务完成。质量概览、规则、任务、预警、报告通过同一后端模型关联。

用户已明确授权迁移实施，不重复请求设计或执行确认。当前目录不是Git仓库，直接在现有工程增加新src和api；旧文件保留以便对照。

## 执行步骤

1. 建立src、Vite、TypeScript、Vue Router及npm开发/构建入口，安装并锁定依赖。
2. 实现api/config、storage、engine、jobs、routers和main，文件持久化、统一错误、角色授权、样例执行、取消/超时、CSV和数据服务。
3. 重建首页、模块导航、标准和资产CRUD、样例预览、质量总览、任务、预警、服务、账号和审计。
4. 实现Vue流程拖拽、节点编辑、连线、保存、运行及报告；不允许通过UI把未接数据库当已接入。
5. 将npm start和双击启动迁移到FastAPI；开发模式Vite代理API，生产模式FastAPI提供dist，同源访问。
6. 增加FastAPI隔离测试，验证权限、持久化、规则、执行结果、取消超时、服务密钥、SPA和错误接口；运行vue-tsc和Vite构建。
7. 停止旧Node服务，启动FastAPI，浏览器验证主页、菜单、画布、执行和报告，保存截图。
8. 更新README、API与迁移说明，记录当前能力边界、源码位置和后续数据库接入位置。

## 验收标准

- npm run build通过，生成dist；默认页面所有活动路由均由Vue 3渲染。
- FastAPI /api/health标明backend=fastapi，/docs可读取，未知API返回明确404而非HTML或伪成功。
- 不创建数据库连接、不安装业务数据库驱动、不读取旧.data；工作目录为.data-v3。
- 样例流程真实执行8条到7条，生成2条问题及预警；规则/实体可保存重启保留。
- 首页“数据治理”可直接进入质量模块和流程操作，无独立工作台孤立入口。
- 用户新增功能可从src/views、router和api/routers中开发，不修改mock/bodies。
