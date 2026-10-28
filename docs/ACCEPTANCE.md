# Web 验收记录

验收环境：2026-10-19 至 2026-10-29，Python 3.12、Node.js、Windows、Chromium / Firefox / WebKit Headless。本轮仅在本地运行，未上传至 GitHub 或运行云端检查；仓库保留可在 Ubuntu / Node.js 22 上执行的 CI 配置。

## 相对日期显式确认

原文相对日期候选须选用并保存才写入草案，来源为用户填写；跨年、闰日、日期上界、清空、旧记录和刷新恢复纳入检查。真实两次模型调用均未完成整项语义验收，第二次仅日期遗漏，失败不以离线测试覆盖。最终检查与调用范围见 [日期确认记录](architecture/INTAKE_REVIEW_MATRIX.md#相对日期诊断与显式确认)，该组浏览器为三引擎定向检查，旧完整归档基线仍单独保留。

## 需求理解与连续使用矩阵

接续固定两次真实调用：歧义场景通过，相对日期被原文依据校验拒绝，没有保存错误草案，整体仍为失败。随后以失败回归验证并修正过期准入放行、浏览器清理证据接受问题，细化安全依据字段诊断；细节与最终自动检查见 [接续记录](architecture/INTAKE_REVIEW_MATRIX.md#接续两次真实复验与运行边界修正)。新发布矩阵要求显式清理成功，旧报告缺少该字段时须重新验收。

2026-10-28 固定相对日期、歧义条件和明确改口三类输入，真实调用三次：改口通过，相对日期遗漏且逐日时段误合并，歧义调用失败，整体保留失败。修正后未追加真实调用。最终源码的 Python 326、客户端 95、三引擎 local 各 60 项合计 601 次检查通过，类型/构建和 Schema 一致性通过，服务正常退出；这不是九份完整发布矩阵。

首个浏览器预检在退出清理阶段失败，首组完整仓库在并行负载下的既有进程间隔测试失败；分别保留记录，单独原样复查及完整仓库重跑通过，不宣称间歇问题已根治。固定输入、脚本入口、报告和真实复验缺口见 [需求理解与连续使用验收](architecture/INTAKE_REVIEW_MATRIX.md)。未重跑真实地图、HTTPS/恢复或新归档。

## 原文依据格式复验

基于安全诊断定位 evidence 类型问题后，补充同一工具的格式说明，同一局部逐日真实输入一次复验通过；合计两次模型调用，失败与通过分别保留，未知值和用户明确清空均核验。修正后 Python 316、客户端 95、类型/构建及 Schema 一致性通过，三引擎定向 3 次通过。单样本不代表全表达准确率，未重跑完整矩阵/HTTPS/恢复或新归档，详细证据见 [需求校验诊断](architecture/INTAKE_DIAGNOSTICS.md)。

## 需求校验诊断阶段

本轮新增安全字段诊断与中文恢复提示，Agent 专项 12 项、三引擎各 1 项定向流程通过，类型/构建通过。完整仓库结果与范围见 [需求校验诊断](architecture/INTAKE_DIAGNOSTICS.md)。未重跑完整浏览器矩阵、真实模型/地图、HTTPS、灾备或新归档。以下表格及完整候选结论保留为 `bea0f6c` 归档基线，不能作为新源码的完整通过记录。

## 可复现检查

先按根 README 安装 Python、Node 与可选 Agent/MCP 锁定依赖，再执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_repository.py --run-id local-acceptance
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.cache/playwright"
npx playwright install --only-shell chromium firefox webkit
.\.venv\Scripts\python.exe scripts/verify_browser.py --run-id local-acceptance
.\.venv\Scripts\python.exe scripts/summarize_browser_runs.py --run-id local-acceptance
.\.venv\Scripts\python.exe scripts/update_publish_manifest.py --check
```

Linux 浏览器首次安装使用 `npx playwright install --with-deps --only-shell chromium firefox webkit`，并设置 `export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/playwright"`。单独执行 `npm run test:browser` 需要专用服务地址；推荐使用上述 Python 编排脚本，按引擎和账号模式隔离数据库，自动启动并关闭 API 和 Vite。

| 检查 | 数量 | 覆盖范围 |
| --- | ---: | --- |
| Python | 310 | 旅行 API 15、Agent 8、澄清 9、真实提取核验脚本的离线回归 9、MCP 服务端 1、任务恢复 3、MCP 客户端 18、鉴权隔离 15、业务限流 8、备份恢复 6、分日算法 13、地图代理 16、健康 4、部署配置 6、定时备份 8、发布包 8、恢复种子保护及完整DTO 5、真实质量报告/预算预检 23、时间不可行诊断 7、保存列表分页/查询 9、单日/多日共享起终点 20、交通上限 12、共享高德节流 8、逐日独立起终点 12、逐日时段/停留 10、备选地点/真实收益/兼容 19、浏览器运行与报告隔离 5、演练生命周期 8、源码/构建绑定 14、候选证据拒绝 9、严格通过统计 2 |
| TypeScript 客户端与展示逻辑 | 95 | HTTP 契约、轮询期限/取消、暂时断线、提交收据恢复、编辑差异与还原、工具握手、账号绑定与恢复、配额拒绝、本机草稿校验/冲突/存储失败、版本筛选/关系/缺省与只读差异、分页参数编码与元数据/错误、起终点汇总/缺项、版本/草稿兼容、请求与取消信号、交通上限的严格输入/清除和旧草稿兼容、逐日事实/差异/数组校验与恢复、时段与默认停留优先级/不完整输入/模式切换/差异、备选变化/最长段定位/评分缺失/开关恢复/共享 transport、草案逐日转换/确认/清除/未知保留 8、起终点交接确认/日期地点失效/恢复 3、服务快照与迟到响应 5、地图加载/首绘/重试/卸载 8、需求输入稀疏保存/来源/多页冲突/部分确认保留 18、北京时间及冻结请求 2 |
| Chromium / Firefox / WebKit | 300 次 | 每引擎旅行工作台及完整需求流程/服务状态/需求输入保护 58 项、账号流程 16 项、生产构建弱网/最大行程/连续流程/共享起终点/启动恢复/交通上限/限流恢复/逐日选择/时段停留/模式切换/备选比较/评分取舍与原方案恢复/带基线十二站 26 项，三个引擎合计 300 次执行 |
| Web / Schema | — | TypeScript 检查、Vite 构建、OpenAPI 生成文件一致性 |

归档 `bea0f6c` 的完整验收规模为 **505 个逻辑用例、705 次执行**。需求输入保护与归档排序最终组 `requirements-portable-20261024` 已通过 Python 310、客户端 95、类型/无密钥生产构建和 OpenAPI/TS 生成一致性；三引擎各 100 项、九份完整报告合计 300 次全部通过，零最终失败/跳过/自动重试。报告绑定当前源码和实际 Web 字节，服务正常退出通过；范围及首轮失败记录见 [需求输入保护](architecture/REQUIREMENTS_INPUT_RECOVERY.md)。同组本地 HTTPS 29 项通过；归档启动、备份恢复和同一 ZIP 的候选门禁结果单列于 `artifacts/releases/`、`artifacts/drill-runs/requirements-portable-20261024/recovery/` 与 `artifacts/candidate-runs/requirements-portable-20261024/report.json`，不混入 705 次。此前功能组 `requirements-final-20261024` 的 704 次检查通过，但归档因 Windows 文件排序差异被拒，未执行该组归档启动/恢复/候选门禁；修正后完整重跑，没有复用旧组作为新源码证据。

真实模型使用独立空库固定调用两次：`complete15` 通过，`partial-daily` 以 `invalid_agent_output` 失败，整体真实模型检查按失败保留；没有追加重试或模拟补齐，合计一份草案、零行程，无高德/SDK 调用。日志缺少具体校验路径，不能判断是哪一个字段导致失败，后续诊断与复验计划见上述需求输入保护说明。自动回归通过不代表该真实失败已解决。

服务状态与恢复历史组 `web-services-accepted-20261023` 为 Python 300、客户端 75、三引擎各 92 项，合计 467 个逻辑用例、651 次执行。该组还从 GBK 父环境验证了 UTF-8 输出转发修复，范围见 [服务状态与恢复](architecture/WEB_SERVICE_RECOVERY.md)。

C 包历史规模为 443 个逻辑用例、615 次执行，证据组为 `c-release-final-20261023`：`artifacts/repository-runs/<id>/report.json`、九份 `artifacts/browser-runs/<id>/<engine>/<suite>/`、`artifacts/drill-runs/<id>/deployment` 与 `recovery`，以及同一干净 ZIP 的 `runtime.json`。`artifacts/candidate-runs/<id>/report.json` 统一复核源码、构建、完整套件和归档 SHA。HTTPS 29 项、完整 A/B 记录恢复/回退 97 项和归档启动 4 项另列检查数，不混入 615。具体命令、绑定和本地边界见 [发布候选综合验收](architecture/LOCAL_RELEASE_CANDIDATE.md)。

预备组 `c-release-verified-20261023` 在执行期间增加严格 skip/todo 统计校验，起止源码指纹因此不同，被最终规则拒绝；保留原日志/failed元数据，不计为当前通过。修正后使用全新组完整复验，没有覆盖旧记录。历史 13 个缺失文档引用已修正或改为明确历史文件名记录；不补造缺失截图。

B 包当时为 Python 259、客户端 62、三浏览器 258 次，共 407 个逻辑用例 / 579 次执行。四条需求/选点/恢复/来源对照流程保留，详见 [需求确认与 Web 连续使用](architecture/REQUIREMENTS_WORKFLOW.md)。

B 包证据：`artifacts/b-workflow-repository.log`、`artifacts/b-workflow-schema.json`、`artifacts/b-workflow-<engine>-verified.log`，不可覆盖的 `artifacts/browser-runs/b-workflow-verified-20261022/<engine>/<suite>/` 及同组 `summary.json`，总表 `artifacts/b-workflow-acceptance.json`。定向组 `b-workflow-targeted-20261022-01/-02/-03` 单独保留，不能当作完整矩阵。PC 行程区域与 390 像素窄屏截图在当前 local/results 中，均明确为 TEST ONLY 数据。

B 包当轮外部数据/模型调用为 0，没有重跑真实模型新字段准确率、Amap/JS SDK、HTTPS、灾备或手机。补充草案实际调用同一 PATCH/存储链路，规划和调整实际调用隔离服务/SQLite及测试 Provider；生产入口不会载入这些测试数据。A 包真实多城/direct/MCP 结果按原日期和范围保留，不计入 B 包通过结果。

B 包三日十二站切日 p95：未带基线 Chromium 110.4 / Firefox 149 / WebKit 290 ms，带基线 154 / 131 / 256 ms，均低于原 1500 ms 门槛。带基线 JSON 453074 字节；DOM、单次响应和草稿大小的原门槛保持，属于本机 TEST ONLY、无真实 SDK 条件。

A 包实际证据：`artifacts/poi-comparison-verified-repository.log`、`artifacts/poi-comparison-schema.json`、`artifacts/poi-comparison-<engine>-verified.log` 和不可覆盖的 `artifacts/browser-runs/poi-comparison-verified-20261022/<engine>/<suite>/`，汇总为同组 `summary.json` 与 `artifacts/poi-comparison-acceptance.json`。执行前发现用例，执行后核对完整 ID 集、每例一次、无跳过/重试及服务优雅退出；此前定向或较早矩阵不会混作最终完整报告。复跑须选择新 run ID。

A 包带基线比较的十二站/三日样本 JSON 为 453074 字节，切日交互 p95 为 Chromium 128.7 ms、Firefox 133 ms、WebKit 250 ms，均低于原 1500 ms 门槛；编辑草稿不含基线事实/折线、低于 32 KiB，保存/刷新及原版本保留通过。这是本机 TEST ONLY、无真实地图 SDK 的条件，三引擎并发、各自单 worker，不是公网指标。

A 包最终三城真实直接 Provider：南京交通 73→37 分钟，杭州 279→224 分钟；苏州候选不改善而保留 30 分钟。南京实际 MCP 也核验 36 分钟收益；各自收益从同任务基线与采用结果计算。含车站 Web 样本来源、逐日调度、编辑/刷新/保存/来源对照通过，但无路途收益，仍如实保留基线。首轮零收益、诊断和最终复验都保留，累计网关调用上界 129，低于整包 141，不是账单计数。详细范围、评分取舍与未知项见 [POI_COMPARISON.md](architecture/POI_COMPARISON.md)。真实 SDK/模型、HTTPS、灾备、人工读屏、真机本轮未重跑；没有上传 GitHub。

此前逐日模式授权样本：南京两日、每天一站、步行，分别交换南京站/南京南站的起终点。原规划、单日清除、刷新恢复、编辑保存、来源对照及真实 MCP 均通过；页面 8 次 POI 读取成功。预留调用上界 35，按已选 ID 的结构性上界 29，无自动付费重试或模拟结果。费用/营业字段仍保留缺失，地图 SDK/模型/HTTPS/灾备/人工读屏/手机本轮未重跑。证据见 [DAILY_ENDPOINTS.md](architecture/DAILY_ENDPOINTS.md)。

共享节流阶段历史真实 Web/MCP 复验通过：原规划、返程超限失败、刷新恢复、清除上限后保存及来源保留；页面 POI 读取 4 次均成功。首次真实脚本文本断言停止与后续手动复验分别保留，两次调用预算累计上界 58，未自动重放。完整结果、数据缺项和未重跑范围见 [AMAP_REQUEST_PACING.md](architecture/AMAP_REQUEST_PACING.md)。

交通上限阶段历史修复：新增测试首次误引用不存在的等待函数，已改为有期限任务轮询；浏览器测试定位百分比浮点显示误差，改用标准百分比格式化后按原断言通过。无密钥测试时限及零自动重试设置保持不变。

交通上限阶段的历史真实验收有两次尝试，累计预算上界 71，低于预定 84，不是账单计数。第一次验证脚本在任务仍运行时触发 30 秒观察门槛，没有终态；第二次单日原规划、负担展示、返程超限诊断及刷新恢复草稿通过，但清除后保存被高德 10021 拒绝，整体失败，真实 MCP 后续阶段未执行。证据及中间响应未完整保留的限制见 [TRAVEL_LOAD_LIMITS.md](architecture/TRAVEL_LOAD_LIMITS.md)。该阶段没有额外付费重试，没有模拟结果；真实 SDK、模型、HTTPS、灾备、人工读屏、真机未重跑。历史 [多日起终点](architecture/MULTIDAY_ENDPOINTS.md) 的完整真实 Web/MCP 通过范围保持原记录，不挪作本轮通过。

2026-10-22 推荐质量观察阶段增加 6 项离线检查，实际运行质量报告全部 18 项、无凭证预检，以及杭州/北京/成都三个授权真实任务，通过来源、契约和调度检查。最长路段、交通占比和跨日负担来自已保存事实，保留交通偏长及字面未匹配线索；不代表满意度评分。生产 API/Web/Schema 未改，其他检查未在此阶段重跑；范围和查询上限 51 见 [RECOMMENDATION_QUALITY.md](architecture/RECOMMENDATION_QUALITY.md)。

此前同日使用手册阶段的检查集为 238 个逻辑用例、362 次执行（包含相同页面场景在不同引擎中的重复）。2026-10-22 新增连续用户流程，实际重跑三引擎生产套件 18 次全部通过；类型/构建和 Schema 一致性通过。其余 Python、客户端、工作台与账号用例沿用前一日未变业务代码的通过记录，未称为本轮全跑。新增场景首次因预算标签完全匹配错误超时，定位后修正测试再通过；超时与零自动重试设置未变，详见 [WEB_USER_JOURNEY.md](architecture/WEB_USER_JOURNEY.md)。同日另以授权高德、生产 API/Web 和临时库通过时间失败修正、草稿刷新、离线提交恢复及新旧版本对照，查询上限 10；未加载真实 SDK/模型/MCP，单列真实样本，不计入无凭证自动用例。

以下保留 2026-10-21 分页交互恢复基线：分页交互恢复阶段重跑 Python 146、共享客户端/展示逻辑 30、类型/生产构建及三引擎 183 个引擎场景；重新生成的 OpenAPI 与 TypeScript 契约无差异。首次全跑在 WebKit 账号第 12 项的 beforeEach 期间遇系统休眠约 63 分钟，触发 30 秒准备超时；电源事件核对为上海时间 17:01–18:04。唤醒后保持代码与测试时限不变，重新运行 WebKit 账号 13 项及尚未执行的生产构建 5 项，最终各套件通过，无失败或跳过，配置始终为 `retries=0`。当时 359 是完整检查集的执行规模，不重复计入定向复查和休眠后复跑。焦点、原页保留、并发插入、换号迟到响应及首个定向失败记录见 [SAVED_PAGE_RECOVERY.md](architecture/SAVED_PAGE_RECOVERY.md)。该分页恢复阶段未调用高德或模型接口，`224a597` 的南京真实规划→调整→搜索→对照记录保留在 [SAVED_PAGINATION.md](architecture/SAVED_PAGINATION.md)，不冒充本轮重测。历史扩展质量矩阵、时间约束、字体阻塞及 Windows WebKit 的 SameSite 元数据边界分别保留在 [EXPANDED_QUALITY.md](architecture/EXPANDED_QUALITY.md)、[TIME_CONSTRAINTS.md](architecture/TIME_CONSTRAINTS.md)、[MULTIDAY_QUALITY.md](architecture/MULTIDAY_QUALITY.md) 和 [BROWSER_ACCEPTANCE.md](architecture/BROWSER_ACCEPTANCE.md)，本轮未重跑真实 SDK、HTTPS、恢复演练或人工辅助技术听读。

扩展矩阵阶段的博物馆 3 站、咖啡 4 站、公园 12 站各走直接 Provider/MCP，共六任务全部通过来源/调度检查；调用上限 138，单日保留上限与实测的区别，十二站任务各返回 48 条矩阵路段计数。详细结果、人工复核范围与非主观评分的判定见 [EXPANDED_QUALITY.md](architecture/EXPANDED_QUALITY.md)，不计入无密钥检查集。

多日概览阶段另通过四项真实高德多日质量样本，实际 4 次搜索、16 次路线查询，直接 Provider/MCP 均通过，单列于 [MULTIDAY_QUALITY.md](architecture/MULTIDAY_QUALITY.md)，不计入无密钥检查集。

时间约束阶段另以独立临时库、生产 API/Web 构建和真实高德验证南京 1 日 2 站的失败到重新规划：原时段仅 1 分钟、需 81 分钟，显式扩大至 18:00 后新任务成功，旧失败记录保留；实际 2 次搜索、4 次路线查询，未加载 JS SDK。该真实链路单列于 [TIME_CONSTRAINTS.md](architecture/TIME_CONSTRAINTS.md)，不计入无密钥检查集。

本地恢复/回退脚本以包内生产应用启动实际 HTTPS 服务，验证在线快照、新路径恢复、原会话撤销、数据时间点、双账号隔离、任务事件、原库/快照不变和缺授权时明确失败。全部测试业务记录离线构造，API 不替换 Provider；58 项单独计数，详见 [LOCAL_RECOVERY.md](architecture/LOCAL_RECOVERY.md)。

发布包增加逐文件清单校验、相同输入重复打包哈希一致、私密配置/数据排除与归档源码独立启动；后者另计 4 项。备份轮换在测试库演练显式保留、损坏/手工文件保护、失败与独占锁、时钟回拨以及不覆盖恢复。首轮回归中电脑休眠约 85 分钟使 MCP 超时用例失效，唤醒后按原限制复查并重跑完整检查；没有放宽超时或跳过。步骤与范围见 [RELEASE_BACKUP.md](architecture/RELEASE_BACKUP.md)。

部署阶段另使用真实 Caddy 2.11.7、本地 CA、独立数据库和生产构建通过 29 项 HTTPS 检查，TLS 验证始终开启，没有安装系统信任或系统服务；这 29 项单独计数。包括同源登录 Cookie、CSRF、异步任务去重、SSE 及时交付与终态、结果读取、退出和请求大小拒绝。源码入口、复现及 Linux/公网边界见 [DEPLOYMENT.md](architecture/DEPLOYMENT.md)。

本轮新增逐日时段/默认停留、逐站覆盖、跨日候选按目标日期重核验、单日超时诊断、旧数据/草稿/收据兼容、编辑省略/清除与来源不变。浏览器新增天数增减/刷新/切回共用、失败定位/显式修正、按日应用/不完整草稿/断网保存/来源对照，以及未完成共用输入的切换保护。真实南京 Web 原版/调整版和同契约 MCP 三任务通过，预留 36 次外部调用上限，8 次页面 POI 读取成功，详细调度时间与负担边界见 [DAILY_SCHEDULES.md](architecture/DAILY_SCHEDULES.md)。

本轮保留了切换边界的首次失败复现，以及同引擎测试目录重叠造成的 trace 收尾冲突。原进程退出后重跑完整生产构建套件，零自动重试，原超时及性能门槛不变。三个不同引擎可并发，但同一引擎/套件不重叠。后端日志 `artifacts/daily-schedules-repository.log`（Python 227；修复前 TS 45），最终全部客户端/构建 `artifacts/daily-schedules-client-final.log`（TS 46），Schema `artifacts/daily-schedules-schema.json`，浏览器基础/账号日志 `artifacts/daily-schedules-<engine>.log`，最终生产构建套件 `artifacts/daily-schedules-<engine>-resilience-final.log`。九份最终报告在 `artifacts/browser-reports/<engine>/<suite>.json`；运行记录被 Git 排除。本轮没有重跑真实 SDK/模型、HTTPS、灾备、人工读屏或手机。

浏览器场景：

1. 自然语言缺字段草案 → 用户补全与确认 → 来源和未处理需求保留 → 应用表单 → 更新草案时提示表单版本 → 刷新恢复。
2. 后端已受理但 POST 响应丢失 → 恢复同一提交 → 使用原任务 ID，无重复 POST。
3. 另一页面已更新草案 → 保存返回版本冲突 → 未保存答案保留 → 用户显式加载最新草案。
4. 暂时调用失败 → 修改当前表单 → 按原条件重试仍使用服务端原请求，新任务关联原任务，原失败记录保留。
5. SSE 不可用且短暂网络失败 → 有界退避轮询恢复 → 刷新后继续显示同一任务与行程。
6. 取消进行中的任务 → 状态终结 → 提供显式原条件重试。
7. 打开已保存多日行程 → 录入站点费用 → 编辑重算创建新版本 → 原行程可读，缺失费用仍为未知。
8. 预算页面主动检查数据工具 → 后端完成真实 MCP 握手 → 界面单列地图授权未配置，不将连接通过当作业务成功。
9. 业务限额拒绝 → 展示等待秒数 → 清理未确认提交并保留表单 → 刷新不会重放请求 → 用户可再次提交；此页面场景使用显式 429 故障注入，真实配额拒绝由后端 HTTP 测试覆盖。
10. 多日规划 → 展示原分日与采用方案的真实交通对比 → 刷新保留 → 手动编辑重算仍保持用户选定分日，原版本不变。新提交清除上一任务的完成提示，验收等待新的任务 ID 及终态。
11. 时间轴编号与地图地点列表双向选择 → 高亮、滚动和键盘焦点 → 切换日期清除选择；不额外查询 POI 详情。
12. 修改费用为 0、停留和分日 → 差异对照与地图地点预览 → 切换页面及取消浏览器刷新保留修改 → Escape 继续编辑 → 确认放弃恢复已保存路线。
13. 打开行程/提交新规划前提示未保存 → 取消后不发送规划 POST → 保存拒绝保留编辑 → 再次保存成功创建新版本并清除未保存提示。
14. POST 与状态响应延迟 → 保持禁用与同一任务，重复触发表单不重复提交。
15. 任务执行中真实离线 → 状态请求失败 → 联网后继续同一任务，没有第二次创建 POST。
16. 离线编辑提交失败 → 保留原内容和标识 → 联网仅查收据并清除过期断网提示 → 用户显式恢复后创建新版本。
17. 修改分日/停留/费用 0 与空白输入 → 接受刷新 → 显式恢复草稿 → 保存创建新版本并清理本机草稿。
18. 原行程版本变化或 404 → 拒绝恢复且保留草稿 → 重试成功或显式放弃。
19. 新增地点不缓存事实 → 恢复时重查详情 → 详情失败保留全部草稿，重试后恢复，不静默移除地点。
20. 两标签页同时打开编辑 → 旧页面写入/删除/提交被冲突保护阻止，不覆盖较新草稿。
21. 编辑已受理但响应丢失 → 刷新先恢复回执与任务 → 完成后清理对应草稿，只有一次调整 POST。
22. 本机配额不足或禁止读取 → 明确提示草稿不可用，仍可编辑并直接保存到后端。

23. 键盘跳过导航并切换页面 → 焦点到新标题 → 当前页面状态及窄屏名称可读取。
24. 规划/搜索错误摘要与字段关联 → 纠正空格、时段与数值 → 无效请求不发出，费用与预算保留小数。
25. 其他日期停留为空或约束折叠 → 摘要切换日期、展开并定位 → 修正或移除后更新错误，不丢编辑草稿。
26. 键盘排序、跨日移动、移除 → 焦点保持可用 → 不误提交；放弃确认的 Tab/Shift+Tab/Escape 可用。
27. 地点详情焦点循环、Escape 关闭与返回原按钮 → 编辑中可添加地点后继续原页面。
28. 多日概览逐日核对 API 站数、停留、交通和缺失费用 → 方向键/Home 切日、焦点与时间轴同步 → 窄屏无横向溢出。
29. 跨日移动同步概览站数 → 编辑时隐藏旧交通/费用 → 保存后显示新事实 → 原版本保持，0 元与未填区分。
30. 工作台刷新及第二个标签页均完成加载 → 不请求外部字体或样式，避免第三方字体阻塞。
31. 时间不可行任务展示原方案分日分钟 → 定位输入不自动改值或提交 → 刷新后诊断不跟随当前表单变化 → 手动修改后显式新任务成功。
32. 第二天编辑超时 → 原行程和 0 元/停留草稿保留 → 刷新恢复、切日及展开定位 → 显式保存新版本，原版本不变。
33. 通过测试 API 生成父/子/孙版本 → 完整 ID 与类型筛选 → 直接关系不含孙版本 → 时间排序、无结果与窄屏无横向溢出。
34. 已保存来源对照 → 未知/0 元、停留与完整预算分别显示 → 不发送 POST 或清理草稿 → 打开来源仍受未保存保护，原记录不变。
35. 来源不在已载入列表时重新读取 → 来源 404 时清除旧表格 → 显式重试成功；不推断或拼接假版本。
36. 读取过程中关闭对照 → 按钮重新启用后恢复焦点 → 迟到来源响应不重新打开或覆盖当前页面。
37. 全库搜索 65 条历史 → 50/15 双页与回退 → 每条只出现一次、排序与 API 一致，窄屏无横向溢出。
38. 查找默认首屏之外的原版 → 后端计数包含跨页直接子版本 → 直接条件不含孙版 → 对照与打开来源正常。
39. 先后搜索的迟到响应不覆盖新结果 → 列表失败显式重试 → 不发送任务 POST，原编辑输入保持。
40. Enter 翻页/回退后定位新结果标题，Tab 到首卡 → 状态/忙碌属性与窄屏布局通过 → 等待中转到搜索框后不抢焦点。
41. 实际断网导致下一页读取失败 → 原 50 个 ID、页码与游标保留，聚焦失败摘要 → 同游标重试成功；第二页刷新 503 仍保留原 15 个 ID，费用草稿不变，无业务 POST。
42. 延迟第二页响应期间改变筛选 → 新查询第一页与输入焦点保持 → 旧响应不回填旧数据、页码或错误。
43. 实际向测试服务提交一个匹配的新行程 → 旧快照前后页 ID 和总数不变 → 显式刷新后第一页才纳入新版本。

独立生产构建套件再验证 5 项：间歇状态/事件读取失败后恢复、连续 5 次失败后停止重试并恢复原任务、完成结果读取失败后保留旧版本并联网同步、取消后迟到状态不覆盖终态，以及 12 站/4608 路线点的日期切换、费用编辑、版本保存和刷新。详细门槛、计时方法和实测值见 [RESILIENCE_PERFORMANCE.md](architecture/RESILIENCE_PERFORMANCE.md)。

账号第 10 项覆盖无效登录的摘要、字段定位和不发送凭证请求，详细范围见 [KEYBOARD_ACCESSIBILITY.md](architecture/KEYBOARD_ACCESSIBILITY.md)。

账号第 11 项覆盖客户端 TEST ONLY 关系篡改后的来源读取，真实服务仍按当前账号拒绝他人来源并返回 404；页面不显示对照表或其他用户行程内容。版本阶段真实样本使用南京两个公园与真实道路，生产 Web 构建完成一次原规划、一次调整保存和后续只读浏览；调用上限 7，不计入上表无密钥检查。详见 [SAVED_VERSIONS.md](architecture/SAVED_VERSIONS.md)。

账号第 12 项分别为两个测试账号保存 65 条明确 TEST ONLY 历史，验证翻页只含自身记录、他人 ID 搜索总数为 0、他人游标被拒绝。服务端另验证插入后旧快照页码和计数保持、重开同库可继续、字面通配字符不扩大查询、旧记录缺时间不补当前时刻。分页阶段的真实样本仍为两个真实版本，不将 65 条测试历史当作真实业务数据验收。

账号第 13 项延迟旧账号的第二页实际 GET 响应，退出后工作区清空；重新登录另一个账号再交付旧响应，新页面仍只包含新账号第一页的 50 个 ID，不混入旧账号内容、页码或焦点操作。

账号第 9 项验证编辑后会话失效、切换账号不显示原草稿、重新登录原账号恢复，以及主动退出清理。该多次登录场景使用独立测试账号，不改变生产登录限额。草稿数据、有效期与浏览器存储边界见 [EDIT_DRAFT_RECOVERY.md](architecture/EDIT_DRAFT_RECOVERY.md)。

新增的 MCP 客户端检查使用实际 stdio 子进程：生产工具服务的成功输出 Schema（测试进程显式注入 FixtureProvider）、现有规划算法、已有 ToolRegistry、工具白名单、调用次数/总时限、握手/调用超时、意外退出、文本或非法业务结果拒绝、错误脱敏、生产固定命令/凭证边界，以及任务取消和超时后的子进程退出。`POST /tool-service/check` 还对真实随仓库提供的服务执行不消耗 Provider 配额的握手；生产任务在缺 Key 时失败且不保存虚假行程。

账号浏览器套件另启动 `--auth-fixtures` 的隔离服务，测试账号只存在于临时库中：登录错误、HttpOnly Cookie、刷新与退出；主动退出前保护未保存编辑，取消退出保留当前账号；两用户的行程读取/调整隔离；跨标签页换号关闭旧空间；会话失效后重新登录；未确认提交不跨账号恢复；Bearer 登录与浏览器 Cookie 分离。后端还验证同名提交标识按用户去重、任务/事件/SSE/草案/重试的越权拒绝、CSRF/来源校验、密码重置/禁用/过期撤销、登录频率和会话上限、密码/Token 散列存储，以及旧库安全迁移和冲突回滚。

`scripts/verify_browser.py` 默认依次运行三个引擎的本地、账号和生产构建恢复/性能套件，可用 `--browser chromium|firefox|webkit`、`--suite local|auth|resilience` 或 `--grep` 定向运行。账号第 8 项新增离线退出失败后保留身份、联网后显式退出。脚本会清空测试子进程中的真实模型/地图凭证和浏览器地图配置。

## 数据与功能边界

测试服务必须显式传入 `--test-fixtures-only`，只绑定本机地址，数据库限制在仓库 `.tmp/`。FixtureProvider、固定模型回复和故障注入仅在 `tests/` 定义；生产服务不提供开启测试数据的配置。浏览器测试屏蔽外部 HTTPS，所有 POI 名称使用 TEST ONLY 标识。日志、截图和 trace 保存在被 Git 排除的 `artifacts/` 中，CI 仅在失败时上传测试诊断。

上述自动检查验证页面、API 与后端算法之间的调用和状态一致性。2026-10-19 另通过授权高德的本地真实联调，覆盖 POI、步行/驾车、直接 Provider/MCP 异步规划、多日编辑版本和 Web 保存重开。地图接入阶段的 JS API 检查覆盖底图、编号、道路折线、跨天切换和刷新；地图编辑阶段另完成 23 项真实检查及截图核对，见 [WEB_EDITING.md](architecture/WEB_EDITING.md)。前端构建通过且不含后端 Key。授权联调不计入上表无密钥检查集。实际范围、早期页面检查失败及后续复查记录见 [LIVE_AMAP.md](architecture/LIVE_AMAP.md)。未来交通与营业状态不在此次结论内；票价、库存、评论等无授权来源时保持缺失。

安全密钥代理阶段新增 12 项自动检查，总数增至 128。另在真实高德 SDK 下分别通过本地模式 25 项与账号模式 28 项检查，初始化代理请求全部成功，登录 Cookie 可用于该路径，退出后返回 401；安全密钥不在浏览器配置/请求/代理响应或前端构建中。步骤与部署边界见 [AMAP_PROXY.md](architecture/AMAP_PROXY.md)。此前 23 项地图编辑记录保留为历史验收。

本轮新增的后端检查覆盖用户/全局固定窗口持久化、原子扣减、队列与活动任务限额、去重不扣配额、真实 HTTP 429/Retry-After、查询/取消/退出仍可用、工具并发释放和 SSE 槽位回收。备份演练在源 WAL 连接仍运行时取得已提交快照，在新路径恢复后通过真实 API 登录两用户，核对行程/草案/收据归属、会话撤销、未完成任务终结、损坏/不兼容库拒绝和不覆盖已有文件。未恢复或修改个人业务数据库。

当前验收范围为本机单 API 进程的 Web 工作台，覆盖本地模式、多账号隔离、业务限流和本地备份恢复。公网 HTTPS、异地备份部署、多实例队列和移动端真机在 [后续计划](RELEASE_STATUS.md) 单列。启用与迁移方法见 [AUTH_ISOLATION.md](architecture/AUTH_ISOLATION.md)，限流配置和恢复方法见 [OPERATIONS.md](architecture/OPERATIONS.md)。

## API 恢复约定

`Itinerary.optimization` 为兼容性新增字段，旧行程默认 `null`；自动多日规划提供原方案、已核验候选、采用结果及有向路线调用数。新增分日检查覆盖道路绕行、方向不对称、每日约束、负担保护、预算/停留保留、最多 48 个路段，以及旧记录和手动分日兼容。上海/杭州的直接 Provider 与 MCP 真实比较不计入上述自动检查，见 [DAY_GROUPING.md](architecture/DAY_GROUPING.md)。

创建规划、草案、编辑或重试任务可携带 `Idempotency-Key`（8–128 位字母、数字、下划线、点、冒号或连字符）。同一标识与同一请求返回原任务；标识复用于其他请求返回 `409 idempotency_conflict`。未传标识的旧客户端保持原行为。

`GET /api/v1/travel/submissions/{key}` 查询提交收据。Web 在发送前保存请求快照与标识；页面刷新只查收据，未找到时等待用户显式恢复。临时网络失败保留快照，明确拒绝的请求清除快照。

`POST /api/v1/travel/tasks/{id}/retry` 仅允许可重试的失败、超时或取消任务，沿用服务端保存的请求，创建关联 `retry_of` 的新任务。旧记录没有请求快照时禁止伪造重试。SQLite 以新增表兼容已有记录。
