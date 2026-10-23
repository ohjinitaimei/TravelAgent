# 需求输入保护与真实提取核验

日期：2026-10-24。基线为本地提交 `d8aaf85`，继续以 Web 为优先、同一 FastAPI 和 HelloAgents 需求入口为业务边界。

## 用户流程

旅行需求原文、未保存的补充、勾选状态和逐日修改由工作台持有。切换到预算、推荐或已保存页面后再返回，继续使用当前输入。输入不会因需求组件重新挂载而重置。

刷新或重新打开浏览器时，页面提示“本机需求输入”。点击“恢复需求输入”后才恢复，用户随后显式整理或保存补充；恢复不会发送草案、规划或补充请求。“放弃本机需求备份”只清理本机副本，服务器草案保留。

每份补充绑定草案 ID 和修订号。服务器草案更新或当前任务返回另一份草案后，未保存补充作为原始修改保留供核对，不能套用到新版本。页面显示来源和保留的字段/逐日修改，保存按钮禁用；用户可明确“放弃未保存补充”，再核对当前版本。原有“加载最新草案（替换未保存补充）”继续作为用户明确放弃旧补充的操作，读取失败仍保留输入。

成功保存补充只清理实际提交或确认的字段，未勾选的修改继续保留。只有已知本次原子 PATCH、同一草案紧接下一版、且保留字段的服务端基线没有变化，才将剩余输入绑定到新修订号；无法证明时保留原来源并提示核对。已确认的任务结果只清理与服务器原文相同的输入，保留后来输入的新文本；恢复提交收据时同样沿用这一规则。

## 本机保存规则

- 同账号、同浏览器保留 7 天，32 KiB 上限；过期或格式无效的副本不会自动恢复。
- 数据是原文覆盖、用户修改/勾选、逐日修改差量及草案 ID/版本。未修改的模型值、证据、POI、路线、账号会话令牌不随备份写入。
- 逐日差量保留明确空值、清空动作和用户选定的数量；不会给未填写的子项补默认值，也不自动裁剪日期。
- 写入或删除前核对上次读到的存储内容。其他页面改动后暂停覆盖，保留本页内容，并提供“读取最新需求备份”后再显式恢复/放弃的操作。
- 配额或私密模式等存储失败会提示“需求输入未能保存到本机”，保留当前内存输入与原耐久副本，仍可手动提交。无法安全保存时，离开浏览器有未保存保护。
- 账号失效或切换后，旧输入不会进入其他账号；同账号重新登录后可显式恢复。成功退出登录会清理当前账号的需求备份，其他账号备份保留。

类型白名单和长度检查作用于恢复数据；后端继续独立校验提交。该副本不是服务器草案，也不自动确认模型解释。

## 日期与共享请求契约

`DraftRequest.reference_date` 保持现有契约。新草案点击提交时，按 `Asia/Shanghai` 即时计算参考日；保持页面跨午夜或使用其他浏览器时区，也不会继续使用打开页面时的旧日期。页面说明相对日期的时区，并显示每份服务器草案实际采用的参考日期。

已受理任务、未确认提交收据和按原条件重试沿用冻结的原请求，跨日恢复不重算旧请求的参考日期。用户填写的出发日期和规划约束不随此操作变动。

## 实际模型验收方法

复用 `scripts/verify_live_clarification.py`，保留原 legacy 用法，新增两份预先固定的验收输入和独立断言：

| 场景 | 判定范围 |
| --- | --- |
| `complete15` | 全部 15 字段，包括共用和不同的逐日时段/停留、两项交通上限、逐字起返提示；原文依据、模型来源和未确认状态 |
| `partial-daily` | 逐日只说第一天开始、第二天结束，其他子项保留 null；未确定的日期、交通方式、预算、停留等不补默认值 |

每次最多一次草案 POST，不自动重试；检查单次 Agent 调用事件、确认、用户填写 0 元、明确清除、409 修订冲突、422 合并拒绝、原文/来源保留、任务与事件未重调，以及没有新行程。仅草案符合 Schema 不足以通过，具体字段和缺项也须符合事先定义的要求。

