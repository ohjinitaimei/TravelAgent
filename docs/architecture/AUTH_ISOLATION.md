# 账号、会话与用户数据隔离

本地交付日期：2026-10-19。代码保存在本地分支，不上传 GitHub。实现使用 Python 标准库、现有 FastAPI/Pydantic/SQLite 和 Vue，不升级核心依赖。

## 启用与运行

默认 `TRAVEL_AUTH_MODE=local` 延续原有本地空间。该模式只能访问归属 `local` 的记录，不会展示账号模式下其他用户的记录。

在新克隆的项目根目录完成 README 中的依赖安装后，先创建账号：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m travel.accounts create alice
Pop-Location
```

密码在本机隐藏输入两次，长度 15–128 个字符；不提供默认账号、公开注册或密码命令行参数。账号名为 3–40 位字母、数字、点、下划线或连字符，按小写保存。

在 `backend/.env` 配置后重启原 FastAPI：

```dotenv
TRAVEL_AUTH_MODE=session
TRAVEL_SESSION_TTL=28800
TRAVEL_SESSION_IDLE_TTL=1800
TRAVEL_COOKIE_SECURE=0
TRAVEL_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Web 自动进入登录页，没有可用账号时显示联系管理员的提示。localhost HTTP 使用 `TRAVEL_COOKIE_SECURE=0`；HTTPS 部署使用 `1`，并明确配置前端来源和可信反向代理。推荐同源代理，保持 Web 页面和 `/api/v1/travel` 在同一来源。不支持跨站第三方 Cookie。未知模式、无效时限或账号模式中的通配 CORS 来源会阻止启动。

管理员在 `backend/` 运行以下命令：

```powershell
..\.venv\Scripts\python.exe -m travel.accounts reset-password alice
..\.venv\Scripts\python.exe -m travel.accounts disable alice
..\.venv\Scripts\python.exe -m travel.accounts enable alice
```

重置密码、禁用或重新启用均撤销该账号的已有会话。新会话需重新登录。账号管理仅通过可信服务器终端操作，不存在前端提权或账号管理 API。

## API 契约

| 接口 | 行为 |
| --- | --- |
| `GET /api/v1/travel/auth/status` | 当前模式、登录状态、用户、Cookie 会话 CSRF Token、绝对到期时间、是否需配置账号 |
| `POST /api/v1/travel/auth/login` | `username`、`password`、`transport: cookie/bearer`；默认 Cookie |
| `POST /api/v1/travel/auth/logout` | 撤销当前会话；Cookie 模式同时清除 Cookie |

Cookie 登录须携带 `X-Travel-Client: web`。返回的 `access_token` 为 null，会话由浏览器保存为 HttpOnly、SameSite Strict、限定 API 路径的 Cookie。Web 从 status 接口取得 CSRF Token，只保留在当前空间的内存中，写操作携带 `X-CSRF-Token`。

原生客户端可指定 `transport: bearer`，从返回的 `access_token` 取得不透明 Token，后续使用 `Authorization: Bearer ...`。不设置浏览器 Cookie，不要求 CSRF Header；应使用设备安全存储，Token 不进入 URL。共享 TypeScript 客户端已提供 `authStatus()`、`login()`、`logout()`；具体 uni-app 真机接入仍在后续阶段。

`X-Workspace-User` 可绑定页面预期的用户 ID；不一致时返回 `409 workspace_identity_changed`，防止共享 Cookie 在另一标签页换号后使用旧表单提交。此 Header 只用于校验，不能指定或覆盖服务端的身份。

账号模式保护所有统一旅行业务接口，包括地图数据查询和工具连接检查；旧 `/api/*` 入口关闭，避免绕过鉴权消费工具或读取历史数据。未登录返回 `401 authentication_required`，跨用户资源返回与不存在一致的 404，CSRF/来源错误返回 403。401 响应带 `WWW-Authenticate`，登录限流带 `Retry-After`。认证和旅行响应设置 `Cache-Control: no-store`。

