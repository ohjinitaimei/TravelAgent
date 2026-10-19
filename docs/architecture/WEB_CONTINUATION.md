# Web 开发增量记录

2026-10-10。按用户补充，优先 Web，授权 Key 后续提供；本轮没有新增 uni-app，也没有改动 Flutter。

本文保留当日实施边界。2026-10-11 已完成后续 HelloAgents 单 Agent 需求草案、既有工具桥接及真实模型 Web 联调，最新状态见 [HelloAgents 需求草案记录](HELLOAGENTS_INTAKE.md) 与 [交付说明](TRAVEL_DELIVERY.md)。

## 本轮完成

- 编辑每天 POI 顺序与跨天移动，每天 1–4 站、全局 ID 去重；停留时间可逐站设为 10–360 分钟，仍调用既有调度器。
- 调整出发日期、每日时段、步行/驾车及预算；`budget` 省略保留，显式 null 清除。保存通过异步任务重新查询路线，保留父行程版本。被移除 POI 的旧费用和时长覆盖不会带入新版本。
- 每日实际站数、停留、交通分钟数和路线公里数汇总；编辑时明确显示地图仍为已保存版本。
- localStorage 仅保存用户表单、任务 ID 和行程 ID；刷新恢复状态查询与行程。导航 hash 保留页面。编辑草稿不持久化，刷新后恢复已保存版本。
- 共用客户端增加每请求超时、总轮询时限和进行中请求取消；断线时可点击重新查询状态。修复 Vue 数字输入自动转换造成的费用保存异常，显式 0 保留，空白保持未知。
- typed tools 三项白名单：search_pois/get_poi/get_route。REST 和规划任务使用同一 gateway；Function Calling 描述从 Pydantic 生成。MCP stdio 使用相同 gateway，不包含 Agent 循环或第二套算法。

`PlanRequest.stay_minutes_by_poi` 和 `EditRequest` 新字段为可选扩展，旧客户端可继续省略。API Schema 已重新导出并生成 TS；老 SQLite 行程反序列化时使用新字段默认值。

## 无 Key 运行与验证

正式服务沿用交付文档的 uvicorn:8000 与 Vite:5173。工作台可运行；数据获取失败会返回明确错误，不提供模拟成功结果。

```powershell
.\.venv\Scripts\python.exe tests\test_travel.py -v
npm run test:client
npm run build
```

MCP 为可选依赖；核心锁文件版本未变，新增依赖的安装及 pip check 已验证。固定 SDK 1.26.0 与它的官方版本文档一致，不升级既有核心栈。

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.mcp.txt -c backend\requirements.travel.lock.txt
.\.venv\Scripts\python.exe tests\test_mcp.py -v
# 在 backend 目录运行本地 stdio server：
..\.venv\Scripts\python.exe -m travel.mcp_server
```

协议测试真实创建 MCP 子进程，验证 initialize/list_tools/call_tool，缺配置或错误参数产生 `isError=true` 和统一错误 Schema；不消耗高德配额。MCP 功能可用不表示 HelloAgents 已启用。

浏览器编辑验证仅使用测试服务，以下需两个终端：

```powershell
.\.venv\Scripts\python.exe tests\browser_fixture_server.py --test-fixtures-only
```

```powershell
$env:TRAVEL_BACKEND_URL='http://127.0.0.1:8001'
npm run dev --workspace apps/web -- --port 5174
```

访问 `http://127.0.0.1:5174/#saved`。所有地点名为 TEST ONLY，fixture 仅为隔离测试输入。已通过浏览器将 fixture-b 从第 1 天移到第 2 天，fixture-a 设为 90 分钟与 88 元，改为 2026-10-15 出发、驾车、清除预算；保存后第 1 天结束 10:30，第 2 天 3 站，已知小计 88 元，上限未设置；刷新后保留当前预算页面及保存结果。测试截图 `artifacts/travel-web-editor-test.jpg` 被忽略提交。正式服务库未写入这些数据，测试服务验证后已关闭。

本轮结果：后端 13/13、客户端 4/4、MCP 1/1、Vue 类型检查/构建通过。原既有回归 49/49；高德成功调用和地图绘制留待 Key 配置后验证。

## HelloAgents 下一步

参考 [第十三章官方旅行规划实现](https://github.com/datawhalechina/hello-agents/blob/main/code/chapter13/helloagents-trip-planner/backend/app/agents/trip_planner_agent.py)。该示例含 LLM 计划与备用行程生成，本项目只参考交互和工具接入模式；保持用户要求的真实数据边界。

1. 在现有 `backend/agent/RouteCoordinator` 边界增加单 Agent 适配，核验 HelloAgents 包版本和依赖兼容性。保留当前结构化规划路径，避免默认安装框架影响现有服务。
2. 自然语言仅生成受 Schema 校验的表单草案/澄清问题，不生成 POI、票价、评论或路线时长。用户确认约束后才提交现有异步任务。
3. 将既有 ToolRegistry 的在线工具映射到 `TravelTools`。可选择 Function Calling 或 MCP 客户端，二者均走相同 Provider；限制调用次数与时间，不允许任意工具名或任意 URL。
4. Agent 事件写入已有任务事件存储，取消与超时通过既有工作进程控制；工具事实由来源标记追踪，输出由后端既有优化与调度决定。
5. 用隔离的模型/工具响应验证 Schema 错误和失败链路；提供 LLM 凭证后再做真实模型调用。多 Agent 和 Memory 后置。

MCP 实现依据 [Python SDK v1.26.0 官方文档](https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0)。新工具模块只是适配层，尚无第二个 Agent 系统。
