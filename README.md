# TravelAgent · 旅行规划工作台

TravelAgent 将自然语言旅行需求整理为可核对草案，再由统一 FastAPI 后端查询授权数据，复用已有推荐、排序和时间调度算法生成行程。模型不负责计算真实交通时间或路线成本，缺失数据不以模拟地点、价格、评论或交通降级补齐。

## 当前可用范围

| 模块 | 状态 |
| --- | --- |
| Vue3 / TypeScript / Vite PC 工作台 | 已实现规划表单、草案核对、执行状态、地图容器、多日时间轴、POI、编辑、预算和保存页面 |
| HelloAgents 需求提取 | 单 Agent 适配已实现，历史环境已完成真实模型验证 |
| 草案澄清 | 同一 ID 多轮补充、字段确认、来源标记、修订冲突保护，不再次调用模型 |
| 统一任务服务 | 有界工作进程、SQLite、SSE、轮询、取消、超时、原条件重试、提交去重和断线恢复 |
| POI / 路线 | 已通过授权高德 POI、步行/驾车路线、多日规划、编辑重算及浏览器底图/标记/折线的本地真实联调 |
| 推荐 / 排序 / 调度 | 复用既有后端算法；生产入口不读取旧测试 POI |
| MCP | 可选 stdio 客户端与服务端，规划/查询复用同一 Provider，支持调用限额、超时、取消及结构化结果校验 |
| App | 保留原 Flutter 源码；apps/mobile 是后续 uni-app 预留说明，不是可运行 App |
| 账号与数据隔离 | 可选登录模式，按用户隔离任务、草案、行程和提交收据；保留本地空间模式 |
| 部署 | 单 API 实例；用户/全局业务配额、工具/SSE 并发控制、SQLite 在线备份与恢复校验 |

自动验收覆盖 API、共享客户端及 Chromium 页面交互，使用 tests 中隔离的 TEST ONLY 数据。2026-10-19 另通过授权高德真实数据联调，覆盖直接 Provider、MCP 和 Web 保存行程展示；密钥与运行记录不进入 Git，克隆后须配置自己的授权。详见 [验收记录](docs/ACCEPTANCE.md)、[真实高德联调](docs/architecture/LIVE_AMAP.md) 和 [功能范围与后续计划](docs/RELEASE_STATUS.md)。

## 工程结构

```text
apps/web/               Vue3 PC 工作台
apps/mobile/            未来 uni-app 接入说明
packages/api-schema/    OpenAPI、生成的 TS 类型和共享客户端
backend/travel/         Schema、Provider、Tools、任务、持久化和 API
backend/agent/          既有受控协调器与 HelloAgents 适配
backend/services/       既有推荐、排序、调度模块
tests/                  隔离测试，不作为生产数据入口
scripts/                契约生成、检查与显式真实联调脚本
lib/ android/ windows/  保留的 Flutter 历史客户端
docs/                   当前状态、架构审计和历史记录
```

## 安装

环境：Python 3.12、Node.js 22.12+、npm。依赖有锁文件；不要未经兼容性验证升级核心依赖。

```powershell
git clone https://github.com/ohjinitaimei/TravelAgent.git
cd TravelAgent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.travel.lock.txt
npm ci
Copy-Item backend/.env.example backend/.env
```

Linux/macOS 使用 `python3 -m venv .venv`、`.venv/bin/python` 和 `cp backend/.env.example backend/.env`。

### 启动 Web 与后端

```powershell
# 终端一：仅绑定本机，单实例、单 worker
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
# 终端二
npm run dev
```

访问 <http://127.0.0.1:5173/>；接口文档 <http://127.0.0.1:8000/docs>，统一前缀 `/api/v1/travel`。如 8000 被占用，可改后端端口，并在启动 Web 前设置 `$env:TRAVEL_BACKEND_URL='http://127.0.0.1:18000'`。

示例默认 `TRAVEL_PRODUCTION=1`，关闭旧 `/api/route/`、`/api/map/`、`/api/eval/`、`/api/context/` 数据入口。仍须自行完成鉴权等部署改造，不能把该开关当成生产安全保证。

