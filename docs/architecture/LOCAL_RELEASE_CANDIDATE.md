# 本地发布候选综合验收

2026-10-23，优化计划 C 包。A/B 功能与既有 API、单一 Provider/MCP、算法和锁定依赖一起验收；本轮补齐发布工具的证据绑定、完整恢复核对及文档入口，不新增业务 Agent 或重写前端。只在本地生成提交和归档，不触发 GitHub 上传、PR 或公网发布。

## 交付范围与判定

| 验证 | 本地范围 |
| --- | --- |
| Python / 共享客户端 | 全部根 `test_*.py` 独立执行；295 项 Python、62 项 TS；包含 direct/MCP、任务超时/取消/限流、账号、地图代理、Schema、备份和新增发布工具拒绝测试 |
| 三浏览器 | 每引擎 local 47 / auth 13 / resilience 26，共 258 次；需求→规划→编辑→刷新/离线恢复→保存→来源对照、最大十二站及旧功能回归 |
| 源码与生产 Web | 类型检查、契约再生成一致、源码起止指纹不变；构建文件和归档内实际字节一致 |
| 本地 HTTPS | 29 项原有网关/登录/CSRF/幂等/SSE/保存/退出及入口检查；私有 CA 显式交给客户端校验，不关闭 TLS 校验，不安装信任根 |
| 备份 / 恢复 / 回退 | 97 项检查：在线快照、停服到新路径恢复、较新快照回退、双账号隔离、旧会话撤销、未完成任务中断与显式重试；逐份完整 A/B 行程、草案和完成收据核对 |
| 归档启动 | 同一 ZIP 先验证再解压，空 TEST ONLY 库执行 live / ready / 匿名拒绝 / 首次账号状态 4 项 |
| 候选汇总 | `verify_candidate.py` 核对同组仓库/九份浏览器/HTTPS/恢复/runtime、源码和 Web 摘要及同一归档 SHA；缺项、旧项或清理失败均拒绝 |

Python、客户端和浏览器合计 **615 次执行 / 443 个逻辑用例**，不重复计入定向检查。HTTPS、恢复及归档启动独立计数，完成的具体检查名称和数量由同组报告保留；正式归档恢复/回退为 97 项。服务结束和临时目录清理也是通过条件，不能把已跑完断言等同于正常完成。

恢复预演组 `c-recovery-preflight-20261023` 使用脏工作区快照，只作诊断，不用于最终候选；正式阶段对干净提交的确切 ZIP 再次验证。

本地证据组为 `c-release-final-20261023`；最终汇总为 `artifacts/candidate-runs/c-release-final-20261023/report.json`。运行记录不随 Git 或发布包分发，接收源码后使用新的 run ID 复现。报告哈希用于关联本地记录，不是签名，也不能独立证明第三方来源。

## 修正的发布缺口

旧浏览器汇总仅核对用例和 run ID，可能接受不同版本的完整旧报告。本轮将每次执行绑定到业务/验收源码、锁文件、构建与测试配置；起止必须相同，汇总同时复核报告文件哈希。旧 A/B 报告保持原始记录，但不能作为当前候选的新报告。仓库统计只接受 Python 纯成功及 Node pass 等于 tests、失败/取消/跳过/todo 为零，不能将退出码为 0 的跳过计为通过。

旧打包只要求 dist 存在。本轮 `verify_web_build.py` 记录实际构建与源码关系；打包核对实际选入的 Web 字节，不能先验证默认 dist 再通过 `--web-dist` 装入另一份旧文件。`RELEASE.json.verification` 记录源码与 Web 摘要；候选还会与生产构建浏览器和 HTTPS 的 Web 字节逐份比较。

部署报告原来在关闭服务前就写成功。本轮独立 `drill_runs` 保存运行、服务退出与最终状态，非零退出、强制结束、清理失败和源文件变化都不能通过，原失败不被后续清理覆盖。`--run-id` 为 HTTPS 和恢复分别保留独立目录，同一 scope 不允许覆盖。

恢复检查不只比较标题/数量：测试种子包含有限备选优化的真实算法对照及原始事实、显式调整来源、部分逐日草案、交通上限/地点原文、两次澄清的证据/来源/确认/修订历史，以及完成提交收据。HTTPS 恢复/回退后完整 DTO 相等；局部数据库回归另比较 owner、请求快照与提交指纹绑定。所有种子显式 TEST ONLY，生产入口不会引用。

打包禁止数据库、环境配置、私钥与签名库，新增拒绝 `.jks`、`.keystore`、`.ppk`、`.p8`、`key.properties` 和常见 SSH 私钥文件名。模板和公开 JS Key 仍按既有约定处理。最终源码清单与源码/构建凭证检查保留；不将忽略目录直接交给发布扫描。

归档 README 的 11 个搬家后相对链接已修正。两张未保留的历史 HelloAgents 本地截图改为明确的文件名记录，不伪造图片或用新截图替代旧真实证据。

## 证据绑定方式

`verification_context.capture` 仅从 Git 管理或未忽略的源文件中收集 `backend/`、`apps/web/`、`packages/api-schema/`、`deploy/`、`scripts/`、`tests/` 和根 npm 锁/配置、Playwright 配置，文本以 LF 归一化。忽略的凭证、数据库、缓存和构建不会进入源码指纹。

