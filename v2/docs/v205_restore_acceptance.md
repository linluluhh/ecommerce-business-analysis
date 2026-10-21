# V2.0.5 稳定版本恢复与验收报告

验收日期：2026-10-20。全部数据为 Synthetic 模拟数据，不代表企业真实收益。

## 范围与来源

- 唯一修改仓库：当前独立整理仓库（下文文件路径均相对仓库根目录）。
- 基线：`e0b0db7d66d515128ffd07552a3ce0b4ebbaf58a`。
- 开始时工作区干净，创建临时分支 `rebuild/v2.0.5-staging`。
- 已有实现取自受保护的只读原项目；未写入原项目或完整备份。
- 恢复既有功能，没有重新开发数据质量功能；没有暂存、提交、推送或合并。

## 文件

|文件（相对本仓库）|处理目的|
|---|---|
|v2/app.py|只替换导航列表中的两个旧入口为经营分析|
|v2/phase2_ui.py|恢复 Phase 2A/2B 展示组件、旧路由兼容、11 KPI、趋势、拆解、来源与导出|
|v2/analysis_presentation.py|恢复范围摘要、逐日趋势文字、排名和指标解释纯函数|
|v2/tests/test_analysis_page.py|恢复单一入口、旧路由、筛选导出与国家边界测试|
|v2/tests/test_analysis_experience.py|恢复 KPI 顺序、范围、趋势边界、排名及说明测试|
|v2/tests/test_phase2_ui.py|恢复与最终页面顺序对应的已有回归断言|
|v2/tests/test_presentation.py|恢复与最终页面顺序对应的状态展示断言|
|v2/phase2_browser.cjs|恢复既有浏览器脚本；增加 Python/证据目录环境变量覆盖，默认证据目录改到 runtime，避免覆盖历史证据|
|v2/phase2b_browser.cjs|恢复已有 Phase 2B 验收；Python/证据路径可配置，桌面宽度改为1366|
|v2/README.md|仅更新 V2.0.5 导航、展示功能与业务边界|
|v2/docs/v205_restore_acceptance.md|本次实际验收报告|

临时对账脚本、补充浏览器脚本、基线归档、模拟数据库及日志均在已忽略的 `v2/runtime/v205-rebuild/`。不纳入业务源码。

## 已恢复能力与拆分

Phase 2A：单一经营分析入口；兼容两个旧内部路由；经营摘要、趋势分析、经营拆解、指标说明四组件；全部11项KPI；订单趋势；国家地区拆解；筛选、来源明细、图表与JSON导出。

Phase 2B：核心经营/经营效率/数据可信度分层；预警单独作为待办；当前日期、平台、SKU、国家、订单状态、有效样本和退款观察日摘要；仅最后一天与前一天的规则文字；销售和商品毛利Top SKU；平台暂估贡献利润排序；17项指标的含义、解释范围与限制。

`app.py` 没有整文件覆盖，仅改导航列表，因此原项目中该文件混入的 V2.1 页面调用未被引入。`phase2_ui.py`、展示辅助函数及四个测试文件按已有实现恢复；未发现它们依赖 V2.1 模块。

排除 `quality_presentation.py`、`quality_ui.py`、`quality_report.py`、V2.1测试、质量报告导出、经营日报、AI及质量评分。原 V2 质量检查和审核仍保留。

## 自动化验收

实际全量执行：**121 passed in 125.84s (0:02:05)**。

使用原项目已有 Python 环境作为只读解释器，禁用字节码写入；测试当前目录、pytest缓存、临时库及JUnit均位于整理副本。

日志：`v2/runtime/v205-rebuild/pytest-elevated.log`；JUnit：`pytest.xml`。
测试集合相对 Phase 1 的102项增加19项，并非通过凑数量验收。
`git diff --check` 通过；仅提示部分文件未来 Git 规范化 CRLF/LF，不是内容错误。

## 指标对账