## 会话与密码

使用标准库 scrypt，参数 `N=2^17,r=8,p=1`，每个密码有随机盐；不保存明文或可逆密码。并发密码验证最多两个，登录还按账号和客户端地址限制频率。未知账号与密码错误使用相同响应，未知账号也执行密码散列验证。

会话 ID 使用随机 256 位数据生成，数据库只存 SHA-256 摘要。默认绝对期限 8 小时、闲置期限 30 分钟，每账号最多 5 个会话；Cookie 登录换号会撤销被替换的旧 Cookie 会话。每次请求检查数据库中的用户状态和会话有效期，SSE 也在循环中复查，撤销后停止发送进度。

这些选择参考 [OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[CSRF 防护](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) 和 [FastAPI Cookie 接口](https://fastapi.tiangolo.com/advanced/response-cookies/)。本模块不提供 OAuth、MFA、邮件找回或独立身份服务。

## 数据归属与迁移

在同一 SQLite 增加 `resource_owners` 和 `user_submissions`，保留原表和 JSON 内容。旧记录标为 `local`，不会分给首个登录账号。原全局提交标识按任务归属迁移到用户作用域；两个用户可使用相同 `Idempotency-Key`，不会读到或复用对方的任务。

新任务的用户 ID 由认证结果确定，不接受前端传入的 owner。工作进程保存草案、行程及调整版本时沿用原任务归属；重试先验证原任务属于当前用户，再创建同归属的新任务。接口按归属检查单个资源，并在 SQL 中筛选行程列表。

如需将旧本地空间归属于已有账号，先停止后端并备份数据库，在 `backend/` 显式执行：

```powershell
..\.venv\Scripts\python.exe -m travel.accounts claim-local alice --service-stopped
```

只变更 `local` 记录和其提交收据的归属，保留原 ID、内容及来源；存在未结束任务或提交标识冲突时拒绝并回滚，不删除记录。操作可用 `--db` 显式选择数据库。此命令不会自动执行，本轮也未迁移真实个人记录。

## Web 账号切换

登录状态由新的根组件处理。每次登录创建独立、绑定用户 ID/CSRF 的客户端和请求取消信号；退出或身份失效时卸载工作台、关闭 SSE 并终止旧请求。旧客户端不能在新账号下发起后续请求。

浏览器恢复状态以用户 ID 区分，只保存自己的输入与资源 ID，不保存密码、Token 或 Provider 数据。显式退出会清理该用户的浏览器恢复记录；会话失效后，同一用户重新登录可继续核对自己的表单。另一标签页的登录/退出仅广播随机变化标记，使旧页面返回登录状态，不自动进入另一个账号。

退出不会取消后台已受理任务：任务继续按原用户保存，其他用户不能查看。未确认提交也不会转移给新账号。

## 验收与边界

`scripts/verify_repository.py` 包含 14 项鉴权检查；`scripts/verify_browser.py` 另运行 6 项真实浏览器账号场景和原有 8 项工作台场景。账号、密码和旅行成功数据均为显式 TEST ONLY 输入，只存在于隔离临时库；不创建真实默认账号、不读取个人库、不使用真实 API 凭证。

当前仍为单 API 实例；公网 TLS/代理信任、业务配额/资源限流、备份恢复和多实例队列应分别验收。本模块的本地通过结果不代表这些部署能力已验证。

## 主要文件

- 后端：`travel/auth.py`、`accounts.py`、`store.py`、`tasks.py`、`api.py`、`runtime.py`、`schemas.py` 和 `main.py`。
- Web：`WorkspaceRoot.vue`、`WorkspaceShell.vue`、`workspaceTransport.ts`、`api.ts`、`session.ts`、`App.vue` 和工具检查组件。
- 契约：`packages/api-schema/client.ts` 及生成的 OpenAPI/TypeScript 类型。
- 验证：`tests/test_auth.py`、`auth_client.test.ts`、`browser/auth.spec.ts`，以及隔离服务与检查脚本。
