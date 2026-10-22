# 共享 API 契约

唯一事实源：`backend/travel/schemas.py` + `api.py`。类型通过 OpenAPI 生成，前端不手工复制后端模型。

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
npm run schema:generate
```

后端改变后提交 `openapi.json` 与 `schema.d.ts`，执行 `npm run build` 检查消费者。`client.ts` 是与平台无关的契约客户端；Web 使用 fetch，后续 uni-app 提供 uni.request transport。SSE 事件与轮询 Event 模型相同，事件 ID 可用于续读。

需求澄清使用 `clarifyDraft(id, {expected_revision, values, confirm_fields})`，对应 PATCH `/drafts/{id}`。省略字段保持不变，null 清空；409 表示草案已被更新，需重新获取并核对，禁止自动重试覆盖。详见 [需求澄清记录](../../docs/architecture/DRAFT_CLARIFICATION.md)。

`DraftValues` 支持可空 `day_schedules`（1–3 项，逐项时段/停留可空）、严格交通上限，以及仅为用户文字的 `origin_hint` / `destination_hint`。已知天数时日程数量须相等，补充完整替换数组；未说明子项不补默认。hint 不进入规划请求或转换为 ID，需真实搜索选择及显式核对。历史草案缺字段兼容，20 个 travel 路径不变。见 [需求确认与 Web 连续使用](../../docs/architecture/REQUIREMENTS_WORKFLOW.md)。

时间不可行任务仍为 `failed`，`error.code=time_constraint_exceeded`，可选 `error.time_constraints` 提供原分日方案的时段及超时日分钟明细。字段由后端生成并通过同一任务查询/SSE 传递，历史记录可为空；客户端不能据此自行重算交通或承诺调整后可行。修改条件使用 `create` / `adjust` 显式提交新任务，原条件 `retry` 仍受 `retry_available` 限制。参见 [时间约束调整](../../docs/architecture/TIME_CONSTRAINTS.md)。

新规划的 `compare_poi_alternatives?: boolean` 缺省 false，严格布尔；省略与 false 幂等兼容。开启可比较同次真实搜索的有限候选，不新增必填字段。`Itinerary.planning_comparison` 可空，包含同任务基线/采用指标及事实、候选和查询范围；基线可能不可行，只作对照。新摘要存在时优先展示，不再叠加旧分日收益。编辑继承开关也不会自动换点，`EditRequest` 不增加比较开关。评分仍是排序参考，缺失不补齐，也不是用户未设置的硬下限。完整语义见 [地点与路线对比](../../docs/architecture/POI_COMPARISON.md)。
