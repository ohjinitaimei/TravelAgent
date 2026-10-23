# 需求整理校验诊断

日期：2026-10-24；基线归档为 `bea0f6c`。本阶段继续本地 Web 开发。

## 问题与实现

上一阶段真实模型的完整 15 字段场景通过，局部逐日场景返回 `invalid_agent_output`。旧日志没有工具参数或校验路径，无法追溯具体失败字段。代码审查发现两处诊断丢失：Pydantic 异常转为通用错误后丢失字段路径，工具注册层又只传递错误码。新增回归先复现缺失诊断，记录为 `artifacts/intake-diagnostics-preflight.log`。

现在错误契约增加可空的 `draft_validation`，旧错误与旧保存任务缺省为 null。最多八条去重提示，每条只有白名单字段路径与有限原因码：缺项、类型、范围、格式、条件冲突、不支持字段或缺少原文依据。逐日下标限制为第 1–3 天；模型自定义键统一折叠到受控父路径。不会序列化原始输入、Pydantic 消息/上下文、原文、模型完整回复、凭据或私有地址。

同一个校验失败对象穿过现有工具层，工作进程和 HTTP 错误使用同一 Schema。异步任务持久化该错误；事件增加通用的 `draft_rejected` 提示，既不带原始值也不触发再次调用。Schema、调用次数、任务超时和无模拟数据规则保持原有要求。

Web 任务区显示中文字段及原因，例如“第 1 天开始时间：格式不符合要求”，说明这是模型返回内容的校验，不将错误归咎于用户。原文继续保留；用户可手动修改描述后整理，或直接填写规划表单。刷新恢复使用同一失败任务，不重新提交模型请求。

## 文件

- `backend/agent/intake_diagnostics.py`：校验路径与原因的有限映射。
- `backend/agent/travel_intake.py`：保留安全诊断、原文依据诊断和单次拒绝事件。
- `backend/travel/schemas.py`、`provider.py`、`worker.py`、`runtime.py`：错误契约及跨进程/HTTP 传递。
- `packages/api-schema/openapi.json`、`schema.d.ts`：后端导出及生成的共享类型。
- `apps/web/src/components/DraftValidationGuide.vue`、`TaskExecution.vue`：中文提示及旧任务兼容。
- `tests/test_agent_intake.py`、`tests/browser_fixture_server.py`、`tests/browser/requirements.spec.ts`：隐私、边界、单次调用、工作进程及三浏览器失败恢复回归。固定模型回复只在 tests 中使用。

## 验证与限制

Agent 专项 12 项通过，包括新增四项：未知键/原始值不泄露、最多八条、真实框架单次拒绝及关闭客户端、工作进程序列化/原文依据/旧错误兼容。三引擎各一项定向失败流程通过，零自动重试，服务正常退出；类型和生产构建通过。

完整仓库 Python 314 项、TypeScript 客户端 95 项、类型/生产构建和 Schema 一致性全部通过，服务正常退出；三浏览器定向 3 次另列。共 412 次执行，不包含未重跑的完整矩阵。

完整仓库报告为 `artifacts/repository-runs/intake-diagnostics-20261024/report.json`；本轮定向浏览器记录为 `artifacts/browser-runs/intake-diagnostics-20261024/<engine>/local/`。带 grep 的单项记录不冒充完整套件，不能拼成发布候选矩阵。此前 `requirements-portable-20261024` 的完整 705 次、HTTPS/恢复/归档通过结论仅属于旧归档 `bea0f6c`。

本轮真实模型与高德调用均为零，没有重跑真实提取、完整浏览器矩阵、HTTPS、灾备或新归档。局部逐日真实提取失败的具体原因仍未知，不能宣称已修复其准确率。下一步预先固定局部逐日、未知值和明确清空场景及合计调用预算，再进行有界真实核验；失败可按本轮安全字段诊断定位，严格校验与手动入口继续保留。

## 接续：原文依据格式真实复验

以上零外部调用及 314/95 结果属于诊断链路提交 `69fda7b`。随后固定同一个 `partial-daily` 输入，以合计最多两次模型调用执行定位、修正和复验；两次各用一个空临时数据库，没有修改个人库或环境文件。

第一次任务失败，新增安全诊断给出 `evidence / type`，事件为 queued、running、agent_call、draft_rejected、failed。它证明原文依据的类型违反 Schema，不能据此指认某个具体值为 null、数组或对象，也不能推断更早那次失败完全相同。没有保存草案或行程。证据为 `artifacts/intake-diagnostics-live-20261024-01/{summary,partial-daily}.json`。

修正只加强同一个 Agent 的工具格式说明：evidence 必须是字段名到原文字符串的对象，未知字段必须省略依据键，逐日依据也必须是一段原文字符串。没有修改 Schema、放宽类型、丢弃非法依据、补默认值或增加模型重试。两个新增离线回归覆盖非法依据值仍严格拒绝，以及稀疏字符串依据和局部逐日空值仍被保留；Agent 专项共 14 项通过。

第二次同一固定输入通过实际 HTTP 模型核验：15 个字段逐项比对、未知值和逐日未说明子项保留 null、原文依据/来源与未确认状态、用户确认、0 元预算、交通上限修改、明确清空、409 冲突及 422 无效合并不覆盖，全部通过。澄清期间没有追加模型事件，也没有生成行程。证据为 `artifacts/intake-diagnostics-live-20261024-02/{summary,partial-daily}.json`。

两次合计两个草案任务、两次 agent_call 事件、一份保存草案、零行程；没有高德、地图 SDK 或路线调用。API 均正常退出、没有强制终止，临时资源已清理，源码和环境文件在各自运行期间保持不变。事件加固定单请求配置证明调用上界，不冒充供应商账单计数。

同一场景一次通过不代表所有表述稳定通过，也不能把两次实时模型响应差异全归因于提示文本。原失败和首次拒绝记录保留；完整 15 字段场景本阶段未再付费重跑。后续按明确预算扩充歧义表达和不同输入形式，继续保留严格拒绝与手动填写。

修正后的完整仓库回归 `intake-evidence-20261024`：Python 316 项、TypeScript 95 项、类型/生产构建和 Schema 一致性全部通过；三引擎各 1 项失败提示/刷新/手动入口定向流程通过，共 414 次执行（Agent 14 项包含于 Python 总数）。报告位于同名 `artifacts/repository-runs/` 和 `artifacts/browser-runs/`；后者是定向单项，不是完整矩阵。服务正常退出；本阶段未重跑 HTTPS/灾备或生成新发布归档，旧归档只代表其原提交。
