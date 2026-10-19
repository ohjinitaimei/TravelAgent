# 高德 JS 安全密钥代理

日期：2026-10-20。Web 现在使用同源 FastAPI 代理；JS 安全密钥只在后端配置。实现依据为 [高德官方安全密钥说明](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode)，采用 SDK 加载前设置 `serviceHost`、服务器补入 `jscode` 的方式。

## 配置与运行

后端 `backend/.env`：

```dotenv
# 原有 POI/路线授权，继续只供后端 Provider 使用
AMAP_WEB_KEY=
# 独立的 JS API Key，须与前端使用的 JS Key 一致
AMAP_JS_KEY=
AMAP_JS_SECURITY_CODE=
TRAVEL_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

前端 `apps/web/.env.local`：

```dotenv
VITE_AMAP_JS_KEY=
VITE_API_BASE_URL=/api/v1/travel
```

已有配置需把原前端 `VITE_AMAP_SECURITY_CODE` 的值移到后端 `AMAP_JS_SECURITY_CODE`，并删除前端变量；把前端 JS Key 同时填入后端 `AMAP_JS_KEY`。不要使用后端 Web 服务 Key 替代 JS Key。本地迁移已完成，配置文件均被 Git 排除。

按根 README 分别启动 uvicorn 和 `npm run dev`；两端均需重启。Vite 现有 `/api` 代理已覆盖地图路径，不增加另一套服务。更改 Web 端口时，后端 `TRAVEL_CORS_ORIGINS` 须包含准确的访问来源。JS Key 仍是浏览器公开标识，域名白名单按高德控制台配置。

正式部署将构建后的 Web 与 `/api/` 反向代理放在同一 HTTPS 域名，完整保留 `/api/v1/travel/_AMapService/` 路径；沿用账号模式、Secure Cookie 和明确的允许来源。该代理与 `/api/v1/travel` 的 Cookie Path 一致，SDK 的同源请求可携带 HttpOnly 会话。代理不要求用户放宽 Cookie Path，也不向浏览器返回安全密钥。公网域名、HTTPS 和网关仍须在实际部署环境验收。

## 数据流与访问边界

```text
浏览器公开 JS Key → 高德 JS SDK
SDK.serviceHost → 同源 /api/v1/travel/_AMapService/{固定路径}
  → 现有身份校验 → 来源与参数校验 → 现有用户/全局工具配额与并发槽
  → 服务端追加 JS 安全密钥 → 固定高德 HTTPS 服务
  → 有界读取、类型和密钥回显检查 → SDK

POI 搜索、详情、路线与规划 → 原有 TravelTools → Provider/MCP → 既有算法
```

允许的 SDK 路径只有两项：

| 路径 | 固定目标 | 用途 |
| --- | --- | --- |
| `v3/log/init` | `https://restapi.amap.com/v3/log/init` | 真实 SDK 观察到的初始化请求 |
| `v4/map/styles` | `https://webapi.amap.com/v4/map/styles` | 官方代理文档的样式接口；本轮未启用自定义样式 |

其他路径（含 POI、方向规划、任意 URL）、非 GET 方法、其他 JS Key、重复参数、客户端 `jscode`、非法 JSONP 回调和过长查询均不转发。来源校验在本地模式也生效；账号模式还要求有效会话，退出后返回 401。缺配置返回 503，不切回前端明文方式。

代理不转发用户 Cookie、Authorization、Origin 或自选 Host，只向上游传递校验后的来源根地址作为 Referer；不转发 Set-Cookie、Location 或上游跨域头，不跟随重定向、不自动重试、不读取系统代理设置。响应类型受限，解码后最多 2 MiB，每次总期限 12 秒，连接期限 5 秒、读取期限 10 秒。共享现有工具并发与持久化配额，默认每用户 60 次/分钟、全局 180 次/分钟、4 个活动槽；拒绝返回 429/Retry-After。查询任务状态、取消与登录状态仍可用。

响应设置 `no-store` 与 `nosniff`。错误返回固定错误码和中文说明；HTTPX INFO 日志中的 JS 凭证会脱敏，响应若回显安全密钥则拒绝。运维不得另行记录上游完整查询参数或响应正文。SDK、底图和瓦片仍会访问高德官方域名，此代理覆盖 SDK 的 serviceHost 接口；它没有把所有地图资源搬到后端。

高德初始化可能把 JSONP 标记为 JSON 或二进制 MIME。代理只在回调名匹配、包裹合法且内部内容可解析为 JSON 时转换为 `application/javascript`，让 WebKit 在保留 nosniff 的条件下执行。无回调的 JSON 保持原类型；不接受额外脚本、错误回调、非法编码或任意 JavaScript 表达式。新增回归与三引擎最终复验见 [BROWSER_ACCEPTANCE.md](BROWSER_ACCEPTANCE.md)，以下 128 项记录属于代理接入阶段的历史结果。

## 验证结果

- 128 项无密钥自动检查全部通过：Python 91（新增代理 12）、TypeScript 17、Chromium 20。代理检查使用明确的 TEST ONLY MockTransport，覆盖访问拒绝、固定目标和凭证注入、会话/退出、来源、参数、重定向/错误/类型/大小、密钥回显、日志脱敏、限流/并发、取消释放和客户端关闭，不访问真实高德。
- Web 类型检查和构建通过；在实际本地 JS Key 配置下再次构建，确认后端 Web Key 和 JS 安全密钥均未进入前端构建物。OpenAPI 与生成 TypeScript 无差异；SDK 资源路由不进入业务 Schema，旧客户端与移动端契约保持兼容。
- 真实 Chromium 本地模式通过 25 项检查，观察到 3 次同源初始化请求，全部 HTTP 200；高德资源 145 个响应、132 个瓦片或地图资源响应，无 HTTP 失败或已知授权错误。SDK 配置中没有 `securityJsCode`，浏览器请求和代理响应不含安全密钥。
- 真实 Chromium 账号模式通过 28 项检查：在真实上海保存行程的独立数据库副本中创建一次性账号并显式迁移副本记录，使用登录页面建立 HttpOnly Cookie；真实初始化请求 3 次均成功，地图双向定位、编辑预览、放弃还原与刷新通过。退出后同一路径返回 401。高德资源 140 个响应、123 个瓦片或地图资源响应，无 HTTP 失败或已知授权错误。
- 真实流程没有重查 POI/路线，没有生成虚构业务数据，也未修改个人业务库。账号凭证只用于独立副本，不构成部署默认账号。未推送 GitHub。

上述真实检查分别记录在被忽略的 `artifacts/live-map-20261019T155814Z/`（本地）和 `artifacts/live-map-20261019T160324Z/`（账号）中，含脱敏汇总和截图，不包含在克隆内容里。较早的代理试跑只完成地图交互，未要求代理返回成功；它暴露了 SDK 使用 `v3/log/init`，实现随后收紧为该初始化路径及官方样式路径，最终检查要求所有初始化响应成功。此处时间戳使用 UTC，账号检查对应北京时间 10 月 20 日。

复现自动检查使用根 README 的两条编排命令，或单独运行 `python tests/test_map_proxy.py -v`。使用自己的授权验证真实地图时，检查 Network 中同源初始化请求成功、页面可切日/编辑/刷新；账号模式退出后检查代理拒绝请求。不要导出含凭证的 HAR 或完整请求 URL。

三引擎与有界延迟/断网验收已完成，下一阶段补充 Safari 真机、持续弱网及部署域名验收，再扩展推荐质量样本；新增 SDK 功能若需要其他接口，须先核实用途并显式扩展白名单，不开放通用 Web 服务代理。
