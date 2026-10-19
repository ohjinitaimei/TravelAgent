# TravelAgent 架构审计与本阶段设计

审计日期：2026-10-10。依据当前代码，非历史路线图。用户补充：先实现 Web，uni-app 后续增加。

## 现有系统

| 范围 | 实际实现 | 结论 |
| --- | --- | --- |
| 客户端 | `pubspec.yaml`、`lib/main.dart`、`lib/pages/`，Flutter/Dart，Android/Windows | 没有 uni-app、Vue、Vite 工程。保留原目录，不搬迁或重写 |
| 后端 | `backend/main.py`，FastAPI/Pydantic 2/httpx/uvicorn | 已有 `/api/route/generate`、`modify`、POST SSE，地图、意图、context、eval API |
| 推荐 | `candidate_builder`、`poi_retriever`、`semantic_retriever`、`ranker_engine` | 本地 JSON 召回，多路检索、约束筛选、打分，未直接在线召回真实 POI |
| 优化与调度 | `route_planner.py` | 最近邻排序、路线变体、类别约束、时间安排；已有 `planning_distance_matrix` 注入点，缺失时使用距离/速度估算 |
| Agent | `agent/coordinator.py`、`planning.py`、`tool_layer.py`、`intent_repair.py` | 自研受控执行计划和同步工具注册，不是 HelloAgents，也不是 MCP 协议服务器 |
| LLM | `core/llm_intent_client.py` | DashScope/OpenAI 兼容 HTTP，意图抽取/修复，局部快速解析门控；未发现 HelloAgents 依赖 |
| 真实数据 | `services/amap_client.py`、`tianditu_client.py`、`tools/amap_poi_sync.py` | 高德地理编码/搜索/详情客户端、天地图服务已有；高德同步脚本只补部分事实，不证明原价格/评论的真实性 |
| 模拟/估算 | `pois.json`、`tools/expand_local_pois.py`、`generate_mock_ugc.py`、`route_tools._local_segment`、`map_service` | 手工扩展记录、模板评论、交通估算；不得进入新的真实数据业务入口 |
| Flutter 降级 | `route_api_service.dart` | 存在 mock 代码，但 `enableMockFallback=false`，默认关闭 |
| 依赖/启动 | `backend/requirements.txt`、`flutter.ps1`、README | Python 范围约束，无 Python 锁；Flutter SDK 脚本固定旧 G 盘；无 Web 构建和生产部署配置 |
| 长任务 | 当前 async 路由内部直接调用同步规划 | 可能阻塞事件循环；旧 SSE 部分进度在规划完成后发出，缺少真实任务取消/超时 |

## 目标目录与边界

```text
apps/web/                 Vue3 + TypeScript + Vite PC 工作台
apps/mobile/              后续 uni-app 接入说明，当前不创建另一套 App
packages/api-schema/      FastAPI OpenAPI 快照和生成的 TypeScript 类型
backend/travel/           统一旅行 API、真实 Provider、任务管理、SQLite 保存
backend/services/         已有推荐/优化/调度函数，继续复用
backend/agent/            已有后端 Agent，后续适配 HelloAgents
lib/ android/ windows/    保留现有 Flutter
docs/architecture/        审计、契约、验证与交付说明
```

先新增 `/api/v1/travel` 契约，再接 Provider 与隔离的异步任务，最后实现 Web。不升级已有核心依赖。旧算法只增加可选的真实数据参数，默认行为保持兼容。新业务不得加载 `pois.json` 或模拟 UGC，不得调用旧地图降级路径。

## 契约与数据流

创建任务 → 后端隔离工作进程 → 高德搜索 → 现有推荐函数（排除缺失事实的评分项）→ 高德有向交通矩阵 → 现有排序函数 → 现有调度函数 → 约束与未知项 → SQLite 行程。Web SSE 与轮询读取同一事件/状态；未来 App 轮询同一 API。取消/超时终止工作进程，终态不再写入行程。

PC 页面：规划表单、任务事件、左侧多日时间轴/右侧大地图、POI 搜索详情、编辑和重新调度、预算与未知约束、已保存行程。地图只画 Provider 返回的路网折线。无 Key/权限不足/路线缺失，返回结构化错误或显示空状态，不构造演示行程。

本阶段本地单服务实例；任务与行程持久化，不宣称具备多实例队列、登录鉴权或完整商业旅行约束。后续生产部署需账号隔离、鉴权、限流、共享队列、密钥配置和授权审查。

## 参考依据

- [Hello-Agents 第十三章](https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter13/%E7%AC%AC%E5%8D%81%E4%B8%89%E7%AB%A0%20%E6%99%BA%E8%83%BD%E6%97%85%E8%A1%8C%E5%8A%A9%E6%89%8B.md)：参考表单、地图、行程编辑和分层；不复制其示例假数据，也不在前端加入 Agent。
- [高德 POI](https://lbs.amap.com/api/webservice/guide/api-advanced/search)、[路径规划](https://lbs.amap.com/api/webservice/guide/api/direction)：服务端授权 API；字段缺失保留 null。
- [OpenAPI TypeScript](https://github.com/openapi-ts/openapi-typescript)：从后端模式生成共享类型。
