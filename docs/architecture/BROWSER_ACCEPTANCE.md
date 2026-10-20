# 跨浏览器与断网恢复验收

日期：2026-10-20。环境：Windows、Python 3.12、锁定的 Playwright 1.64.1，Chromium / Firefox / WebKit Headless。本轮只在本地运行，没有推送 GitHub 或触发云端检查；未升级核心依赖。

## 可复现检查

先按根 README 安装锁定依赖。在项目根目录执行：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.cache/playwright"
npx playwright install --only-shell chromium firefox webkit
.\.venv\Scripts\python.exe scripts/verify_repository.py
.\.venv\Scripts\python.exe scripts/verify_browser.py
```

Linux 安装命令增加 `--with-deps`。浏览器安装方式及项目配置参照 [Playwright 官方浏览器文档](https://playwright.dev/docs/browsers)。编排脚本默认依次运行三个引擎的本地、账号两套测试；每次使用独立临时数据库和服务端口，清空真实凭证并阻止测试页面的外部 HTTPS。没有生产模拟数据开关。

```powershell
# 单浏览器完整验收
.\.venv\Scripts\python.exe scripts/verify_browser.py --browser firefox
# 仅复查某个场景；不能把筛选结果当作完整验收
.\.venv\Scripts\python.exe scripts/verify_browser.py --browser webkit --suite local --grep "offline edit submission"
```

默认仍为单个 Playwright worker、无自动重试；浏览器之间不共享原条件重试标记、账号或配额。直接对同一测试服务运行所有 project 不具备此数据库隔离，因此完整验收使用 Python 编排脚本。

JSON 报告位于 `artifacts/browser-reports/{engine}/{local|auth}.json`，失败 trace/截图位于 `artifacts/browser-results/{engine}/{suite}/`，服务日志位于 `artifacts/browser-diagnostics/{engine}/{suite}/`，均被 Git 排除。CI 配置已同步安装三个引擎并保留失败报告；此次没有运行 Ubuntu CI。

## 结果与范围

| 引擎 | 本地工作台 | 账号流程 | 失败 / 跳过 / 重试后通过 |
| --- | ---: | ---: | --- |
| Chromium | 22 | 9 | 0 / 0 / 0 |
| Firefox | 22 | 9 | 0 / 0 / 0 |
| WebKit | 22 | 9 | 0 / 0 / 0 |

草稿恢复阶段增至 31 个页面场景、93 次浏览器执行；加上 Python 92 和 TypeScript 23，共 146 个逻辑用例、208 次执行。Web 类型检查、Vite 构建及 OpenAPI 生成一致性通过。次数包含不同引擎执行同一页面场景，不表示新增了 208 个不同业务功能。

新增场景验证本机编辑草稿的刷新恢复、版本/归属核对、详情失败保留、跨页面冲突、回执优先恢复与配额/存储拒绝，以及原账号恢复和主动退出清理；细节见 [EDIT_DRAFT_RECOVERY.md](EDIT_DRAFT_RECOVERY.md)。调试时发现按日期误选新子版本，已固定选择原版本；多次登录改用独立测试账号，保持生产限额不变。一次 WebKit 运行被修改源码触发的 Vite 热更新打断，trace 已确认；最终矩阵在固定源码下重新完整执行，无自动重试。

已有场景在三个引擎中重复验证需求补充/冲突、请求收据、重试、SSE 转轮询、取消、地图地点列表与时间轴选择、跨天编辑、新旧版本、未保存修改、刷新取消、登录与账号隔离。新增网络场景如下：

1. 服务器已受理规划，POST 响应延迟 900 ms、状态读取延迟 350 ms；表单保持禁用，再触发表单不会重复 POST，最终仍展示同一任务。
2. 任务进行中使用真实 `BrowserContext.setOffline` 断网，确认 `navigator.onLine=false` 和状态请求失败；恢复网络后显示同一任务及行程，没有第二次创建 POST。
3. 离线提交编辑失败后保留费用 0、停留 90 分钟及同一提交标识。联网时只查询收据，确认没有受理记录后等待用户显式恢复，不自动重放。再次保存使用原标识创建新版本，费用和停留不丢失。
4. 退出登录时断网，保留当前账号与工作空间；恢复后服务端会话仍有效，用户再次退出成功后才回到登录页。

这些是有界延迟和离线状态注入，不等同于特定 3G/4G 带宽、随机丢包或长时间离线压测。成功行程只使用 tests 中明确标记的 TEST ONLY 输入，不计为真实高德数据验收。

## 修复与平台差异

- WebKit 鼠标点击按钮时不保证按钮成为 `document.activeElement`。原来对话框仅记录活动元素，取消时可能返回输入框或页面根节点。现在在退出、打开行程、创建/重试和退出登录的入口记录实际触发元素；对话框关闭后仅在该元素仍连接时恢复焦点。三个引擎已核验退出编辑、新规划、打开行程及主动退出登录的焦点恢复。
- 收据查询成功但未受理时，原来保留 `connection=offline`，导致网络恢复后仍提示“恢复连接”。现在查询成功即同步连接状态，同时保留待恢复提交与原请求，不自动创建任务。
- 原地图在 Vue 更新布局前计算视野，曾记录 SDK 高度 470、DOM 高度 660（退出编辑时相反）。现在在 DOM 更新后重绘；日期、地点或编辑视图改变时重建 SDK 实例，避免 WebKit 复用旧实例后底图空白。费用和时长输入不触发该重建，选择站点仍只更新高亮与平移。这会增加视图切换的 SDK 初始化请求，仍受既有配额限制，不重查 POI/路线。
- 真实 SDK 的成功初始化 JSONP 被上游标成 `application/octet-stream`，错误响应也可能标成 `application/json`。原代理保留该类型并设置 `nosniff`，WebKit 因此拒绝执行。现在只对匹配已验证回调且内部内容可解析为 JSON 的响应返回 `application/javascript`；继续保留 `nosniff`，非法包裹、非 JSON、额外脚本和错误编码均拒绝。普通 JSON 响应不变，新增后端回归使地图代理检查增至 13 项。此修复消除了 MIME 拒绝，底图重绘还需要上述实例生命周期修复。
- 首轮 Firefox 在 Codex Windows 受限沙箱中无法建立自动化管道，离线最小启动复现超时；在正常 Windows 权限下启动成功并完成全部套件。仅关闭本轮测试所属的进程；无需改浏览器偏好或降低应用鉴权。终端复现若遇同类沙箱限制，在正常用户终端运行上述命令。
- Windows WebKit 的 Cookie 元数据会把 Strict 报告为 None；[锁定版本的官方测试也记录此限制](https://github.com/microsoft/playwright/blob/v1.64.1/tests/library/browsercontext-cookies.spec.ts#L110-L120)。测试仍在所有引擎中验证服务端 `Set-Cookie: SameSite=Strict`、HttpOnly、登录/刷新/退出与数据隔离；Chromium/Firefox 另外验证 Cookie 元数据。Windows WebKit 此项使用明确的平台限制注解，不跳过整个账号场景，不修改生产 Cookie 设置，也不声称验证了该端口对跨站 SameSite 的完整执行。

WebKit 引擎通过不等同于已在 macOS/iOS Safari 真机验收。实际部署的 HTTPS、域名授权、不同设备、完整键盘流程、持续弱网和大行程性能仍按部署与质量计划继续验证。

## 真实地图补验

地图生命周期与代理阶段的代码在三个引擎中各完成 30 项真实 SDK / 同源代理检查，合计 90 项，不计入无密钥执行。全部使用真实上海保存行程库的独立副本和一次性登录账号，没有重新查询 POI 或路线，没有修改个人业务库。后续本机草稿恢复阶段只运行隔离自动检查，没有再次调用真实地图；此处为此前授权验收记录。

| 引擎 | 检查 | 高德响应 / 瓦片及地图资源 | 地图 HTTP 失败 |
| --- | ---: | --- | ---: |
| Chromium | 30 | 475 / 438 | 0 |
| Firefox | 30 | 353 / 330 | 0 |
| WebKit | 30 | 477 / 446 | 0 |

检查覆盖底图、标记、道路折线、多日切换、双向定位、编辑顺序/差异、放弃后恢复、标记位于视野内、刷新、凭证边界和退出后的 401。补充同一登录会话的真实 HTTP 请求读取代理正文，校验安全密钥未回显；浏览器配置和请求均无安全密钥。最终没有应用脚本异常或 JSONP MIME 拒绝；截图时的 GPU 性能提示、第三方 SDK 弃用信息、主动屏蔽字体及退出后的拒绝响应不被解释为业务数据成功。

已目视核对三个引擎编辑和恢复后的地图视口截图；另以中心区域颜色占比辅助识别空白画布，六张图均超过 2%（原空白样本约 0.1%）。像素检查只用于此次选定城市样本，不能单独代替地图质量或语义验收。

较早的自动断言只检查 SDK 节点、标记和请求成功，曾把 WebKit 空白底图误判为通过；该结论已由视口截图复查纠正。诊断确认：额外等待 15 秒仍空白，重新创建同数据地图后正常；单独修正尺寸或动画未解决底图问题。最终采用上述生命周期处理，并独立修复 JSONP MIME。没有关闭证书验证、移除 nosniff 或引入模拟数据。

Windows 沙箱内的 WebKit 曾因证书访问限制无法加载官方 SDK；正常用户权限下访问成功，故真实 Firefox/WebKit 补验在正常权限下进行。早期 Firefox 读取错误 MIME 的 JSONP 正文还出现协议诊断失败；最终 MIME 修正后的响应正文可读取，旧失败报告保留，不修改为成功。

本地证据被 Git 排除：`artifacts/live-map-chromium-20261019T171315Z/`、`live-map-firefox-20261019T171318Z/`、`live-map-webkit-20261019T171146Z/`；汇总为 `artifacts/live-map-matrix-summary.json`。无密钥矩阵汇总为 `artifacts/browser-matrix-summary.json`，详细六份 JSON 报告在前述 browser-reports 目录。UTC 时间戳均对应北京时间 10 月 20 日；克隆仓库不会附带这些授权记录、截图或数据库。
