# HTTPS 部署与上线验收

日期：2026-10-20。方案：Caddy 提供生产 Web 静态文件、HTTPS 和同源代理；一个 Uvicorn/FastAPI 实例绑定 `127.0.0.1:8000`，继续使用既有 SQLite、任务工作进程、Provider/MCP 和算法。此阶段完成本机配置与验收，没有操作公网服务器、安装系统服务或上传 GitHub。

```text
浏览器 ── HTTPS ── Caddy ── /assets、/ ── apps/web/dist
                       └─ /api、/health ── 127.0.0.1:8000
                                            ├─ SQLite：/var/lib/travelagent
                                            └─ 既有任务、工具和真实授权 API
```

## 入口与配置

- `deploy/Caddyfile`：HTTPS 静态站点及显式 HTTP 308 跳转；API、健康检查转发；SSE 立即刷新；请求体上限 64 KB。入口覆盖客户端传入的转发来源，不信任外部 `Forwarded`。HTML 不长期缓存，带哈希的 assets 可缓存一年；缺失文件保留 404，不返回伪造的 HTML 成功结果。网关拒绝使用 JSON 错误，后端响应及 `Retry-After` 原样传递。
- `deploy/backend.env.example`：账号模式、Secure Cookie、精确 HTTPS 来源、独立数据目录和现有限额。模型/地图凭证只填入其私有副本。没有配置授权时业务明确失败。
- `deploy/gateway.env.example`：域名、HTTP 来源、回环上游、dist 与证书目录；不允许填入后端密钥。公开域名的 `TRAVEL_TLS` 保持空，使用公开证书。JS 浏览器 Key 在构建时配置，安全密钥仍在后端。
- `deploy/travelagent-api.service`：非 root 运行、一个 worker、只信任回环代理、关闭 URL 访问日志、受限写目录、停止时退出所属工作进程。`deploy/caddy-override.conf` 为发行版官方 Caddy 服务的 drop-in，复用其账号和证书目录。

