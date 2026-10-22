# 功能范围与后续计划

更新日期：2026-10-22。本文记录可运行范围、可复现验收和后续交付条件；逐项验收步骤见 [ACCEPTANCE.md](ACCEPTANCE.md)。

使用入口：[Web 使用手册](USER_GUIDE.md)。完整用户流程见 [WEB_USER_JOURNEY.md](architecture/WEB_USER_JOURNEY.md)，最新多日共享起终点、预算与真实联调见 [MULTIDAY_ENDPOINTS.md](architecture/MULTIDAY_ENDPOINTS.md)。

## 已实现

- 1–3 天可选每日共享的出发地/返回地，真实入站与返程纳入调度和预算缺项，复用原排序/调度；Web 支持选择/清除、草稿、地图/时间轴和版本对照。新旧提交收据兼容，已修复启动同步与手动草稿恢复竞争。默认 64 次工具预算内预留往返、裁剪候选；三天十二站双端点保留顺序编辑最多 29 次，超额重排序在 API 受理前拒绝。详情见 [MULTIDAY_ENDPOINTS.md](architecture/MULTIDAY_ENDPOINTS.md)。

- 质量验收新增杭州、北京、成都矩阵，以及每天交通占比/最长路段/剩余时段与跨日负担报告；真实直接 Provider 三任务通过完整性检查，同时保留长步行和字面未匹配线索，不冒充主观推荐评分。见 [RECOMMENDATION_QUALITY.md](architecture/RECOMMENDATION_QUALITY.md)。

- Vue3、TypeScript、Vite PC 工作台；结构化表单、需求草案、执行事件、地图容器、多日时间轴、POI 详情、预算与已保存行程页面。
- 保存列表的当前账号全库搜索、类型筛选/排序、快照分页和全部直接调整计数；来源跳转与只读版本对照保留未保存保护，未知费用不视为 0 元。65 条隔离历史和南京真实保存/搜索/对照链路通过，见 [SAVED_PAGINATION.md](architecture/SAVED_PAGINATION.md)、[SAVED_VERSIONS.md](architecture/SAVED_VERSIONS.md)。
- 键盘分页后定位到新结果；读取状态与失败摘要可访问，分页/刷新失败保留原页，重试沿用原目标，等待时继续操作不抢焦点。浏览器覆盖并发插入、换号后的迟到响应及真实离线，见 [SAVED_PAGE_RECOVERY.md](architecture/SAVED_PAGE_RECOVERY.md)。
- 多日概览并排展示各天已保存交通、停留与费用缺项，支持键盘切日；编辑仅预览站数。南京步行、苏州驾车的直接 Provider/MCP 四个真实样本通过，见 [MULTIDAY_QUALITY.md](architecture/MULTIDAY_QUALITY.md)。页面字体使用本机回退，不依赖远程字体样式加载。
- 真实质量矩阵支持预算预检、传输选择、单日/十二站、来源时间拒绝门槛、失败与验收拒绝分开计数；博物馆、咖啡与公园六个直接/MCP 任务通过，报告不把字面匹配当主观推荐评分，见 [EXPANDED_QUALITY.md](architecture/EXPANDED_QUALITY.md)。
- 同一个 FastAPI 后端与 OpenAPI 生成的 TypeScript 类型；为后续 App 保留共享 transport。
- HelloAgents 单 Agent 需求提取；同一草案的多轮补充、字段确认、来源标记、修订冲突保护。
- 有界异步工作进程、SQLite 任务/事件/草案/行程、SSE、轮询、取消、超时和重启处理；原条件重试、提交去重与断线恢复。
- 时间不可行时提供持久化的原方案分日诊断；Web 可定位时段、站数/地点和停留，编辑失败保留原版本与草稿，显式修改条件后提交新任务。南京真实 Web 失败到成功的链路已通过，见 [TIME_CONSTRAINTS.md](architecture/TIME_CONSTRAINTS.md)。
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
- 可重复校验的源码/Web 发布 ZIP、独立归档启动检查，以及复用原 WAL 快照的定时备份命令、独占锁、显式保留清理与 systemd timer 模板，见 [RELEASE_BACKUP.md](architecture/RELEASE_BACKUP.md)。
- 发布包内生产服务的本地 HTTPS 在线快照、新路径恢复和回退演练，覆盖双账号、旧会话撤销、任务事件、数据时间点与缺授权失败，58 项通过，见 [LOCAL_RECOVERY.md](architecture/LOCAL_RECOVERY.md)。
- 同源高德 JS 安全密钥代理：密钥留在后端，固定 SDK 接口、账号会话、来源/参数校验、现有配额与并发限制，以及有界响应和日志脱敏；本地与登录模式均通过真实地图验证，见 [AMAP_PROXY.md](architecture/AMAP_PROXY.md)。

## 验证边界

历史环境已验证真实模型需求提取及 Web 代理到后端的草案补充 HTTP 链路。自动验收中的成功行程使用 tests 中隔离的 FixtureProvider。2026-10-19 另以用户授权的高德 Web 服务 Key 完成直接 Provider 与 MCP 的真实 POI/路线/异步规划，以及多日调整版本、Web 保存重开与刷新复查；未使用 FixtureProvider、模拟交通或模型补事实。同日配置独立 JS API 授权后，Chromium 实测通过真实底图、编号标记、道路折线、跨天切换和刷新恢复，详细边界见 [LIVE_AMAP.md](architecture/LIVE_AMAP.md)。

当前检查集规模为 278 个逻辑用例、410 次执行：Python 178、共享客户端/展示逻辑 34、页面 66 个场景 × 3 引擎 = 198。最终完整后端/客户端/类型构建、Schema 一致性及三浏览器 198 次均通过；无跳过或自动重试。多日阶段首次失败及清理诊断单列在 [ACCEPTANCE.md](ACCEPTANCE.md) 与 [MULTIDAY_ENDPOINTS.md](architecture/MULTIDAY_ENDPOINTS.md)。无核心依赖升级，原 Flutter 保留。