每次输出使用新的目录或未存在的 `--output`。报告先保留运行状态，成功或失败都写入终态；已存在输出在 HTTP 前拒绝，失败信息只保留错误类型和检查代码。报告中的一次 Agent 事件与单请求配置是调用边界证据，不是供应商账单计数。HTTP 入口不冒充浏览器点击或实际地图/SDK 验收。

```powershell
# 先使用独立空数据库启动同一 API，并显式启用需求整理。
# 每条命令最多一次真实模型调用；未提供授权或依赖时先检查配置。
.\.venv\Scripts\python.exe scripts/verify_live_clarification.py --allow-model-call --scenario complete15 --base http://127.0.0.1:8000/api/v1/travel --reference-date 2026-10-24 --date 2026-10-26
.\.venv\Scripts\python.exe scripts/verify_live_clarification.py --allow-model-call --scenario partial-daily --base http://127.0.0.1:8000/api/v1/travel --reference-date 2026-10-24 --date 2026-10-26
```

## 文件与运行

| 范围 | 文件 |
| --- | --- |
| 受控需求输入及本机存储 | `apps/web/src/requirementsInput.ts`、`components/RequestAssistant.vue`、`components/DraftDailyReview.vue` |
| 工作台恢复、确认和账号清理 | `apps/web/src/App.vue`、`session.ts` |
| 北京时间参考日 | `apps/web/src/referenceDate.ts` |
| 真实提取核验 | `scripts/verify_live_clarification.py`、`live_requirements_cases.py` |
| 回归 | `tests/requirements_input.test.ts`、`reference_date.test.ts`、`test_live_clarification.py`、`tests/browser/requirements.spec.ts`、`auth.spec.ts` |
| 归档构建清单的跨平台排序 | `scripts/verification_context.py`、`tests/test_verification_context.py` |
| 执行和说明 | `package.json`、`playwright.config.ts`、README、使用手册、验收/范围说明和源码清单 |

安装和启动仍按 [README](../../README.md) 与 [Web 使用手册](../USER_GUIDE.md)。统一 API Schema、后端草案字段和业务算法继续复用原实现；没有引入新的 Agent、核心依赖或移动端工程。

## 验证记录

原文切页丢失和跨日参考日错误已分别在改动前用浏览器复现，记录保留在 `requirements-preflight-20261024`。新输入保护 6 项及账号恢复/清理 1 项的预检断言通过，执行期间源码变化导致元数据检查拒绝，保留在 `requirements-targeted-20261024-01`，不计为最终完整证据。

保存部分字段后丢失未勾选修改，也已先在 `requirements-ack-preflight-20261024` 复现。修正后 `requirements-ack-targeted-20261024-01` 单项通过，保留了预算单独保存、未勾选城市/逐日输入、刷新恢复及下一次显式保存的证据。

预备完整组 `requirements-accepted-20261024` 在执行期间新增上述回归，源码指纹发生变化，不能作为最终通过。该组 WebKit 本地套件的断言通过，但服务退出未通过，临时日志删除遇 Windows 文件占用；原失败元数据和目录保留。没有放宽退出期限或强制终止来计作通过。输入保护功能随后使用新的 `requirements-final-20261024` 完整复验。

该功能组 Python 309、TypeScript 95、三引擎各 58 项本地工作台 + 16 项账号 + 26 项生产构建恢复流程全部通过，合计 504 个逻辑用例、704 次执行；零跳过/自动重试，九套浏览器服务均正常退出。本次 WebKit 的关闭异常未复现。类型、无密钥生产构建、OpenAPI/TS 一致性及源码/Web 字节绑定通过，本地 HTTPS 另有 29 项通过，未修改系统证书信任。

