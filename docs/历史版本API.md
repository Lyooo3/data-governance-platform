# 后端接口与流程格式

HTTP基址：`http://127.0.0.1:4173`。使用JSON请求体；成功响应为 `{code:200,success:true,data:...}`，失败返回对应HTTP状态及 `success:false`。认证使用HttpOnly的gov_session Cookie，或Bearer会话令牌；原回放token不代表真实权限。

## 身份

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 无需登录，后端模式和连接器 |
| POST | `/api/auth/local-session` | 同源浏览器创建本机会话，需要LOCAL_AUTO_LOGIN |
| POST | `/api/auth/login` | `{name,password}`密码登录 |
| GET | `/api/auth/me` | 当前账号 |
| POST | `/api/auth/logout` | 撤销会话 |
| GET/POST | `/api/auth/users` | 管理员列出或创建账号，角色admin/reader |

浏览器请求需同源Origin，禁止跨站请求；命令行可以不发送Origin。密码至少10位。只读用户不能修改配置或执行任务。

## 资源CRUD

所有资源路径以 `/api/governance/` 开头：

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/{kind}` | 分页，pageNum/pageNumber、pageSize、searchContent及实体字段过滤 |
| POST | `/{kind}` | 新增，管理员 |
| GET | `/{kind}/{id}` | 详情 |
| PUT/PATCH | `/{kind}/{id}` | 修改，管理员 |
| DELETE | `/{kind}/{id}` | 删除配置，管理员 |

kind：sources、workflows、elements、businessTypes、qualifiers、dictionaries、catalogs、assets、rules、qualityTasks、services、projects、tables。

列表返回list/rows/content和total/totalElements兼容字段。代码集条目使用dictionaryDetails。删除资产配置不会删除源表。被流程、任务或服务引用的数据源不可删除。

## 数据源

```json
{"name":"业务MySQL","type":"mysql","host":"127.0.0.1","port":3306,"database":"your_database","user":"your_user","password":"your_password","allowWrite":false,"tls":false}
```

SQLite由平台生成受管理文件，不接受任意路径。编辑时密码留空保留原密码，响应不返回连接口令。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| POST | `/api/governance/sources/{id}/test` | 检查连接 |
| GET | `/api/governance/sources/{id}/tables` | 表名和schema |
| GET | `/api/governance/sources/{id}/columns?table=...` | 字段结构 |
| GET | `/api/governance/sources/{id}/preview?table=...&pageNum=1&pageSize=20` | 数据库内分页预览，可用sql替代表名 |
| POST | `/api/governance/sources/{id}/sync` | 持久化表字段元数据 |
| POST | `/api/governance/sources/{id}/import` | `{table,rows}`写入新表，需启用写入 |

SQL只接受单条SELECT/WITH查询，拒绝注释、多语句和写指令，连接使用只读模式。节点不执行用户JavaScript。

## 流程格式

```json
{
  "name":"单位名称检查",
  "nodes":[
    {"id":"a","type":"source","x":40,"y":70,"config":{"sourceId":"demo-source","table":"demo_records"}},
    {"id":"b","type":"clean","x":290,"y":70,"config":{"fields":["org_name"],"operation":"trim"}},
    {"id":"c","type":"quality","x":540,"y":70,"config":{"ruleIds":["rule-required"]}},
    {"id":"d","type":"output","x":790,"y":70,"config":{}}
  ],
  "edges":[{"source":"a","target":"b"},{"source":"b","target":"c"},{"source":"c","target":"d"}]
}
```

需要一个source、一个output及全部连线，暂不支持循环、分支或多表合并。保存与执行都会校验。

| 节点 | config |
| --- | --- |
| source | sourceId、table，可选sql，填写时优先 |
| select | mappings数组：`{from,to}` |
| clean | fields数组、operation：trim/upper/lower/number/fill，fill使用value |
| filter | field、operator：eq/ne/contains/notEmpty/gt/lt、value |
| dedupe | fields组合键，保留第一条 |
| quality | ruleIds或内联rules，dropInvalid=true过滤问题记录 |
| output | 默认平台结果库；sourceId和table可另存新表 |

质量规则类型：required、unique、regex（pattern）、range（min/max）、enum（values）。唯一性将所有重复键记录计为问题；空集合合格率为null。failedIndexes针对质量节点当时输入顺序，每条规则最多展示100个索引。

## 执行与结果

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| POST | `/api/governance/workflows/{id}/run` | 执行已保存流程 |
| POST | `/api/governance/qualityTasks/{id}/run` | 根据sourceId/table/ruleIds检测 |
| GET | `/api/governance/runs` | 运行列表 |
| GET | `/api/governance/runs/{id}` | 状态、步骤、报告、来源 |
| POST | `/api/governance/runs/{id}/cancel` | 取消任务 |
| GET | `/api/governance/runs/{id}/rows` | 结果分页 |
| GET | `/api/governance/runs/{id}/export` | CSV结果 |
| GET | `/api/governance/summary` | 平台计数 |
| GET | `/api/governance/audit` | 管理员审计 |

状态：RUNNING、SUCCESS、FAILED、CANCELLED、TIMED_OUT、INTERRUPTED。重启不自动重试，避免重复输出。CSV对公式起始字符加前缀。

## 数据服务

services配置需要name、sourceId、table，可选fields数组。POST `/api/governance/services/{id}/publish` 返回endpoint和一次显示的apiKey。GET `/api/published/{id}/query?pageNum=1&pageSize=20`需 `X-API-Key` 请求头，仅支持分页，不提供任意SQL。

重新发布使原密钥失效。修改配置取消发布，需重新发布。调用记录写入审计，单服务每分钟最多60次，本进程计数。

## 原前端兼容

`backend/legacy.mjs`适配身份、菜单、项目、标准、目录、元数据、质量与运行统计。菜单结构取自原页面配置，业务数据来自平台库及数据源。没有导入原快照里的账号、连接口令和业务记录。

未实现原厂业务返回501，不替换为录制成功响应。缺失的原前端页面无法仅靠补后端恢复，工作台提供本版业务操作入口。
