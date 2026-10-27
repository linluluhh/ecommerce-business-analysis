# Streamlit Community Cloud 公开演示说明

入口：`v2/portfolio_app.py`。公开 Synthetic 演示已上线，2026-10-26 已通过真实 Edge 线上业务实操核对：[在线体验](https://ecommerce-business-analysis-izcmrhydxddnasxqdbdxxr.streamlit.app/)。部署分支为 `release/v2.1-streamlit-deploy`。以下保留隔离设计及2026-10-22历史验收，当前展示见 [SHOWCASE](SHOWCASE.md)。本轮只整理文档与素材，未重新部署。

## 两种运行模式

|内容|本地完整模式|公开 Synthetic 模式|
|---|---|---|
|入口|`v2/app.py`|`v2/portfolio_app.py`|
|数据|本地业务/模拟空间；可配置 V2_DATA_DIR|仅预载 Synthetic，忽略 V2_DATA_DIR，不显示业务空间|
|上传|原有 CSV/XLSX 导入与模板|不创建任意文件上传控件，不接受访客业务文件|
|审核/修订/检测/规则配置|原有功能|复用相同页面和服务，只写当前会话副本|
|分析、质量、日报、HTML|原有功能|开放；质量和日报 HTML 在内存生成，可离线下载|
|保存|本机数据目录，可手动备份|临时保存；断线/刷新可能重建，不承诺持久化|

公开表单只允许模拟内容，文本长度受限。默认阈值仍为演示值，人工处理不等于根因确认。初始化调用已有 13 条规则服务写入 Synthetic 留存证据；证据保存时间是初始化时间，检测参考日固定为 2026-10-21，不能伪装为历史经营日当时的状态。

## 初始化、隔离、清理

`portfolio_sessions.py` 负责进程内会话管理；`portfolio_app.py` 在独立执行命名空间复用 `app.py`，不更改进程环境变量或模块注册来切换数据库。

- 首次访问生成不可预测的会话标识，存于服务端 Streamlit session_state，不从 URL 或表单接受数据库路径。
- 每个会话在系统临时目录获得独立文件夹与 SQLite，按同一 `phase2_synthetic.xlsx` 初始化，随后运行现有预警引擎一次。重复 rerun 复用已有 Store，不重复导入或检测。
- 管理器首次创建加锁；不同会话有不同数据库，同一会话的执行加锁。活动执行持有租约，清理不会删除使用中的目录。
- 每 60 秒清理空闲超过 30 分钟或存活超过 2 小时的非活动会话；新请求也执行清理。上限 64 个会话，每次操作前检查 8 MiB 数据限额，超限提示重置。限额不是生产级防滥用系统。
- “重置我的演示”丢弃本会话数据、清空控件状态并重新播种，不改变其他访客。应用进程重启创建新的管理器和种子库，不加载旧业务库。
- 正常进程退出清理所属临时目录；强制终止时的残留依赖容器/系统临时目录回收，不宣称崩溃后永久文件一定即时删除。持续运行中的过期目录由后台线程清理。
- 所有删除仅针对本管理器生成并登记的目录；初始化失败不保留半成品会话，并显示不含路径的中文错误。

这不是身份认证、多租户生产数据库或可靠存储服务。不要上传或输入真实企业数据、凭证、个人信息。平台配额和重启会影响演示可用性。

## 本地验证公开模式

从仓库根目录执行：

```powershell
py -3.11 -m venv v2/.venv
v2/.venv/Scripts/python.exe -m pip install -r requirements.txt
v2/.venv/Scripts/python.exe -m streamlit run v2/portfolio_app.py --server.address 127.0.0.1 --server.port 8547
```

macOS/Linux 使用虚拟环境下 `bin/python`，从仓库根目录执行相同模块命令。路径均由 `__file__` 或系统临时目录构造，无 Windows 驱动器依赖。当前实际验证环境为 Windows/Edge；2026-10-26公开网址已可访问；本轮未重新安装云端环境。

本地完整入口仍可使用首页命令（`v2/app.py`、上传上限显式设为 20 MiB）。根配置的公开默认上传上限为 2 MiB，但公开入口根本不提供上传；原本地命令显式参数优先。`V2_DATA_DIR` 只对本地完整入口生效。

## 已使用的云端配置（保留供维护参考，本轮不执行）

1. 已使用 `release/v2.1-streamlit-deploy` 分支；未来推送或部署仍需另行授权。
2. 在 Community Cloud 选择仓库 `linluluhh/ecommerce-business-analysis`、实际推送分支、入口 `v2/portfolio_app.py`。
3. Advanced settings 选择 Python **3.11**。不需要 secrets，也不要填写真实业务数据库配置。
4. 使用根 `.streamlit/config.toml`；开启 headless、关闭使用统计、隐藏访客堆栈详情，未关闭 XSRF/CORS 保护。
5. 依赖：根 `requirements.txt` 仅 Streamlit、Pandas、NumPy、openpyxl、tzdata；入口目录 `v2/requirements.txt` 引用 `../requirements.txt`。不装 Jupyter、绘图库或 pytest。开发测试另用 `v2/requirements-dev.txt`，V1 兼容依赖保存为 `requirements-v1.txt`。
6. 冷启动后用两个浏览器上下文验证互不影响，核对下载和重置，再记录真实网址。公开地址见本文顶部；实际证据记录见作品集展示说明。

官方依据：[工作目录与配置](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)、[入口目录依赖优先级](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)。

## 验证命令

```powershell
v2/.venv/Scripts/python.exe -m pip install -r v2/requirements-dev.txt
v2/.venv/Scripts/python.exe -m pytest v2/tests/test_portfolio_deploy.py -q
v2/.venv/Scripts/python.exe -m pytest v2/tests -q
```

Edge/Playwright 验证脚本 `v2/portfolio_browser.cjs`：安装既有文档所述 Playwright 开发工具，启动上述本机公开入口，设置 `V2_BASE_URL=http://127.0.0.1:8547` 后执行 `node v2/portfolio_browser.cjs`。脚本通过两个真实浏览器上下文完成修订与审批，再对账另一会话、重置和 HTML 断网下载。它只允许 loopback 地址，不用于真实业务服务。

验证输出位于忽略的 `v2/runtime/deploy-validation/`，不会提交临时数据库或原始日志。V2.1 原有 176 passed 是历史证据，本候选以本轮实际测试结果为准。

## 历史本地结果（2026-10-22）

- 隔离/初始化/清理/入口专项：12 passed（17.74 秒）。
- 最终全量：188 passed（154.09 秒）。首次全量为 187 passed、1 failed：旧 C2 测试把固定零点当成未来检测时间；已改为相对种子记录时间，未修改历史证据业务逻辑，随后有针对性重跑全量。
- Edge：两个真实上下文初始化、A 修订审批/B 不变、重置、质量与日报 HTML 下载及断网打开均通过，页面错误列表为空。浏览器初次读取旧页面/假定重置跳转的等待脚本已修正。
- 入口目录依赖 dry-run（已有环境）与 pip check 通过；当时没有进行全新 Linux 安装或云端部署；后续2026-10-26线上可访问性与业务操作另有独立证据。
- 指标、质量规则、13 条预警、审核修订服务及 SQL 结构未修改；本地原有测试全部通过。

原始证据：`v2/runtime/deploy-validation/specialist-final.log`、`full-final.log`、`browser/results.json` 与浏览器截图（均留本地，不公开提交运行产物）。
