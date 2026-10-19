# Web 验收记录

验收环境：2026-10-19，Python 3.12、Node.js、Windows、Chromium Headless。本轮仅在本地运行，未上传至 GitHub 或运行云端检查；仓库保留可在 Ubuntu / Node.js 22 上执行的 CI 配置。

## 可复现检查

先按根 README 安装 Python、Node 与可选 Agent/MCP 锁定依赖，再执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_repository.py
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.cache/playwright"
npx playwright install --only-shell chromium
.\.venv\Scripts\python.exe scripts/verify_browser.py
.\.venv\Scripts\python.exe scripts/update_publish_manifest.py --check
```

Linux 浏览器首次安装使用 `npx playwright install --with-deps --only-shell chromium`，并设置 `export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/playwright"`。单独执行 `npm run test:browser` 需要专用服务地址；推荐使用上述 Python 编排脚本，自动启动并关闭隔离 API 和 Vite。

| 检查 | 数量 | 覆盖范围 |
| --- | ---: | --- |
| Python | 52 | 旅行 API 13、Agent 6、澄清 4、MCP 服务端 1、任务恢复 3、MCP 客户端 11、鉴权隔离 14 |
| TypeScript 客户端 | 12 | HTTP 契约、轮询期限/取消、暂时断线、提交收据恢复、表单与编辑状态、工具握手、账号绑定与恢复 |
| Chromium | 14 | 旅行工作台 8 项、账号流程 6 项 |
| Web / Schema | — | TypeScript 检查、Vite 构建、OpenAPI 生成文件一致性 |

浏览器场景：

1. 自然语言缺字段草案 → 用户补全与确认 → 来源和未处理需求保留 → 应用表单 → 更新草案时提示表单版本 → 刷新恢复。
2. 后端已受理但 POST 响应丢失 → 恢复同一提交 → 使用原任务 ID，无重复 POST。
3. 另一页面已更新草案 → 保存返回版本冲突 → 未保存答案保留 → 用户显式加载最新草案。
4. 暂时调用失败 → 修改当前表单 → 按原条件重试仍使用服务端原请求，新任务关联原任务，原失败记录保留。
5. SSE 不可用且短暂网络失败 → 有界退避轮询恢复 → 刷新后继续显示同一任务与行程。
6. 取消进行中的任务 → 状态终结 → 提供显式原条件重试。
7. 打开已保存多日行程 → 录入站点费用 → 编辑重算创建新版本 → 原行程可读，缺失费用仍为未知。
8. 预算页面主动检查数据工具 → 后端完成真实 MCP 握手 → 界面单列地图授权未配置，不将连接通过当作业务成功。

新增的 MCP 客户端检查使用实际 stdio 子进程：生产工具服务的成功输出 Schema（测试进程显式注入 FixtureProvider）、现有规划算法、已有 ToolRegistry、工具白名单、调用次数/总时限、握手/调用超时、意外退出、文本或非法业务结果拒绝、错误脱敏、生产固定命令/凭证边界，以及任务取消和超时后的子进程退出。`POST /tool-service/check` 还对真实随仓库提供的服务执行不消耗 Provider 配额的握手；生产任务在缺 Key 时失败且不保存虚假行程。

账号浏览器套件另启动 `--auth-fixtures` 的隔离服务，测试账号只存在于临时库中：登录错误、HttpOnly Cookie、刷新与退出；两用户的行程读取/调整隔离；跨标签页换号关闭旧空间；会话失效后重新登录；未确认提交不跨账号恢复；Bearer 登录与浏览器 Cookie 分离。后端还验证同名提交标识按用户去重、任务/事件/SSE/草案/重试的越权拒绝、CSRF/来源校验、密码重置/禁用/过期撤销、登录频率和会话上限、密码/Token 散列存储，以及旧库安全迁移和冲突回滚。

`scripts/verify_browser.py` 默认依次运行本地模式和账号模式，可用 `--suite local` 或 `--suite auth` 单独运行。脚本会清空测试子进程中的真实模型/地图凭证和浏览器地图配置。

## 数据与功能边界

测试服务必须显式传入 `--test-fixtures-only`，只绑定本机地址，数据库限制在仓库 `.tmp/`。FixtureProvider、固定模型回复和故障注入仅在 `tests/` 定义；生产服务不提供开启测试数据的配置。浏览器测试屏蔽外部 HTTPS，所有 POI 名称使用 TEST ONLY 标识。日志、截图和 trace 保存在被 Git 排除的 `artifacts/` 中，CI 仅在失败时上传测试诊断。

这些结果验证页面、API 与后端算法之间的调用和状态一致性。高德 POI、真实交通时间、地图 SDK 及授权限制需要取得合法 Key 后另行验收；票价、库存、评论等无授权来源时保持缺失。未使用测试数据替代生产接口结果。

当前验收范围为本机单 API 进程的 Web 工作台，覆盖本地模式及多账号数据隔离。公网 HTTPS、业务限流、运维备份、多实例队列和移动端真机在 [后续计划](RELEASE_STATUS.md) 单列。启用与迁移方法见 [AUTH_ISOLATION.md](architecture/AUTH_ISOLATION.md)。

## API 恢复约定

创建规划、草案、编辑或重试任务可携带 `Idempotency-Key`（8–128 位字母、数字、下划线、点、冒号或连字符）。同一标识与同一请求返回原任务；标识复用于其他请求返回 `409 idempotency_conflict`。未传标识的旧客户端保持原行为。

`GET /api/v1/travel/submissions/{key}` 查询提交收据。Web 在发送前保存请求快照与标识；页面刷新只查收据，未找到时等待用户显式恢复。临时网络失败保留快照，明确拒绝的请求清除快照。

`POST /api/v1/travel/tasks/{id}/retry` 仅允许可重试的失败、超时或取消任务，沿用服务端保存的请求，创建关联 `retry_of` 的新任务。旧记录没有请求快照时禁止伪造重试。SQLite 以新增表兼容已有记录。