从 HEAD 用 git archive 提取基线到隔离目录。仅导入一次模拟工作簿，分别用基线和恢复版本读取同一独立数据库；退款观察日固定2026-10-14。
对全部、SKU001、US国家、无匹配日期四种范围的完整指标JSON逐字段比较，结果完全相同。

|指标|基线|恢复后|
|---|---:|---:|
|有效订单|71|71|
|销售额 USD|1364.00|1364.00|
|SKU001销售额 USD|924.00|924.00|
|商品毛利 USD|658.00|658.00|
|暂估贡献利润 USD|262.00|262.00|
|ROAS（展示舍入）|3.57倍|3.57倍|
|成本覆盖率（展示舍入）|98.53%|98.53%|
|订单可用率（展示舍入）|98.61%|98.61%|

底层 Decimal 原值也逐字段一致，不只比较舍入结果。对账详情：`v2/runtime/v205-rebuild/metrics.json`；脚本：`verify_metrics.py`。
浏览器另验证实际下载的 JSON 与当时相同筛选及观察日的指标服务完整结果一致，浏览前后指标不变。
metrics.py、service.py、rules.py、alerts.py、revisions.py、schema.sql、migrate.py 与 HEAD 无差异。

## 真实浏览器验收

使用本机 Edge/Playwright，应用 `http://localhost:8540`，独立库 `v2/runtime/v205-rebuild/browser-data/`。

通过：空库状态 → 实际点击导入123条模拟记录 → 单一入口 → 四模块及全部11 KPI → 范围摘要 → SKU001筛选 → JSON下载逐字段对账 → 国家不分摊贡献 → 480px KPI无截断。
补充通过：订单趋势、国家表、2025-01-01至2025-01-03无匹配日期，金额显示“当前范围无匹配数据”，非0.00。
1366px及480px截图已检查。页面 pageerror=[]，无stException；服务错误日志只有启动信息，未见Streamlit异常。

实际执行 Phase 2B 主脚本和 runtime 补充脚本；较早 phase2_browser.cjs 的规则处理/修订/重启整链路本次未重跑，不将其报告为新的浏览器验收结果。相关功能有本次全量pytest回归覆盖。

截图位于 `v2/runtime/v205-rebuild/browser/`：

- 00-empty.png：空库。
- 01-summary.png：1366px经营范围、摘要与KPI。
- 02-trend.png：趋势。
- 03-rankings.png：排名。
- 04-definitions.png：指标解释。
- 05-mobile-summary.png：480px。
- 06-order-trend.png：订单趋势。
- 07-country.png：国家拆解。
- 08-no-match.png：无匹配状态。

验收结果：browser/results.json、browser/extra-results.json。
日志：browser-elevated.log、browser-error.log、browser-extra-verified.log、server-elevated.log、server-elevated-error.log。
早期沙箱进程无法正常运行，改为获准的本机隐藏进程；日期补充脚本曾因旧选择器和未提交控件状态失败，保留失败日志及截图，最终使用实际可见日期控件提交后通过。这些失败不冒充成功结果。

## 恢复验收结束时的状态（2026-10-20）

分支 `rebuild/v2.0.5-staging`，HEAD仍为e0b0db7。11个待纳入源码/文档路径：6个已跟踪修改，5个未跟踪新文件；暂存区为空。runtime证据与模拟数据库被Git忽略且保留。

恢复与本次独立验收完成，**具备确认后正式提交 V2.0.5 的条件**。本次不提交，未开始V2.1整理。
验收完成后关闭本次启动的8540端口应用进程，数据库、截图、失败记录及成功证据全部保留。
限制：验收为本地Synthetic作品集场景，不能据此宣称生产可用；运行环境复用本机已有依赖，尚未另建全新环境验收。

## 正式提交准备（2026-10-21）

按11个文件白名单检查提交范围，仅对本报告的本机绝对路径作脱敏并明确历史状态时间；业务源码未作新增修改。
运行时数据库、上传文件、截图和完整日志仅在本机忽略目录保留，不随本次提交公开。
