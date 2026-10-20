# 地图联动与行程编辑验收

日期：2026-10-19。此轮在本地完成 Web 交互增量，沿用同一个 FastAPI 后端、任务服务和真实数据层。API 契约、核心依赖及 Flutter 源码未变。

## 页面行为

- 时间轴编号按钮定位地图中的对应地点，高亮该标记及与其相邻的已保存道路折线；不会请求 POI 详情或重新调用路线工具。
- 点击地图编号或“地图地点”列表项，会选中、滚动并聚焦时间轴对应站点。切换日期或行程时清除选择；列表可通过键盘操作，地图 SDK 不可用时仍可使用。
- 编辑时，地图按当前调整后的每日地点与顺序显示编号。已保存交通折线、距离、时间和分日优化比较暂不展示，保存成功后显示后端新版本的真实结果。
- “本次编辑改动”逐项比较位置、新增/移除、停留、费用、日期、每日时段、交通方式、预算和排序选项。费用未知与显式 0 分开处理，数字与等值数字字符串不会造成误报。改回原值后不再提示未保存。
- 页面顶部展示未保存改动数量；切换探索、保存和预算页面会保留本次编辑，可点击“返回行程编辑”继续。
- 退出编辑、打开保存行程、新建规划/重试或主动退出登录时，若有改动，先显示放弃确认。初始焦点在“继续编辑”，Escape 保留编辑并返回原按钮；确认后才执行目标操作。
- 浏览器刷新或离开页面使用原生 beforeunload 提示；是否显示由浏览器决定。用户取消刷新时保留编辑。2026-10-20 增加按账号隔离的本机草稿，刷新后可显式核对并恢复；详细流程与存储边界见 [EDIT_DRAFT_RECOVERY.md](EDIT_DRAFT_RECOVERY.md)。
- 编辑保存被拒绝或任务失败时保留编辑内容，用户可修正后继续保存。成功重算创建子版本，原行程可读。连接恢复时不以旧保存版本覆盖当前编辑。
- 会话失效或其他标签页切换账号仍立即关闭旧工作空间；草稿只可在原账号下恢复，主动退出会清除。

## 数据流与文件

```text
用户选择站点 → App.selectedStopId → RouteMap 标记/相邻道路高亮
地图选择 → App.selectStop → 时间轴滚动、键盘焦点
用户编辑 → editSnapshot / editChanges → 差异表与离开保护
当前编辑分日 → RouteMap.preview → 仅地点编号
保存 → 现有 adjust API → 异步任务 → Provider/MCP 查询 → 原有算法 → 新行程版本
```

`editor.ts` 只比较用户输入，不计算交通或补充 POI 事实。没有增加浏览器端 Agent、业务优化算法或模拟数据入口。

| 文件 | 用途 |
| --- | --- |
| `apps/web/src/App.vue` | 选择状态、编辑生命周期、离开保护、地图预览 |
| `apps/web/src/editor.ts` | 可比较的编辑快照与差异 |
| `apps/web/src/components/RouteMap.vue` | SDK 标记、道路高亮、可访问地点列表 |
| `apps/web/src/components/EditComparison.vue` | 修改前后对照 |
| `apps/web/src/components/DiscardChangesDialog.vue` | 原生模态对话框、焦点和 Escape |
| `apps/web/src/style.css` | 选择态及未保存提示样式 |
| `tests/client.lifecycle.test.ts` | 快照、跨天/新增/移除、未知/零值、约束和还原 |
| `tests/browser/workspace.spec.ts` | 双向选择、刷新取消、放弃/保留、保存拒绝和新版本 |
| `tests/browser/auth.spec.ts` | 主动退出登录前保护及取消退出 |

## 验证结果

完整无密钥检查通过 116 项：Python 79、TypeScript 17、Chromium 20（本地模式 13、账号模式 7）。Web 类型检查和 Vite 构建通过；重新导出 OpenAPI 和 TypeScript 后无契约差异。复现命令见 [ACCEPTANCE.md](../ACCEPTANCE.md)。隔离测试输入仍只在 tests 中使用。

另用授权高德 JS SDK 和此前真实上海行程的独立数据库副本完成 23 项浏览器检查：真实底图、编号、时间轴、原优化比较、双向选择、跨天重置、编辑顺序/差异/地点预览、动画结束后标记位于地图内、对话框焦点/Escape、放弃还原和刷新恢复。观察到 78 个高德相关响应，其中 63 个瓦片或地图资源响应成功，HTTP 失败与已知授权错误均为 0。选择与放弃流程的 POI 详情请求和业务 POST 均为 0；没有重新调用 POI/路线接口，没有改动个人业务库。

本地证据在被 Git 排除的 `artifacts/live-map-20261019T115658Z/`，包含 `report.json`、`browser.json`、`day-one-map.png`、`editing-preview.png`、`discard-dialog.png`、`day-two-map.png`；克隆不会附带这些授权记录。截图已目视检查。首次地图点击检查因先居中第一站、另一站移出视野而失败；复查先恢复整日视野后使用真实鼠标点击通过。自动测试中取消刷新没有新的 load 事件，已改为触发刷新、取消原生提示并直接断言页面内容，避免等待不存在的加载。

上述 23 项为地图编辑阶段的历史记录。随后已完成三引擎与安全密钥代理实测，见 [BROWSER_ACCEPTANCE.md](BROWSER_ACCEPTANCE.md)。移动端真机和正式域名部署仍按 [后续计划](../RELEASE_STATUS.md) 分步验收。凭证、构建物、截图、运行库和日志均不进入 Git。