文档、源码清单、运行记录及未参与验收的 Flutter 不进入业务指纹；它们仍由发布清单逐文件核对。测试可以在最终提交之前完成，但最终 ZIP 内受检源码必须与报告完全相同，不能只凭 base commit 或日期宣称相同。源码/测试/脚本/锁文件变化后应使用新 ID 重跑；只整理文档不会改变受检代码。

证据分别保存在：

```text
artifacts/repository-runs/<id>/report.json
artifacts/browser-runs/<id>/<engine>/<suite>/{run,report}.json
artifacts/drill-runs/<id>/{deployment,recovery}/{run,report}.json
artifacts/web-builds/<build-id>/build.json
artifacts/web-build.json                          最新构建记录指针
artifacts/releases/<commit>/{TravelAgent.zip,SHA256SUMS,runtime.json}
artifacts/candidate-runs/<id>/report.json
```

候选汇总同时校验实际源码和包内 Web、九个完整浏览器 scope、全部当前 Python 模块、运行报告哈希、正常退出、TLS 范围、runtime/恢复的归档 SHA-256。失败报告不会自动删除，也不自动复跑、放宽阈值或改用假数据。

## 复现顺序

先按 README 安装锁定依赖、三个浏览器和本地已校验的 Caddy v2.11.7。每组 ID 只能使用一次；例中的 `local-candidate-01` 和版本输出目录需换成自己的唯一名称。

```powershell
.\.venv\Scripts\python.exe scripts/verify_repository.py --run-id local-candidate-01
.\.venv\Scripts\python.exe scripts/verify_browser.py --run-id local-candidate-01
.\.venv\Scripts\python.exe scripts/summarize_browser_runs.py --run-id local-candidate-01
.\.venv\Scripts\python.exe scripts/verify_deployment.py --caddy .tmp/tools/caddy/caddy.exe --run-id local-candidate-01
```

`verify_repository` 同时生成源码绑定的无凭证生产构建。若仅重建发布 Web，用 `python scripts/verify_web_build.py`，不要直接手改 dist；新的字节需要对应的浏览器/HTTPS 证据。

代码与检查通过后整理文档、更新源码清单并提交本地 Git；最终交付包必须标记 `working_tree_dirty=false`。之后针对这个干净提交的同一 ZIP 执行：

```powershell
.\.venv\Scripts\python.exe scripts/update_publish_manifest.py --check
.\.venv\Scripts\python.exe scripts/package_release.py build --output artifacts/releases/自己的提交
.\.venv\Scripts\python.exe scripts/package_release.py verify artifacts/releases/自己的提交/TravelAgent.zip
.\.venv\Scripts\python.exe scripts/verify_release_runtime.py artifacts/releases/自己的提交/TravelAgent.zip > artifacts/releases/自己的提交/runtime.json
.\.venv\Scripts\python.exe scripts/verify_recovery.py artifacts/releases/自己的提交/TravelAgent.zip --caddy .tmp/tools/caddy/caddy.exe --run-id local-candidate-01
.\.venv\Scripts\python.exe scripts/verify_candidate.py --run-id local-candidate-01 --archive artifacts/releases/自己的提交/TravelAgent.zip --runtime artifacts/releases/自己的提交/runtime.json
```

所有数据库、证书和服务目录只位于脚本创建的隔离目录，监听回环。恢复写入全新目标，不覆盖个人库，不安装后台服务或定时任务。

## 实际范围与后续里程碑

本轮脚本清空高德/模型/SDK 凭证，浏览器阻止远程请求；`externalCalls: 0` 表示测试输入与执行配置，不是抓包审计结论。HTTPS 客户端验证临时 CA；未安装浏览器/系统信任根，未验证公网 DNS、ACME、真实域名、Linux systemd 权限或异地备份。既有真实高德/direct/MCP、SDK 和模型记录维持原日期与范围，不混作本轮结果。

没有收集新的真实用户满意度，也没有获得未来营业、预约、真实票价或库存能力。原 Flutter 保留；`apps/mobile` 仍为接入说明。移动端实际工程和真机双端联调是独立里程碑，不能用 Web 或本地 HTTPS 的通过替代。

下一阶段若推进移动端，按已有生成 Schema、统一 transport、Bearer 和轮询接入同一后端；若推进公网交付，待有服务器后执行域名、系统服务与外部恢复验收。上传 GitHub 由用户另行明确发起。

## 文件范围

| 范围 | 文件 |
| --- | --- |
| 新增证据与构建入口 | `scripts/verification_context.py`、`verification_counts.py`、`verify_web_build.py`、`verify_candidate.py`、`drill_runs.py` |
| 现有验收和打包 | `verify_repository.py`、`verify_browser.py`、`summarize_browser_runs.py`、`verify_deployment.py`、`verify_recovery.py`、`verify_release_runtime.py`、`package_release.py` |
| 新增回归 | `tests/test_verification_context.py`、`test_verification_counts.py`、`test_candidate_evidence.py`、`test_drill_runs.py` |
| 完整恢复及拒绝回归 | `tests/recovery_seed.py`、`test_recovery_safety.py`、`test_release_package.py`、`test_browser_runs.py` |
| 文档与交付 | 本文、README、验收/发布范围/优化计划、部署/备份/恢复说明、历史链接、CI 失败诊断目录及 `PUBLISH_MANIFEST.json` |

生产 API、业务 Schema、推荐/优化/调度和 Web 产品代码未在 C 包改动，核心依赖保持锁定。Web/App 仍只通过同一后端实现业务能力。
