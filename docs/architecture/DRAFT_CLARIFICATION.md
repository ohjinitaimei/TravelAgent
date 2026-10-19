# Web 需求澄清闭环

2026-10-16。接续 [HelloAgents 需求草案阶段](HELLOAGENTS_INTAKE.md)，本轮只实现此前计划的第一项：补全、确认和修订同一份草案。移动端、高德授权和 MCP 客户端接通仍在后续阶段。

## 用户流程

1. 自然语言生成初始草案，缺少城市、地点关键词或日期时显示补全问题。
2. 展开“核对与补充字段”，填写缺失值或勾选已有候选值。输入变更会自动勾选该字段，也可显式选中全部已填写项。
3. 点击“保存补充与确认”，更新同一草案 ID、递增修订号。未选中的字段、已确认值和未处理要求保留。
4. 查看“用户填写 / 原文”来源与“已确认 / 待确认”标记，再点击“填入表单并核对”。没有明确输入的可选项继续保留为空，不会将规划表单默认值确认为用户需求。
5. 用户最后点击“开始规划”才创建规划任务；草案更新不会自动规划、生成地点或保存行程。

已确认值仍允许用户主动修改。清空并保存某项会移除其确认状态和字段依据；清空城市、关键词或日期会重新显示补全问题。预约等尚未支持的要求始终保留待处理提醒，不能通过确认字段将其标成已满足。

初始提取需要模型，后续结构化补充完全由用户输入驱动，不再调用模型或 Provider。后端继续使用既有 RouteCoordinator 复核必填信息，不增加 Agent 循环、推荐或路线算法。重新点击“创建新草案”是新需求操作；若生成失败，原草案仍保留。

## API 契约与存储

新增 `PATCH /api/v1/travel/drafts/{id}`，返回更新后的 Draft。短时校验和 SQLite 写入同步完成，无需另建长耗时任务。

```json
{
  "expected_revision": 1,
  "values": {"city": "杭州", "budget": 0},
  "confirm_fields": ["query"]
}
```

此例表示用户填写目的地和零元预算上限，确认已有 query 候选值；不是对真实费用或预算可行性的判断。

- `expected_revision` 必填，严格正整数；旧修订返回 409 `draft_revision_conflict`。
- `values` 只提交变更字段，省略保持不变，显式 null 清空。新增非空用户值视为明确确认，字段源为 `user_input`。
- `confirm_fields` 只接受十项白名单字段且不能重复；只能确认已存在的非空值，不改变原始模型依据或将其伪装为用户新输入。
- 合并后再次按 DraftValues 校验，包括范围与每日起止时段；无效请求不写入，不静默裁剪。
- 新增 Draft 元数据：`revision`、`updated_at`、`confirmed_fields`、`field_sources`、`clarifications`。修订记录包括实际变更值和本轮确认项；原始输入和创建时间保留。
- 已有 Draft JSON 缺少这些字段时使用默认值（revision=1、空确认列表），无需更改数据库表结构。

Store 在写入时再次检查修订，并使用原始 JSON 条件更新。较晚完成的旧请求不能覆盖已保存的新值。Web 遇到冲突会保留本次未保存输入并禁用再次提交；用户明确点击“加载最新草案（替换未保存补充）”后，重新核对再提交，不自动覆盖或重试。

OpenAPI 已重新导出，TypeScript 类型由同一 Schema 生成。共享客户端新增 `clarifyDraft(id, request)`，使用 PATCH；后续 uni-app 可复用同一方法。刷新仍按草案 ID 重新获取后端最新修订；仅保存用户规划表单和 ID，不在浏览器缓存模型输出。

## 实际验证与边界

| 检查 | 2026-10-16 结果 |
| --- | --- |
| `tests/test_draft_clarification.py` | 4/4：多轮同 ID、确认保留、零值、显式清空、旧数据兼容、持久化重开、错误请求、合并时段、409 和存储竞争写入；断言无模型、Provider、新任务或行程 |
| `tests/test_agent_intake.py` | 6/6：已有 HelloAgents 边界回归 |
| `tests/test_travel.py` | 13/13：已有规划、编辑、Provider 与任务回归 |
| `npm run test:client` | 7/7：HTTP 缺配置/禁用路径、取消/期限、表单、费用、草案、PATCH 选中字段及 Vue 数字值 |
| `npm run build` / `pip check` | 通过；核心依赖和锁定版本未修改 |
| 真实模型 + Web 代理 + API | 成功：初始提取一次模型调用；两轮 PATCH 同一 ID 从第 1 到第 3 版，城市/关键词确认保留、缺失问题清除、预约提醒保留，旧版提交 409，行程数量不变 |
| 本轮浏览器界面操作 | 未完成：Computer Use 无法可靠识别当前浏览器 URL，已停止界面操作；没有把接口验证当成浏览器验证 |
| 高德成功路线 / App 真机 | 本轮未执行，授权和移动端继续后置 |

真实 HTTP 证据：忽略提交的 `artifacts/live-clarification-verification.json`。该记录含初始草案、两轮结果、任务/事件、冲突响应和保存行程数量，不包含凭证。没有写入测试 POI、路线或价格。

可复现检查：

```powershell
.\.venv\Scripts\python.exe tests\test_draft_clarification.py -v
.\.venv\Scripts\python.exe tests\test_agent_intake.py -v
.\.venv\Scripts\python.exe tests\test_travel.py -v
# 负路径客户端检查要求目标禁用模型解析，且没有高德 Key：
$env:TRAVEL_TEST_URL='http://127.0.0.1:18000/api/v1/travel'
npm run test:client
npm run build
```

本轮 8000 端口绑定被 Windows 拒绝，底层 socket bind 可复现；检查发现该端口存在另一进程的 CLOSE_WAIT 连接，18000 可正常绑定。未终止该进程或修改系统设置。当前本地服务用 18000，Web 保持 5173，开发代理指向 18000；项目默认端口配置仍为 8000。

```powershell
# 后端：复用已有模型配置，不改 .env；无高德 Key 也可进行需求整理
$env:TRAVEL_AGENT_ENABLED='1'
$env:LLM_INTENT_DISABLE_LLM='0'
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 18000
# 另一个终端：Web
$env:TRAVEL_BACKEND_URL='http://127.0.0.1:18000'
npm run dev
```

可选真实联调脚本（初始提取会调用模型一次；后续仅本地 PATCH，不请求高德）：

```powershell
.\.venv\Scripts\python.exe scripts\verify_live_clarification.py --allow-model-call --reference-date 2026-10-16 --date 2026-10-20
```

## 本轮变更与下一步

新增 `backend/travel/drafts.py`、`tests/test_draft_clarification.py`、`scripts/verify_live_clarification.py` 和本文。

修改 `schemas.py` / `api.py` / `store.py`、Web `App.vue` / `RequestAssistant.vue` / `draft.ts`、共享客户端和生成 Schema、客户端测试以及入口交付文档。未修改 Flutter、核心依赖、原有业务算法或模型凭证。

接下来按原计划完善任务失败重试、断线恢复及草案/行程状态提示，并补做本轮浏览器交互验收。之后验证真实 MCP 客户端连接；高德 Key 到位再验证真实多日路线与编辑成功链路。