SSE 配置依据 [Caddy 反向代理文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#streaming)。服务托管依据 [Caddy 官方 systemd 说明](https://caddyserver.com/docs/running#linux-service)。模板面向直接对外的单台主机；增加 CDN、负载均衡或第二个 API 实例前需要重新设计可信代理与持久化队列，不能直接增加 workers。

## Linux 专用主机安装步骤

以下是操作说明，本机 Windows 未执行 systemd 安装。先准备 Python 3.12、Node.js 22.12+、锁定项目依赖和官方 Caddy 2.11.7，确认 `caddy version`。将本地验收过的源码放在 `/opt/travelagent`，源码与构建只读；账号 `travelagent` 为系统服务账号，不是 Web 登录账号。发行版 Caddy 包应已建立 `caddy` 用户和官方服务。

```bash
cd /opt/travelagent
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.travel.lock.txt
npm ci
# 如启用地图，在 apps/web/.env.local 中仅配置 VITE_AMAP_JS_KEY。
# 模型和安全密钥不进入 VITE 变量。按 README 安装可选 Agent/MCP 锁定依赖。
npm run build

sudo useradd --system --home-dir /var/lib/travelagent --shell /usr/sbin/nologin travelagent
sudo install -d -m 0750 -o travelagent -g travelagent /var/lib/travelagent
sudo install -d -m 0750 -o root -g caddy /etc/travelagent
sudo install -m 0600 deploy/backend.env.example /etc/travelagent/backend.env
sudo install -m 0640 -o root -g caddy deploy/gateway.env.example /etc/travelagent/gateway.env
```

编辑两个配置副本，将 `travel.example.com` 换成自己的域名，保持 HTTP/HTTPS 同域、后端 CORS 来源与 HTTPS 来源一致。DNS 指向该主机，入口开放 TCP 80/443；API 8000 和管理接口 2019 保持回环绑定，不做端口转发。证书数据由 Caddy 账号写入 `/var/lib/caddy/travelagent`，业务库不放在源码或静态目录。无需把任何数据库放入 Web root。

```bash
sudo .venv/bin/python scripts/check_deployment.py \
  --backend-env /etc/travelagent/backend.env \
  --gateway-env /etc/travelagent/gateway.env
sudo -u caddy /usr/bin/caddy validate --config /opt/travelagent/deploy/Caddyfile \
  --adapter caddyfile --envfile /etc/travelagent/gateway.env

# 创建首个 Web 登录账号，密码在隐藏提示中输入；不写命令行或配置文件。
cd /opt/travelagent/backend
sudo -u travelagent ../.venv/bin/python -m travel.accounts create owner \
  --db /var/lib/travelagent/travel.sqlite3
cd /opt/travelagent

sudo install -m 0644 deploy/travelagent-api.service /etc/systemd/system/travelagent-api.service
sudo install -d /etc/systemd/system/caddy.service.d
sudo install -m 0644 deploy/caddy-override.conf /etc/systemd/system/caddy.service.d/travelagent.conf
sudo systemctl daemon-reload
sudo systemctl enable --now travelagent-api
curl --fail http://127.0.0.1:8000/health/ready
# 首次应用 ExecStart 与环境配置时重新启动已有的官方 Caddy 服务。
sudo systemctl enable caddy
sudo systemctl restart caddy
```

本轮未修改数据结构或升级依赖。`backend.env` 由 systemd 在切换服务账号前读取，不必让服务账号读取该文件。不要运行带凭证的 `--environ` 或开启请求头/完整 URL 调试日志。目录写权限和 systemd 限制必须在目标 Linux 机上实测，不能用 Windows 的结果代替。

## 预检、健康检查和只读上线检查

`scripts/check_deployment.py` 只读指定配置及 dist，检查生产开关、账号模式、Secure Cookie、精确 HTTPS 来源、回环上游/管理端口、发布文件、库/证书目录与静态文件的分离，以及已配置后端凭证未被打进构建。不打印凭证，不创建数据库；通过不代表已验证 DNS、供应商授权或 Linux 文件权限。

健康入口不需登录、无外部调用、不泄露配置或业务记录，均禁止缓存，且不加入业务 OpenAPI：

| 入口 | 含义 |
| --- | --- |
| `/health/live` | 进程可响应，返回 `{"status":"alive"}` |
| `/health/ready` | 任务管理器与 SQLite 可读取，返回 `{"status":"ready"}`；未初始化、库错误或无法在 100 ms 内取得库锁时返回 503，正文只有 `unavailable` |

健康检查不表示高德/模型已授权、配额充足或有空闲任务槽。读库失败不输出原始错误、文件路径或凭证。

```bash
.venv/bin/python scripts/smoke_deployment.py \
  --origin https://自己的域名 --http-origin http://自己的域名
```

该命令始终校验证书，不提供跳过 TLS 校验参数。它只读取健康、HTML/assets、匿名身份和应被拒绝的路径，不登录、不创建任务、不调用地图上游。检查缓存、响应头、401/410、缺失文件 404 及 HTTP 跳转。正式账号和真实供应商数据的人工验收另按 [ACCEPTANCE.md](../ACCEPTANCE.md) 与 [AMAP_PROXY.md](AMAP_PROXY.md) 执行，不能仅靠入口只读检查宣称业务验收通过。

## 本地 HTTPS 实际联调

获取 [官方 Caddy 2.11.7](https://github.com/caddyserver/caddy/releases/tag/v2.11.7) 并按同版本 checksums 文件的 SHA-512 校验。可执行文件不纳入 Git。Windows 本次将它保存在被忽略的 `.tmp/tools/caddy/caddy.exe`，在仓库根执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_deployment.py --caddy .tmp/tools/caddy/caddy.exe
```

脚本使用临时端口、独立数据库、生产构建和临时 CA，启动同一份 Caddyfile 与显式 TEST ONLY API。私有 CA 仅交给本次 HTTP 客户端作为信任根，证书验证保持开启；不安装根证书、不安装系统服务、不使用 `verify=False`。所有监听器绑定回环，结束时按各自控制入口优雅关闭。Caddy 的数据、配置与证书目录均限制在临时目录内。

本机最终通过 **29 项 HTTPS 检查**：包括只读入口检查，以及 HTTPS 转发后登录、Secure/HttpOnly/SameSite Cookie、CSRF 拒绝、异步任务受理、同一标识去重、SSE 在慢任务结束前收到进度和成功终态、保存结果读取、退出后 401，以及入口大请求的 JSON 413。首轮登录 403 已定位为测试服务覆盖了 CORS 来源；测试编排改用同一 HTTPS 来源后通过，生产鉴权规则保持不变。

报告与日志位于 `artifacts/deployment/`，含运行状态、检查名称、Caddy 版本、时间、TLS 验证与系统信任未改动标记，均被 Git 排除。新运行先标记 running，失败写 failed，不沿用上一轮成功状态。成功行程只来自 tests 中隔离记录；没有新增真实高德/模型调用，没有验证公网 ACME、正式域名、浏览器 TLS 信任或 Linux systemd 启停。默认 CI 增加健康和预检回归，完整 HTTPS 脚本须单独提供 Caddy，不自动下载或触发发布。

本轮另通过后端 101 项、共享客户端 23 项、类型/构建和契约一致性，以及 Chromium 原账号套件 10 项复查。三引擎 42 个场景的完整基线保留上轮记录，本轮没有重复全部矩阵。健康/配置新增 9 个逻辑用例后，完整检查集规模为 166 个逻辑用例、250 次执行；29 项 HTTPS 联调单独计数。

## 本轮文件

新增 `backend/travel/health.py`、`deploy/` 中 5 个配置模板、`scripts/check_deployment.py`、`scripts/smoke_deployment.py`、`scripts/verify_deployment.py`、`tests/test_health.py`、`tests/test_deployment_config.py` 及本文。修改后端路由注册、仓库检查入口、显式测试服务的 Secure Cookie 参数、Git 排除规则、README/验收/状态/运维文档与源码清单。没有改前端业务代码、生产数据算法或依赖锁文件。

## 更新与回退

更新前使用 [OPERATIONS.md](OPERATIONS.md) 的在线备份命令，显式指定 `/var/lib/travelagent/travel.sqlite3`，将快照写入专用备份目录并校验；不要以复制主库文件代替 WAL 快照。保留上一份已验收源码与 dist，先在独立目录构建并预检，再安排单实例停服更新。重新启动 API、检查 ready，再检查入口和账号；不得启动两个 API 同时接管同一任务库。

本轮没有数据库迁移，代码回退可在停服后恢复上一份源码与 dist，保持数据目录。若确需回退数据库，先停 API、保留当前库和伴随文件，按恢复工具写入全新 `/var/lib/travelagent/` 路径并验证，再修改 `TRAVEL_DB_PATH` 后启动。恢复撤销会话、中断任务须显式重试，详细行为遵循既有备份工具。此处不自动覆盖库、切换线上配置或删除旧版本。

后续已补充源码/Web 发布包、归档启动检查，以及定时备份命令/保留策略和 timer 模板，见 [RELEASE_BACKUP.md](RELEASE_BACKUP.md)。目标主机仍需验证正式 DNS/ACME、域名授权、实际权限、服务重启、timer 和恢复，再按供应商额度调整限额；当前模板不提供多实例队列、自动异地备份或零停机发布。

暂无服务器时，可先执行 [LOCAL_RECOVERY.md](LOCAL_RECOVERY.md) 的发布包 HTTPS 在线备份、恢复和回退流程。本地 58 项已通过，但不替代上述 Linux/公网检查。
