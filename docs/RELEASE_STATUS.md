# 功能范围与后续计划

更新日期：2026-10-20。本文记录可运行范围、可复现验收和后续交付条件；逐项验收步骤见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## 已实现

- Vue3、TypeScript、Vite PC 工作台；结构化表单、需求草案、执行事件、地图容器、多日时间轴、POI 详情、预算与已保存行程页面。
- 同一个 FastAPI 后端与 OpenAPI 生成的 TypeScript 类型；为后续 App 保留共享 transport。
- HelloAgents 单 Agent 需求提取；同一草案的多轮补充、字段确认、来源标记、修订冲突保护。
- 有界异步工作进程、SQLite 任务/事件/草案/行程、SSE、轮询、取消、超时和重启处理；原条件重试、提交去重与断线恢复。
- 统一真实数据 Provider/工具接口，复用既有推荐、排序、调度；缺数据明确失败，无模拟 POI/价格/交通降级。
- 可选 MCP stdio 客户端及工具服务；规划任务、POI/路线查询与已有 ToolRegistry 可复用同一客户端，具备白名单、调用预算、超时和取消验证。HelloAgents 自然语言入口仍仅整理需求。
- 可选本地账号与会话登录、Web HttpOnly Cookie/CSRF、原生客户端 Bearer 会话；任务、收据、草案、行程及其编辑版本按用户隔离。支持后台账号管理、旧本地记录的显式迁移。
- 持久化的用户/全局业务配额、用户活动任务限额、REST 工具并发和 SSE 连接控制；429 等待提示与提交恢复区分。SQLite 在线备份、完整性/归属校验、新路径恢复、会话撤销与中断任务显式重试。
- 复用原有推荐/排序/调度的有界跨日地理候选，真实交通核验后决定是否采用；Web 展示分日与交通对比，手动编辑不自动跨日移动。上海、杭州已完成直接 Provider/MCP 样例比较，详见 [DAY_GROUPING.md](architecture/DAY_GROUPING.md)。
- 地图编号与时间轴双向选择、相邻道路高亮、可访问地点列表；编辑前后差异、未保存保护与地点预览，保存时沿用后端异步重算并保留原版本。操作与验收见 [WEB_EDITING.md](architecture/WEB_EDITING.md)。
- 按账号隔离的本机行程编辑草稿：保留 7 天、刷新/关闭后显式恢复、原版本核对与新增地点重查、提交回执优先恢复、跨页面冲突保护及存储失败提示，见 [EDIT_DRAFT_RECOVERY.md](architecture/EDIT_DRAFT_RECOVERY.md)。
- 键盘导航、跨日期编辑错误定位、中文错误摘要与字段描述关联、详情/放弃对话框的循环焦点及 Escape，见 [KEYBOARD_ACCESSIBILITY.md](architecture/KEYBOARD_ACCESSIBILITY.md)。
- 完成结果读取失败时保留旧行程与编辑内容，单列待同步状态，恢复同一任务并阻止重复保存；生产构建覆盖连续断线、迟到响应和 12 站行程的编辑/保存/刷新及交互门槛，见 [RESILIENCE_PERFORMANCE.md](architecture/RESILIENCE_PERFORMANCE.md)。
- Caddy HTTPS 同源入口、单 API systemd 模板、配置预检、独立健康检查和只读上线检查；本地临时 CA 与生产构建完成 29 项 HTTPS 联调，见 [DEPLOYMENT.md](architecture/DEPLOYMENT.md)。
- 同源高德 JS 安全密钥代理：密钥留在后端，固定 SDK 接口、账号会话、来源/参数校验、现有配额与并发限制，以及有界响应和日志脱敏；本地与登录模式均通过真实地图验证，见 [AMAP_PROXY.md](architecture/AMAP_PROXY.md)。

## 验证边界

历史环境已验证真实模型需求提取及 Web 代理到后端的草案补充 HTTP 链路。自动验收中的成功行程使用 tests 中隔离的 FixtureProvider。2026-10-19 另以用户授权的高德 Web 服务 Key 完成直接 Provider 与 MCP 的真实 POI/路线/异步规划，以及多日调整版本、Web 保存重开与刷新复查；未使用 FixtureProvider、模拟交通或模型补事实。同日配置独立 JS API 授权后，Chromium 实测通过真实底图、编号标记、道路折线、跨天切换和刷新恢复，详细边界见 [LIVE_AMAP.md](architecture/LIVE_AMAP.md)。

当前自动检查集规模为 166 个逻辑用例，共 250 次执行：Python 101 项、共享客户端 23 项、页面 42 个场景在 Chromium/Firefox/WebKit 各执行一次（126 次）。本次部署阶段重跑 Python/客户端/构建及契约，定向复查 Chromium 账号 10 项；三引擎完整页面矩阵沿用同日弱网阶段记录。另有 29 项本地 HTTPS 联调，单独计数。真实地图检查单列于 [跨浏览器验收](architecture/BROWSER_ACCEPTANCE.md)。本机草稿、键盘、弱网性能及部署阶段未新增真实高德调用；性能结果不包含 SDK 瓦片加载。无密钥脚本使用独立临时库和显式 TEST ONLY 服务。本轮未上传代码或触发新的 GitHub Actions；Linux systemd、公网证书、正式域名和真机不属于此次验证。

验证服务使用文件信号优雅退出，确保 Windows 下任务进程、SQLite 和日志先关闭再清理临时目录。源码清单由 `scripts/update_publish_manifest.py` 生成并由 CI 校验，排除凭证、缓存和运行记录。

旧离线 49 项评估属于原工程历史记录，依赖原始 POI 数据；这些数据没有纳入首版，因此该评估不属于本仓库可复现的 CI 检查。Flutter 未进行真机联调，apps/mobile 只是后续 uni-app 的预留说明。

## 优先级与验收标准

1. **Web 持续验收**：现已覆盖需求补全/确认/冲突/刷新、失败重试、断线恢复、取消、地图联动、编辑差异、离开保护、编辑版本与本机草稿恢复；已验证主要键盘路径、模态焦点/Escape、跨日期错误定位及地点列表。三引擎另完成生产构建的连续读取失败恢复、取消迟到响应及最多 12 站行程读写和交互门槛验收。下一阶段优先正式环境的 HTTPS、域名授权、配额和备份恢复检查，再补 NVDA/VoiceOver 人工朗读与 Safari 真机；随机丢包及长时间压力按实际部署补验。
2. **地图与推荐质量验收**：真实地图、双向定位、编辑预览及原分日与有限地理候选比较已完成；上海样例交通减少 12 分钟，杭州样例保持基线以避免最忙一天恶化。JS 安全密钥代理已实现并通过本地/账号实测；下一步核验正式部署的 HTTPS 与域名授权，再扩大城市、交通模式和出发/返回位置样本，继续评估收益与调用成本。
3. **受控工具与 MCP**：本轮已验证客户端实际连接、现有算法与 Registry 复用、调用限额、失败、取消和工具子进程退出。后续按业务需要增加受控 Agent 编排，保持同一数据和算法层。
4. **部署能力**：账号隔离、业务准入限额、备份恢复、HTTPS 网关/服务模板与上线检查已实现。本地 HTTPS 联调通过；下一步在目标主机核验 DNS/ACME、真实域名授权、权限、重启和恢复，按真实配额调参并安排定时/异地备份，再推进持久化队列及多实例恢复。当前支持单 API 实例，模板见 [DEPLOYMENT.md](architecture/DEPLOYMENT.md)，备份步骤见 [OPERATIONS.md](architecture/OPERATIONS.md)。
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
