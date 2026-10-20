# 发布包与定时备份

日期：2026-10-20。本轮在本地完成打包、归档启动与备份轮换/恢复演练；没有上传 GitHub、安装定时器或操作个人业务库。生产业务仍通过同一后端、Provider/MCP 和既有算法运行。

## 发布包

`scripts/package_release.py` 从当前 `PUBLISH_MANIFEST.json` 收录源码，再单列已经构建的 Web 文件。它不复制 Git 历史、环境配置、依赖目录、数据库、备份或运行记录。空值 `.env.example` 保留；环境变量及指定凭证文件中的已配置后端密钥须不出现在源码/构建中，浏览器 JS Key 仍按公开构建参数处理。

归档布局：

```text
TravelAgent.zip
  RELEASE.json                  Git commit、工作区是否有修改、逐文件大小/SHA-256
  source/PUBLISH_MANIFEST.json   原源码清单
  source/...                    受控源码、锁文件、文档与模板
  web/index.html                已构建页面
  web/assets/...                已构建静态资源
SHA256SUMS                      ZIP 文件的 SHA-256
```

源码按现有清单将 UTF-8 CRLF 归一化为 LF；二进制与 Web 构建保持原始字节。固定 ZIP 时间、文件顺序和权限，同一 commit、源码、工作区状态、构建及 Python 压缩环境下重复打包具有相同哈希。包内标记脏工作区，不能把开发快照误认成已提交版本；正式交付使用干净提交。

```powershell
# 先完成依赖安装、当前检查、生产构建和源码清单检查。
.\.venv\Scripts\python.exe scripts/verify_repository.py
.\.venv\Scripts\python.exe scripts/update_publish_manifest.py --check
# 输出目录必须不存在；仓库内只允许输出到已忽略的 artifacts/ 或 .tmp/。
.\.venv\Scripts\python.exe scripts/package_release.py build --output artifacts/releases/自己的版本号
.\.venv\Scripts\python.exe scripts/package_release.py verify artifacts/releases/自己的版本号/TravelAgent.zip
# 只对自己构建且来源可信的归档执行代码启动检查。
.\.venv\Scripts\python.exe scripts/verify_release_runtime.py artifacts/releases/自己的版本号/TravelAgent.zip
```

独立校验器拒绝路径穿越、绝对路径、Windows 驱动器路径、重复/大小写冲突条目、符号链接、加密条目、超限大小、额外文件、清单不一致和内容损坏；不会将未校验文件解压到安装目录。源码和 Web 都禁止携带运行数据。ZIP 与清单哈希用于完整性检查，不是签名，不能独立证明来源；接收包时还应通过可信渠道核对 `SHA256SUMS` 或发布者提供的哈希。

`verify_release_runtime.py` 先校验同一份归档字节，再仅解压到本次 `.tmp/` 目录，以当前 Python 环境启动包内后端。使用空白测试库、清空真实凭证，检查 live、ready、匿名行程 401、账号初始化状态 4 项；不是原开发目录的导入结果。结束后关闭连接并清理本次目录，不安装依赖或系统服务。该脚本会执行包内程序，只适用于来源可信的自有发布包。

安装时将 `source/` 放到 `/opt/travelagent`，将 `web/` 的内容放到 `/opt/travelagent/apps/web/dist`，配置和数据库按 [DEPLOYMENT.md](DEPLOYMENT.md) 单独保存。包不包含 Python/Node 依赖，需按锁文件安装。当前本地验收产物使用无真实凭证构建；如需浏览器地图，应先按部署文档使用自己的 `VITE_AMAP_JS_KEY` 重新构建再打包，安全密钥只配置在后端。不要通过编辑 ZIP 内文件替换配置，否则清单会失效。

## 定时备份与保留

`backend/travel/backup_schedule.py` 复用现有 `travel.backup` 的在线 WAL 快照、完整性/归属检查，不复制主库代替备份，不创建另一套数据服务。

```powershell
# 在 backend/ 中运行，必须显式指定实际数据库和独立备份根目录。
python -m travel.backup_schedule --db /实际路径/travel.sqlite3 --root /独立路径/backups --keep 7
# 首条只创建/校验并报告超过保留份数的条目；确认策略后才显式清理。
python -m travel.backup_schedule --db /实际路径/travel.sqlite3 --root /独立路径/backups --keep 7 --prune
```

每次使用 UTC 时间与随机后缀创建新目录，包含 `snapshot.sqlite3`、原 `manifest.json` 和本工具的 `managed.json`。先完成新快照及校验，再考虑保留清理。默认保留份数 7，可设 1–365；表示份数，不表示天数。若主机时钟回拨，本轮成功的新快照仍必须保留，其余按目录时间排序。

