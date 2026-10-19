# 功能范围与后续计划

更新日期：2026-10-19。本文记录可运行范围、可复现验收和后续交付条件；逐项验收步骤见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## 已实现

- Vue3、TypeScript、Vite PC 工作台；结构化表单、需求草案、执行事件、地图容器、多日时间轴、POI 详情、预算与已保存行程页面。
- 同一个 FastAPI 后端与 OpenAPI 生成的 TypeScript 类型；为后续 App 保留共享 transport。
- HelloAgents 单 Agent 需求提取；同一草案的多轮补充、字段确认、来源标记、修订冲突保护。
- 有界异步工作进程、SQLite 任务/事件/草案/行程、SSE、轮询、取消、超时和重启处理；原条件重试、提交去重与断线恢复。
- 统一真实数据 Provider/工具接口，复用既有推荐、排序、调度；缺数据明确失败，无模拟 POI/价格/交通降级。
- 可选 MCP stdio 客户端及工具服务；规划任务、POI/路线查询与已有 ToolRegistry 可复用同一客户端，具备白名单、调用预算、超时和取消验证。HelloAgents 自然语言入口仍仅整理需求。
- 可选本地账号与会话登录、Web HttpOnly Cookie/CSRF、原生客户端 Bearer 会话；任务、收据、草案、行程及其编辑版本按用户隔离。支持后台账号管理、旧本地记录的显式迁移。
- 持久化的用户/全局业务配额、用户活动任务限额、REST 工具并发和 SSE 连接控制；429 等待提示与提交恢复区分。SQLite 在线备份、完整性/归属校验、新路径恢复、会话撤销与中断任务显式重试。

## 验证边界

历史环境已验证真实模型需求提取及 Web 代理到后端的草案补充 HTTP 链路。自动验收中的成功行程使用 tests 中隔离的 FixtureProvider。2026-10-19 另以用户授权的高德 Web 服务 Key 完成直接 Provider 与 MCP 的真实 POI/路线/异步规划，以及多日调整版本、Web 保存重开与刷新复查；未使用 FixtureProvider、模拟交通或模型补事实。同日配置独立 JS API 授权后，Chromium 实测通过真实底图、编号标记、道路折线、跨天切换和刷新恢复，详细边界见 [LIVE_AMAP.md](architecture/LIVE_AMAP.md)。

当前自动检查集包含旅行 API 13 项、Agent 6 项、澄清 4 项、MCP 服务端 1 项、任务恢复 3 项、MCP 客户端 11 项、鉴权隔离 14 项、业务限流 8 项、备份恢复 6 项、共享客户端 13 项，以及 Web 类型检查/构建和 15 项浏览器场景。脚本使用独立临时库和显式 TEST ONLY 服务，不需要真实密钥。本轮遵循本地开发约定，未上传代码或触发新的 GitHub Actions；历史云端结果不代表本轮验证。

验证服务使用文件信号优雅退出，确保 Windows 下任务进程、SQLite 和日志先关闭再清理临时目录。源码清单由 `scripts/update_publish_manifest.py` 生成并由 CI 校验，排除凭证、缓存和运行记录。

旧离线 49 项评估属于原工程历史记录，依赖原始 POI 数据；这些数据没有纳入首版，因此该评估不属于本仓库可复现的 CI 检查。Flutter 未进行真机联调，apps/mobile 只是后续 uni-app 的预留说明。

## 优先级与验收标准

1. **Web 持续验收**：现已覆盖需求补全/确认/冲突/刷新、失败重试、断线恢复、取消和编辑版本。后续补充跨浏览器、键盘操作及大行程性能验收。
2. **地图与推荐质量验收**：服务端 POI/路线、多日规划、编辑重算、保存重开和浏览器地图已完成本地真实样本联调。下一步扩大真实样本，评估每日地理分组、步行负担与绕行问题，按授权配额调整调用策略；正式部署增加 JS 安全密钥代理，并复验部署域名授权与跨浏览器表现。
3. **受控工具与 MCP**：本轮已验证客户端实际连接、现有算法与 Registry 复用、调用限额、失败、取消和工具子进程退出。后续按业务需要增加受控 Agent 编排，保持同一数据和算法层。
4. **部署能力**：账号隔离、业务准入限额和备份恢复工具已实现；后续配置 HTTPS/入口网关、按真实配额调参、部署环境的定时与异地备份演练，再推进持久化队列及多实例恢复。当前支持单 API 实例的本地空间或账号空间，操作步骤见 [OPERATIONS.md](architecture/OPERATIONS.md)。
5. **移动端**：新增或适配 uni-app，复用同一 API 类型与轮询，再进行 Web + 真机同后端测试；原 Flutter 作为历史客户端保留。
6. **高级优化**：跨日全局路线优化、营业/预约时间窗、真实票价与库存，再推进复杂多 Agent 和高级 Memory。

## 首版发布排除项

原目录与历史保留在开发工作区。新仓库仅导出当前受控源码文件，并额外排除：

- `.env` 及其本地变体，保留空值 `.env.example`。
- `node_modules`、虚拟环境、构建物、缓存、日志、SQLite、用户记录和 artifacts。
- `backend/pois.json`、`backend/pois.amap.enriched.json`、`backend/pois.amap.report.json`：旧 POI 与导出来源/授权尚未核验。
- `.vscode/settings.json`、`adb.ps1`、`flutter.ps1`：机器专用配置或固定 SDK 路径。
- 原 `.git` 历史和所有嵌套仓库。

原接口与 Flutter 源码仍可阅读，但依赖旧 POI 的离线功能在此快照不承诺可运行。Web 旅行服务使用 `/api/v1/travel`；示例配置将 TRAVEL_PRODUCTION 设为 1，以关闭旧数据入口。

## 历史文档

`docs/architecture/` 记录历次实际实现和验证边界，其中 Windows 绝对路径、任务 ID、截图与 artifacts 均是本机历史记录，不是克隆后存在的文件或已发布验收材料。当前安装与限制以根 README 和本文为准。原根说明保存在 [legacy/MUSE_README.md](legacy/MUSE_README.md)。
