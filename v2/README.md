# V2.1 运行与验证索引

当前功能版本为 V2.1 C2。完整背景、功能和安装入口见[根 README](../README.md)，不要用 V1 的运行脚本启动本应用。

- 入口：`v2/app.py`，Streamlit 六个导航：数据运营工作台、经营分析、经营日报、智能预警、数据修订、规则配置。
- 依赖：`v2/requirements-lock.txt` 为验收锁定版本；`v2/requirements.txt` 为兼容范围。Python 3.11，Windows/Edge 实测。
- 默认数据目录：`v2/runtime/`；`V2_DATA_DIR` 可指定独立目录。业务和模拟空间逻辑隔离，第二阶段模拟另用 `phase2_demo/`。
- 样例：`v2/demo_data/phase2_synthetic.xlsx`，全部 Synthetic；[演示步骤](../docs/portfolio/DEMO.md)说明审核和修订的不同路线。
- 备份：停止应用后复制整个数据目录；不把数据库、上传原件、备份或日志提交到公开仓库。
- [V2.1 架构](../docs/portfolio/ARCHITECTURE.md)、[指标口径](docs/METRIC_DEFINITIONS.md)、[规则](docs/ALERT_RULES.md)、[审批](docs/REVISION_WORKFLOW.md)、[日报设计](docs/V21_DAILY_REPORT_DESIGN.md)。旧阶段文档为历史证据，不代替当前首页。

## 自动化测试

在仓库根目录执行：

```powershell
v2/.venv/Scripts/python.exe -m pytest v2/tests/test_daily_report.py v2/tests/test_daily_report_page.py -q
v2/.venv/Scripts/python.exe -m pytest v2/tests -q
```

C2 于 2026-10-21 实测专项 26 passed、全量 176 passed，对应 `3739832fa4d2adf6becebfe213616233e8b0ad5f`。本轮文档整理没有重新执行这些测试。公开证据见[发布材料](../docs/portfolio/RELEASE.md)。

## Edge / Playwright 开发验收

这不是普通用户启动步骤。需要可用的 Node.js（验收使用支持当前 Playwright 的现代版本）、`playwright` 包及 Microsoft Edge。浏览器脚本会导入 Synthetic 数据、写入测试预警和修订，必须使用新的空目录与独立端口，不得指向业务库。

先安装开发工具 `npm install --no-save --package-lock=false playwright`（仓库根目录，首次需网络）；Node 依赖不随应用发布。第一个 PowerShell 终端运行：

```powershell
$env:V2_DATA_DIR = Join-Path (Get-Location) 'v2/runtime/c2-browser-fresh'
v2/.venv/Scripts/python.exe -m streamlit run v2/app.py --server.address 127.0.0.1 --server.port 8545 --server.headless true --browser.gatherUsageStats false
```

第二个终端仍在仓库根目录运行：

```powershell
$env:V2_DAILY_DATA_DIR = Join-Path (Get-Location) 'v2/runtime/c2-browser-fresh'
$env:V2_BASE_URL = 'http://127.0.0.1:8545'
$env:V2_PYTHON = (Resolve-Path 'v2/.venv/Scripts/python.exe').Path
$env:V2_DAILY_REPORT_ACCEPTANCE = '1'
node v2/daily_report_browser.cjs
```

脚本使用 `channel: 'msedge'`；默认场景日期固定在 2026 年 9 月、H=2026-10-21，系统日期需不早于 H。脚本输出到 `v2/runtime/v21-daily-c2/browser/`，会覆盖同名验收输出；若要保留已有结果，先复制该证据目录。应用数据目录必须两终端一致。运行结束在服务终端 Ctrl+C。不要据此宣称已在其他浏览器或操作系统验收。

其他历史脚本：`quality_browser.cjs`、`phase2_browser.cjs`、`phase2b_browser.cjs`、`duplicate_browser.cjs`、`browser_verify.cjs`。各自环境变量和场景不同，不是一个命令的无副作用截图工具。

## 当前限制

手动触发检测，无计划任务/通知/平台同步/AI 助手/生产权限。小批量全量重评、单币种、静态成本、单 SKU 订单。凭证与操作员为本地引用/自报标识。原文件与 SQLite 非同一原子事务，未收齐数据不等于零业务。日报历史证据不能还原完整历史状态。
