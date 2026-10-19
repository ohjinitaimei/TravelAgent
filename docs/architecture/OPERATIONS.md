# 资源限流与数据库恢复

适用范围：单个 FastAPI API 实例、SQLite WAL、本地空间或账号模式。账号身份由后端会话解析；客户端不能指定配额归属。配置在 `backend/.env`，默认值见 `.env.example`，修改后重启服务。不会更改已有推荐、路线排序和时间调度算法。

## 业务准入

| 资源 | 配置 | 默认限额 |
| --- | --- | --- |
| 新规划、需求草案、调整版本、原条件重试 | `TRAVEL_LIMIT_TASKS` / `TRAVEL_LIMIT_TASKS_GLOBAL` | 每用户 20 次 / 全局 60 次，每 300 秒 |
| 同一用户排队及执行中的任务 | `TRAVEL_LIMIT_ACTIVE_TASKS` | 3 个 |
| REST POI 搜索、详情、路线、工具连接检查 | `TRAVEL_LIMIT_TOOLS` / `TRAVEL_LIMIT_TOOLS_GLOBAL` | 每用户 60 次 / 全局 180 次，每 60 秒 |
| 工具连接检查（同时占用上面的 REST 配额） | `TRAVEL_LIMIT_TOOL_CHECKS` | 每用户每 60 秒 3 次 |
| REST 工具请求并发 | `TRAVEL_TOOL_CONCURRENCY` | 全局 4 个，繁忙时立即拒绝，不排队 |
| SSE 长连接 | `TRAVEL_LIMIT_STREAMS` / `TRAVEL_LIMIT_STREAMS_GLOBAL` | 每用户 3 条 / 全局 30 条 |

用户与全局次数采用从首个受理请求开始的固定窗口，计数写入 SQLite，重启不清零。窗口到期后重新计数；跨窗口可出现短时突发，这些数字不是滑动窗口或外部供应商每秒调用量保证。本地模式所有页面共用 `local` 配额。各配置须为正整数，非法配置导致启动失败。

任务创建先查询当前用户的提交收据，重复 `Idempotency-Key` 返回原任务且不重复计数，队列满时同样可查询原收据。配额扣减、新任务、原始请求和收据在同一 SQLite 事务中提交；拒绝请求不落任务记录，也不扣其他配额。新建重试任务会计数。工具请求在获得并发槽位、通过配额检查后计数，后续上游失败仍计数，防止故障期间反复消耗资源。

业务拒绝返回统一 `ErrorResponse`、HTTP 429 和 `Retry-After` 秒数，错误码为 `task_rate_limited`、`task_concurrency_limited`、`queue_full`、`tool_rate_limited`、`tool_busy` 或 `stream_limit`。共享客户端提供 `TravelApiError.retryAfterSeconds`；CORS 暴露该响应头。Web 展示等待提示，明确拒绝时清除未确认提交，不误判为断网，不自动重放 POST。网络丢失仍保留原条件并先查询收据。

查询任务、收据、历史行程、事件轮询、取消任务及退出登录不受上述业务次数限制。SSE 结束、取消或断线会释放槽位；SSE 限额拒绝后 Web 仍使用轮询。该控制不代替入口网关的连接数、防滥用和请求体限制。

任务管理器另保留全局队列容量 10、工作进程并发 2、总超时和取消终止。REST 的 4 个槽位不包含这 2 个工作进程；因此最多同时存在 4 个 REST 工具会话和 2 个任务工具会话。工作进程内继续使用原 MCP 调用次数和时间预算。任务准入次数限制不能直接等同于高德/模型的精确调用配额，正式授权后还须按供应商额度调整配置。

## 在线备份

从项目根进入 `backend`，使用安装过项目依赖的 Python。以下输出目录必须尚不存在，可按实际日期加序号命名：

```powershell
cd backend
python -m travel.backup create --output ../backups/2026-10-19-01
python -m travel.backup verify ../backups/2026-10-19-01
```