该功能组证据入口为 `artifacts/repository-runs/requirements-final-20261024/report.json`、`artifacts/browser-runs/requirements-final-20261024/summary.json` 和同组九套完整报告，以及 `artifacts/drill-runs/requirements-final-20261024/deployment/`。首次归档没有生成，因此未执行该组的归档启动、恢复或候选门禁；以下排序修复后的新组才用于最终交付。

## 归档清单的 Windows 排序修复

输入保护提交 `a2d0475` 的上述 704 次检查通过后，首次归档被严格构建比较拒绝，没有生成 ZIP。原因是 Windows `Path` 自然排序忽略大小写，而归档按 POSIX 路径字符串排序；本次 Vite 的 JS/CSS 哈希名称混合大小写，出现相同文件、大小和 SHA256，列表顺序却不同。原失败依据单独保留在 `artifacts/requirements-package-preflight-20261024.json`。

新增一个混合大小写资源名称用例，旧实现先失败；`tree_digest` 统一按相对 POSIX 字符串排序后，相关源码/构建、归档和候选证据回归共 31 项通过。没有修改文件内容、哈希算法或符号链接拒绝规则，也没有直接改写原通过报告。由于验收工具源码发生变化，重新使用 `requirements-portable-20261024` 执行完整仓库、三引擎和 HTTPS 检查；最终归档、恢复及候选门禁须采用该新组。

该最终组 Python 310、TypeScript 95、三引擎各 58 + 16 + 26 项全部通过，共 505 个逻辑用例、705 次执行，零跳过/自动重试。类型/构建、OpenAPI/TS 一致性、九套服务正常退出及源码/Web 字节绑定通过；同组 HTTPS 29 项通过，临时资源清理完成，外部调用为零、系统证书信任未修改。

最终证据入口为 `artifacts/repository-runs/requirements-portable-20261024/report.json`、`artifacts/browser-runs/requirements-portable-20261024/summary.json` 和九套完整报告，以及 `artifacts/drill-runs/requirements-portable-20261024/deployment/`。干净提交的 ZIP、SHA256SUMS 与四项归档独立启动结果在 `artifacts/releases/`；同一 ZIP 的恢复与候选门禁分别保存在 `artifacts/drill-runs/requirements-portable-20261024/recovery/` 和 `artifacts/candidate-runs/requirements-portable-20261024/report.json`。这些入口只有报告明确通过才构成证据，不将其他归档、旧源码或历史模型记录混为当前通过。真实模型结果继续单列如下。

## 真实模型结果与能力边界

2026-10-24 仅执行预先固定的两个草案提交，共记录两次 `agent_call`，未追加重试。`artifacts/requirements-live-20261024-attempt2/summary.json` 如实标记整体失败：

| 场景 | 实际结果 |
| --- | --- |
| `complete15` | 通过；字段、缺项、原文依据、模型来源、用户确认/修改/清除及冲突校验均通过 |
| `partial-daily` | 任务失败，错误码 `invalid_agent_output`；未生成草案，未将缺项补成默认值 |

部分日程场景约十秒返回校验失败，未触发任务超时。日志没有保留模型工具参数或具体校验路径，不能推断失败由哪个字段、依据或调用外形导致；不能据此声称部分日程真实提取已通过。后续应先增加不泄露输入和凭据的结构化校验诊断，再以明确预算单独复验。当前用户可重新描述或直接填写原有表单，不会以模拟结果降级。

两个任务均为需求草案任务，合计保存一份草案、零行程；本次没有调用高德、地图 SDK 或路线规划。临时 API 正常退出、未强制终止；核验用连接未及时释放导致首次清理失败，保留原记录并在进程退出后核对精确临时路径完成清理。源码和环境文件未被该演练修改。首个启动尝试因临时环境错误清空地图超时配置而在启动前退出，模型调用为零；该记录单独保留，不混入两个场景结果。

这些报告、日志、截图和临时数据库都是本机忽略产物，不随 Git 或发布源码提交。真实模型调用与 TEST ONLY 自动回归分别记录；自动回归通过不代表上述真实模型失败已消除。