只会清理当前备份根目录的直接子目录，且须同时满足生成名称、管理标记、恰好三个已知普通文件和完整备份校验；清理前再次校验。手工目录、损坏/未完成快照、有额外文件或符号链接的目录都跳过，不占用有效快照的保留份数。清理不递归遍历任意目录，不自动处理被跳过的文件。报告输出创建名称及数量，不输出账号、Token 或行程记录。

同一根目录使用 `.backup.lock` 独占锁，重复执行直接失败。进程崩溃后的锁不按时间自动抢占；管理员确认没有备份运行后才可处理该锁。失败不会覆盖源库或旧快照；新快照失败时不开始清理。若清理中途因权限/文件变化失败，命令返回失败，已经验证的新快照仍保留；管理员检查残留条目，工具不扩大删除范围。

备份目录在 POSIX 上要求 0700，新目录按该权限创建；Windows 需管理员为目标目录设置专用 ACL。目录保护不是加密，快照包含用户记录和密码/会话散列，不得放进 Web root、源码发布包或公共 Git 仓库。此阶段没有实现远程上传、异地副本或加密密钥管理。

## Linux 定时模板

新增 `deploy/travelagent-backup.service` 和 `.timer`，与前一轮的单 API 服务配套。模板使用 `travelagent` 账号，显式库路径 `/var/lib/travelagent/travel.sqlite3`、备份根 `/var/backups/travelagent`、保留 7 份且启用 `--prune`；安装前按实际容量和策略审阅该参数。仅备份目录允许写入，业务库目录在该服务内只读。

```bash
sudo install -d -m 0700 -o travelagent -g travelagent /var/backups/travelagent
sudo install -m 0644 deploy/travelagent-backup.service /etc/systemd/system/travelagent-backup.service
sudo install -m 0644 deploy/travelagent-backup.timer /etc/systemd/system/travelagent-backup.timer
sudo systemctl daemon-reload
# 先执行一次并检查成功及日志，再启用计时器。
sudo systemctl start travelagent-backup.service
sudo systemctl status travelagent-backup.service
sudo journalctl -u travelagent-backup.service --no-pager
sudo systemctl enable --now travelagent-backup.timer
sudo systemctl list-timers travelagent-backup.timer
```

按主机时区每天 03:30 调度，再随机延迟最多 15 分钟；`Persistent=true` 可在停机后补触发一次，并非逐次补齐所有遗漏快照。行为依据 [systemd.timer 官方手册](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)。停用用 `systemctl disable --now travelagent-backup.timer`，不会删除备份。服务失败时通过 systemd 状态/日志排查，本阶段未接入外部告警。

Windows 本轮只执行 Python 命令与独立目录演练，没有验证 Linux 的服务权限、定时实际触发或只读 WAL 场景；目标主机须先手动执行服务确认，再启用 timer。数据库恢复继续使用原工具写入全新路径，撤销旧会话、中断任务显式重试，步骤见 [OPERATIONS.md](OPERATIONS.md)。

## 验证与文件

新增测试：备份轮换 8 项、发布打包 6 项。覆盖默认不删除/显式保留、失败不清理、手工/损坏/额外文件保留、独占锁、源库隔离、CLI、恢复不覆盖、时钟回拨；以及重复打包哈希一致、LF 归一化、非发布文件排除、源码变化、凭证混入、原输出保留、内容损坏与异常路径/条目拒绝。原有 6 项备份测试继续验证在线 WAL、双账号归属、会话撤销与恢复。

本轮完整回归的首轮遇电脑休眠/时钟校正，原 MCP 超时测试失效：系统记录睡眠约 85 分钟，测试组异常耗时 5162 秒。唤醒后同一用例按原限制于 13 秒内通过，再重新运行完整检查；没有增加超时或跳过用例。早期一处测试 SQLite 连接未关闭导致 Windows 清理失败，已显式关闭，生产备份逻辑不受该测试修正影响。

新增：`backend/travel/backup_schedule.py`、两个 systemd 模板、`scripts/package_release.py`、`scripts/verify_release_runtime.py`、两个回归文件及本文。修改：仓库检查入口、CI 的清单后打包/归档启动步骤、README/验收/状态/运维/部署文档和源码清单。CI 文件已准备，本轮未上传或触发 GitHub Actions。

完整检查集增至 Python 115、共享客户端 23、浏览器 42 个场景 × 3 引擎，共 180 个逻辑用例、264 次执行。浏览器与 HTTPS 历史记录保持各自边界，本轮没有重跑浏览器矩阵或真实地图。归档启动 4 项单独计数；它不代表全新系统依赖安装、Linux 服务启停或公网验收。
