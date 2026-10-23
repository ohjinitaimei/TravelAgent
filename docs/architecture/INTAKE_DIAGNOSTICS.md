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
