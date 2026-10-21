# 共享 API 契约

唯一事实源：`backend/travel/schemas.py` + `api.py`。类型通过 OpenAPI 生成，前端不手工复制后端模型。

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
npm run schema:generate
```

后端改变后提交 `openapi.json` 与 `schema.d.ts`，执行 `npm run build` 检查消费者。`client.ts` 是与平台无关的契约客户端；Web 使用 fetch，后续 uni-app 提供 uni.request transport。SSE 事件与轮询 Event 模型相同，事件 ID 可用于续读。

需求澄清使用 `clarifyDraft(id, {expected_revision, values, confirm_fields})`，对应 PATCH `/drafts/{id}`。省略字段保持不变，null 清空；409 表示草案已被更新，需重新获取并核对，禁止自动重试覆盖。详见 [需求澄清记录](../../docs/architecture/DRAFT_CLARIFICATION.md)。

时间不可行任务仍为 `failed`，`error.code=time_constraint_exceeded`，可选 `error.time_constraints` 提供原分日方案的时段及超时日分钟明细。字段由后端生成并通过同一任务查询/SSE 传递，历史记录可为空；客户端不能据此自行重算交通或承诺调整后可行。修改条件使用 `create` / `adjust` 显式提交新任务，原条件 `retry` 仍受 `retry_available` 限制。参见 [时间约束调整](../../docs/architecture/TIME_CONSTRAINTS.md)。