默认数据库遵循 `TRAVEL_DB_PATH` 或 `backend/data/travel.sqlite3`，也可使用 `create --db <源数据库>`。源库必须存在；命令不会创建空源库。服务可以保持运行，工具通过 Python 标准库 `Connection.backup` 获取一致性快照，覆盖已提交的 WAL 内容，不复制单独的主数据库文件。此方式遵循 [Python SQLite 在线备份接口](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)；复制过程设置 60 秒期限，持续繁忙时失败后可在低峰重试。

每份备份是独立目录，包含 `snapshot.sqlite3` 与最后写入的 `manifest.json`。清单记录格式版本、UTC 时间、SHA-256、文件大小和表记录数量，不输出账号、密码、Token 或行程内容。完成前检查 SQLite 完整性、所需表结构、业务模型、账号归属、任务结果与重试引用、行程版本和用户收据。缺少归属时拒绝，不通过旧库迁移逻辑自动归到本地空间。

备份含账号密码散列、会话散列、用户行程和输入，应存放在管理员控制的目录并使用受控的加密存储/异地保管。SHA-256 用于检测损坏，不是签名或加密；只恢复可信来源的备份。工具不复制 `.env` 或服务密钥，不提供数据库 HTTP 下载接口。`backups/`、SQLite 与运行数据均被 Git 排除；源码、测试和操作说明可以提交。

## 恢复演练与切换

1. 校验目标备份，停止 API（等待工作进程退出），保留现有数据库与伴随文件。
2. 恢复到一个全新的路径：

   ```powershell
   python -m travel.backup restore ../backups/2026-10-19-01 --db data/travel-restored-2026-10-19.sqlite3 --service-stopped
   ```

3. 将 `TRAVEL_DB_PATH` 指向恢复库的绝对路径，按 README 启动单个 API 实例，再启动 Web。
4. 重新登录，检查各账号的已保存行程、草案版本和提交收据；确认隔离后再恢复日常使用。

`--service-stopped` 是操作者的停服声明，工具不自动探测或停止其他进程。恢复命令绝不覆盖已有目标或 `-wal` / `-shm` / `-journal` 伴随文件；先在同盘临时目录校验、处理，再通过不覆盖目标的硬链接原子发布（需支持硬链接的 NTFS/POSIX 文件系统）。源数据库与备份保持原样，便于按同样的停服与路径切换步骤回退。

恢复保留用户、密码散列、任务请求、归属、收据、草案修订、行程版本和配额计数；撤销备份中的所有 Cookie/Bearer 会话。备份时尚未完成的任务转为 `failed / backup_restored`，追加真实恢复事件，有原请求时允许用户显式重试，不自动重放 Agent 或外部 API。账号配置恢复到备份时间点，若之后曾改密/禁用账号，应在开放服务前再次执行所需管理操作。

当前工具要求包含账号/归属表的当前数据结构；不兼容的历史库会拒绝校验。未实现定时备份、远端上传、加密密钥管理或多实例恢复。按部署环境确定备份周期和保留期限，实际切换前先在独立目录完成恢复演练。

## 本地验收

`tests/test_business_limits.py` 使用独立数据库验证持久化、窗口到期、用户/全局配额、原子扣减、任务去重、队列/并发拒绝、取消与查询可用、工具异常释放、SSE 回收及非法配置。`tests/test_backup.py` 在源 WAL 连接与未提交事务仍存在时备份，恢复后通过真实 API 登录两用户并核对归属，验证草案修订、收据、配额、会话撤销、任务终结、损坏/缺失归属拒绝及不覆盖已有文件。

共享客户端与 Chromium 另验证 HTTP 429 提示、未确认提交清理及用户再次提交。浏览器拒绝响应通过显式测试故障注入，真实后端限流由 HTTP 测试覆盖。全部使用 `tests/` 的 TEST ONLY 记录，不涉及真实个人数据库或外部 API。
