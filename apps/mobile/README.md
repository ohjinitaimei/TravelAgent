# Mobile 接入预留

本仓库没有 uni-app；用户已将本阶段范围改为先完成 Web。现有 Flutter 保留在根目录 `lib/`、`android/`、`windows/`，旧接口保持兼容。这里不生成另一套 Agent 或未经验证的 App 工程。

后续取得 uni-app 源码后接入 `packages/api-schema` 类型和 `/api/v1/travel`：

1. `uni.request` 提交 `POST /tasks`，接受 202。
2. 每 1–2 秒请求 `GET /tasks/{id}` 与 `GET /tasks/{id}/events?after={cursor}`。
3. 终态停止轮询；succeeded 后获取 `GET /itineraries/{id}`。
4. 页面卸载时停止定时器；用户取消时调用 `POST /tasks/{id}/cancel`。
5. 错误读取 `error.code/message/retryable`，不得创建本地模拟行程。

Web 与 App 所有 Provider、Agent、推荐、路径和调度都在同一后端。真机使用局域网后端 URL，不使用设备自己的 localhost；发布前配置 HTTPS、鉴权、用户隔离及平台合法域名。