2026-10-22 最新多日样本通过生产 Web 与隔离库的南京站→两日公园→南京南站链路，含共享出发时段、跨日展示、编辑清除/刷新/离线提交恢复、来源对照和两日返程超时保留原记录；独立 MCP 也通过来源和调度核验。一次运行预算上限 81，辅助 POI 有一次 429 与一次上游拒绝，选择保留且规划后端重新核验成功。详情及范围见 [MULTIDAY_ENDPOINTS.md](architecture/MULTIDAY_ENDPOINTS.md)。本轮未加载真实 SDK/模型，未重跑 HTTPS、灾备、人工读屏或真机，未上传 GitHub。

历史单日阶段：2026-10-22 用生产 API/Web 与临时库通过南京站→公园→南京南站的起终点联调，含草稿刷新、离线清除返回地保存、来源对照和返程超时保留原记录；独立 MCP 用同一契约通过来源/调度校验。完整运行上限 49，前两次未完成的运行连同本次累计上限 79；它们是预算，不是账单计数。辅助 POI 读取一次返回 429 tool_busy，选择保留，后端随后重新核验成功。首次旧诊断断言修正、启动同步竞争的确定性复现/修复、零自动重试与真实运行失败记录，均见 [SINGLE_DAY_ENDPOINTS.md](architecture/SINGLE_DAY_ENDPOINTS.md)。本轮未加载真实 JS SDK、模型，未重跑 HTTPS、灾备演练、人工读屏或真机；未上传 GitHub。

此前同日的三城路途负担观察、南京普通规划与保存对照分别保留在 [RECOMMENDATION_QUALITY.md](architecture/RECOMMENDATION_QUALITY.md)、[WEB_USER_JOURNEY.md](architecture/WEB_USER_JOURNEY.md)。历史真实 SDK、模型、29 项 HTTPS、58 项恢复/回退与更早扩展矩阵保持原日期和范围；这些样本不等于正式域名部署、未来营业/预约或推荐满意度通过。

验证服务使用文件信号优雅退出，确保 Windows 下任务进程、SQLite 和日志先关闭再清理临时目录。源码清单由 `scripts/update_publish_manifest.py` 生成并由 CI 校验，排除凭证、缓存和运行记录。

旧离线 49 项评估属于原工程历史记录，依赖原始 POI 数据；这些数据没有纳入首版，因此该评估不属于本仓库可复现的 CI 检查。Flutter 未进行真机联调，apps/mobile 只是后续 uni-app 的预留说明。

## 优先级与验收标准

1. **Web 持续验收**：现已覆盖需求补全/确认/冲突/刷新、失败重试、断线恢复、取消、地图联动、编辑差异、离开保护、编辑版本与本机草稿恢复；已验证主要键盘路径、模态焦点/Escape、跨日期错误定位及地点列表。三引擎另完成生产构建的连续读取失败恢复、取消迟到响应及最多 12 站行程读写和交互门槛验收。时间诊断、版本关系与对照、全库查询/分页、分页焦点与状态提示、跨页离线/刷新失败和并发插入均已实现；65 条历史及双账号通过，既有真实高德 Web 链路记录保持。完整操作手册与连续流程验收已补齐，南京真实失败修正、草稿和离线保存链路通过。已补每日共享起终点与启动同步恢复，后续补 NVDA/VoiceOver 人工朗读，按真实使用反馈完善推荐质量。目标环境具备后核验正式 HTTPS、域名授权和配额，Safari 真机、随机丢包及长时间压力按实际条件补验。
2. **地图与推荐质量验收**：真实地图、双向定位、编辑预览及原分日与有限地理候选比较已完成；上海样例交通减少 12 分钟，杭州样例保持基线以避免最忙一天恶化。JS 安全密钥代理已实现并通过本地/账号实测；南京步行、苏州驾车的直接 Provider/MCP 四项样本已增加来源、缺失字段和调度验收。已补三类关键词和三/四/十二站的六个真实任务，报告明确任务成功、字段缺失、字面复核、原分日收益与调用上限。新增杭州/北京/成都三场景，报告真实路途负担与待核对证据。单日起终点已实现并通过真实 Web/MCP 核验，见 [SINGLE_DAY_ENDPOINTS.md](architecture/SINGLE_DAY_ENDPOINTS.md)；每日共享起终点和默认 64 次总预算内的候选裁剪已实现，南京两日真实 Web/MCP 通过，见 [MULTIDAY_ENDPOINTS.md](architecture/MULTIDAY_ENDPOINTS.md)；后续增加明确的路途负担提示、步行偏好及逐日不同住宿点；主观推荐评估需真实用户反馈及事先定义的标准，正式域名验收另行推进。
3. **受控工具与 MCP**：既有验收已验证客户端实际连接、现有算法与 Registry 复用、调用限额、失败、取消和工具子进程退出。后续按业务需要增加受控 Agent 编排，保持同一数据和算法层。
4. **部署能力**：账号隔离、业务准入限额、备份恢复、HTTPS 网关/服务模板、发布打包与定时备份保留命令已实现。本地 HTTPS、归档启动和备份恢复演练通过；目标主机具备后核验 DNS/ACME、真实域名授权、权限、重启与 timer 触发，按真实配额调参并安排异地备份，再推进持久化队列及多实例恢复。当前支持单 API 实例，模板见 [DEPLOYMENT.md](architecture/DEPLOYMENT.md)，备份步骤见 [OPERATIONS.md](architecture/OPERATIONS.md)。
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