### 可选：模型需求整理

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.helloagents.txt -c backend/requirements.travel.lock.txt
```

在后端 `.env` 配置自己的 DASHSCOPE_* / OPENAI_*，或 TRAVEL_LLM_API_KEY、TRAVEL_LLM_BASE_URL、TRAVEL_LLM_MODEL，设置 `TRAVEL_AGENT_ENABLED=1` 和 `LLM_INTENT_DISABLE_LLM=0` 后重启后端。模型需支持原生 Function Calling；自定义地址填兼容服务根路径（如 `/v1`）。全部凭证留在后端。

没有模型配置时可直接填写结构化表单；没有高德 Key 时可以运行工作台和需求整理，但 POI/路线查询会明确失败。

### 可选：真实地图与路线

- 后端高德 Web 服务 Key：填入 `backend/.env` 的 `AMAP_WEB_KEY`，按账号设置合法权限和配额，重启后端。
- 浏览器地图使用独立的 JS API Key：复制 `apps/web/.env.example` 为 `.env.local`，配置 `VITE_AMAP_JS_KEY` 与 `VITE_AMAP_SECURITY_CODE` 及域名白名单。
- 不要把后端密钥放入 VITE 变量；VITE 变量会进入浏览器构建产物。
- 地点评分、营业时间和消费字段可能缺失；预算未知项不视为免费，预约与未来日期营业状态尚未验证。

### 可选：通过 MCP 调用数据工具

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.mcp.txt -c backend/requirements.travel.lock.txt
```

在 `backend/.env` 设置 `TRAVEL_TOOL_TRANSPORT=mcp`，重启同一后端即可。默认 `direct` 保持直接 Provider 调用。MCP 模式使用后端启动的固定本机 stdio 服务；客户端、模型和 HTTP 请求不能指定服务命令。Web 的“预算与约束 → 数据工具连接”可检查握手，不调用地图或模型接口。

连接通过与地图授权分别显示；缺 Key 时数据查询仍明确失败。MCP 调用失败不切换到其他传输或测试数据。参数、限额和已验证链路见 [MCP 客户端接入说明](docs/architecture/MCP_CLIENT.md)。

### 启用登录与个人空间

默认 `TRAVEL_AUTH_MODE=local` 保持原有本地空间。要启用独立账号，先创建账号（密码通过隐藏提示输入，不提供默认账号）：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m travel.accounts create alice
Pop-Location
```

在 `backend/.env` 设置 `TRAVEL_AUTH_MODE=session` 后重启后端，Web 会显示登录页面。localhost HTTP 使用 `TRAVEL_COOKIE_SECURE=0`；HTTPS 部署设为 `1` 并配置明确的 `TRAVEL_CORS_ORIGINS`。推荐 Web 与 API 使用同源代理。

Web 使用 HttpOnly 会话 Cookie 和 CSRF 校验，密码与会话 Token 不进入 localStorage。账号模式下旧数据保留在本地空间，管理员可停服、备份后显式迁移，见 [账号初始化、隔离和迁移说明](docs/architecture/AUTH_ISOLATION.md)。

业务配额默认按用户隔离，任务/事件查询和取消不受配额限制。运维工具支持在线备份、校验和恢复到新数据库，保留业务归属并撤销历史会话。配置、命令与恢复演练见 [资源限流与数据库恢复](docs/architecture/OPERATIONS.md)。公网部署还需配置 HTTPS 和入口网关，并完成所在环境的运维验收。

## 可复现检查

完整检查需要两个可选适配依赖，使用隔离数据库，不调用真实高德或模型：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.helloagents.txt -r backend/requirements.mcp.txt -c backend/requirements.travel.lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/verify_repository.py
```

检查旅行 API、Agent、澄清、MCP、共享客户端及 Web 构建；自动启动专用缺 Key 服务，不使用正在运行的开发库。GitHub Actions 使用同一脚本。初次运行可能需要网络安装依赖，但业务 API 不使用真实凭证。

契约变更后运行并提交生成文件：

```powershell
.\.venv\Scripts\python.exe scripts/export_openapi.py
npm run schema:generate
npm run build
```

`scripts/verify_live_*.py` 为显式真实联调工具，使用者提供合法 Key 后自行运行，会产生外部调用或费用，验证产物不提交。

## 发布边界与后续优化

本次只发布整理后的源码快照，不带入原 Git 历史、机器配置、缓存、密钥、运行数据库、个人行程和未核验的旧 POI 数据。原本地工程及历史保持不变。原接口和 Flutter 源码作为历史实现保留，依赖旧 POI 的功能不承诺在此快照可运行。

后续顺序：HTTPS、备份、资源限流与部署验收 → 高德真实多日路线/编辑联调（取得授权后）→ App 接入 → 高级优化与 Memory。

- [功能范围、验收边界与后续清单](docs/RELEASE_STATUS.md)
- [来源、第三方依赖与许可边界](NOTICE.md)
- [架构审计与阶段交付](docs/architecture/TRAVEL_DELIVERY.md)
- [需求澄清实现记录](docs/architecture/DRAFT_CLARIFICATION.md)
- [原工程说明（历史）](docs/legacy/MUSE_README.md)

历史文档中的本机路径、任务 ID、截图及 artifacts 不随仓库上传，不代表克隆后已有验收产物。当前仓库为私有，尚未指定新的开源许可证；公开前需确认原始代码和第三方数据的来源与授权。
