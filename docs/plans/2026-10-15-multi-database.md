# 常见数据库兼容 Implementation Plan

**Goal:** 将现有只读采集扩展为PostgreSQL、MySQL/MariaDB、SQL Server、Oracle、SQLite、MongoDB、ClickHouse共8个选择，保留本地快照与治理闭环。

**Architecture:** 保留原始库格式及平台结构版本3。连接器统一info/tables/describe/batches/cancel/close接口，前端从后端连接器目录读取能力和表单默认值；源配置仅保存非敏感参数。各驱动固定只读查询、标识符转义、参数化元数据查询并分批读取。

**Tech Stack:** Vue3/FastAPI/sqlite3/psycopg/PyMySQL/python-tds/python-oracledb/PyMongo/clickhouse-connect。

## ADR与边界

- 选择各厂商/协议Python驱动，SQL Server用纯Python TDS，Oracle用Thin，降低ODBC及客户端依赖；统一SQLAlchemy无法统一文档库及快照语义，通用JDBC桥接要求额外Java服务，暂不采用。
- PostgreSQL保留READ ONLY+REPEATABLE READ；MySQL/MariaDB用一致只读事务，严格模式只接收InnoDB表；Oracle用SET TRANSACTION READ ONLY；SQLite用mode=ro/query_only及显式读取事务；SQL Server使用只读意图和固定SELECT，严格模式要求SNAPSHOT已启用，不修改服务器设置。
- MongoDB严格模式需5.0+副本集/分片的snapshot session，原始每条文档保存_id及完整Extended JSON；普通单机可显式选择尽力读取。ClickHouse固定只读查询，仅本地存储引擎，不承诺跨表一致事务，需显式选择尽力读取。状态与快照元数据记录实际一致性，不能伪装为统一repeatable read。
- SQLite文件路径是后端机器上的绝对路径，不接受URI或相对路径；只读打开已有文件，排除虚拟表。不上传或移动用户数据库文件。
- 通用表标识为稳定53位内数字（PG保留OID），不会因表排序变化错选。标识符按方言引用；二进制、时间、Decimal、复杂值无损保留为文本，原始库与治理副本分离。
- 密码仅当次使用；TLS可选强制模式，CA路径为后端本机证书；不更改远程账号、权限、隔离设置的数据库级配置或服务器文件。
- 实测等级独立记录：现有PostgreSQL及本机SQLite真实端到端；其他连接器驱动契约测试，若无对应真实实例明确说明，不能宣称所有版本已实库认证。Docker引擎目前未运行，不主动改系统服务。

## 步骤

1. 新增统一目录、配置校验、类型规范、稳定表标识；保留PG连接器回归。
2. 实现MySQL/MariaDB、SQL Server、Oracle与SQLite只读目录/结构/游标。
3. 实现MongoDB文档保真与ClickHouse只读流式采集，记录一致性限制。
4. 接入原始库管理器、健康检查、源保存与API连接器目录，不做不必要的表结构迁移。
5. 更新Vue类型选择、默认端口、Oracle服务/SID、SQLite路径、Mongo认证库、TLS与一致性选项，移除“仅登记”提示。
6. 补充隔离测试及本机SQLite端到端测试；完整回归、构建与浏览器验收；复核已有238表快照及276行治理记录保留。
7. 更新兼容矩阵、指南、README/API与验证结果，保持服务运行。

## 完成记录

已完成1—7。版本3.4.0，结构3仍49表；8类驱动均已安装。76项回归通过，另1项MySQL真实实例测试单独通过（默认跳过）。MySQL9.3独立实例完成TLS/只读、10,021行采集及21行治理后已关闭；SQLite真实文件及浏览器15行采集/12行清洗质量闭环通过。59页面检查通过。已有238表/96,739行训练快照SHA256未变，原有平台记录保留；未再连接远程训练库。其他数据库仅契约测试的范围已明确写入兼容矩阵。详见多数据库验收-2026-10-15.md。
