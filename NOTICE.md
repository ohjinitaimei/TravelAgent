# 来源与发布范围

本仓库包含 TravelAgent 旅行规划工作台、统一后端及相关验证脚本。功能范围与验收记录见根 README。

- 既有工程来自当前本地 MT/Muse 代码库，原配置远程为 <https://github.com/AutumnCs/MT>。本次保留其代码、注释和原作者标识；原本地 Git 历史和文件不会被删除或重写。新仓库以整理后的独立初始提交开始。
- 旅行助手架构参考 Datawhale [Hello-Agents](https://github.com/datawhalechina/hello-agents)；可选运行依赖使用 [HelloAgents](https://github.com/jjyaoao/HelloAgents)，版本及依赖记录在锁文件中。本仓库未复制其完整源码。
- Vue、Vite、FastAPI、Pydantic、MCP SDK、地图 SDK 等依赖适用各自的许可；具体依赖以 package-lock 和 requirements 锁文件为准。
- 高德数据须由使用者自行取得合法授权后调用，不随源码提供。旧 POI 数据、同步导出、运行记录、用户行程、密钥和本地验证产物不属于本次发布内容。
- `tests/` 中的测试回复和 FixtureProvider 是隔离测试输入，不能作为生产业务数据，也不能被描述成真实路线联调成果。

当前为私有仓库，未指定新的开源许可证，也不对原始代码、素材或第三方数据作额外授权承诺。以后如需公开或选择开源许可证，应先确认相关权利与来源。
