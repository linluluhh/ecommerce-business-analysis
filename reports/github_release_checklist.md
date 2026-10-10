# GitHub作品集发布前检查清单

日期：2026-10-10。**基于模拟数据的业务分析项目，不代表真实经营收益。** 本次只做V1文档、展示、代码检查和本地Git准备，不进入V2。

## 发布前检查

|检查|状态|实际执行与证据|
|---|---|---|
|依赖安装/兼容|通过Windows Python3.11|正式验收已在全新venv安装依赖；本次公开候选运行pip check退出0，使用已测试锁定版本。其他系统未实测。|
|从原始数据重跑|通过|实际Git暂存树导出全新目录后执行完整流程，无本地学习数据、私有工具或额外业务文件依赖；未调用生成脚本。|
|关键指标对账|通过|销售18.92%、贡献利润下降20532.13 USD/40.27%；SQL、会计桥梁、平台/SKU加总一致，汇总CSV与验收版逐字节一致。|
|Notebook执行|通过|两个正式V1 Notebook从干净内核运行，使用当前隔离解释器。历史Notebook排除，不作为指标来源。|
|Dashboard生成/启动|通过本地|流水线生成离线HTML；真实浏览器截图已检查；实际执行README的127.0.0.1服务器命令，Dashboard返回HTTP200，测试后进程已停止。|
|README图片/链接|通过|7张经过审查的展示图片；全部本地链接对实际Git候选目标校验，未编造在线站点。|
|文件路径/编码|通过|源代码没有固定本机路径；JSON解码后检查，避免lambda转义换行误报。文本使用LF；CSV禁用Git换行转换，保留raw哈希。|
|实际候选安全扫描|通过当前候选|扫描Git索引真实blob而非只看gitignore；没有用户密钥、私有邮箱、本机路径、作者元数据或缓存进入候选。内嵌Plotly逐字比对安装包后单独审核，仍扫描页面自身。|
|Git历史检查|通过本地可达历史检查|项目及父目录原无仓库；本地提交后已扫描全部可达历史blob，无安全发现。检查结果见github_release_evidence.json；远程推送仍未执行。|
|仓库大小|通过|公开候选约11.8 MiB，最大HTML约4.64 MiB，均低于25 MiB检查阈值；大小与名单见候选证据。|
|Markdown展示|通过本地显示检查|以Markdown表格渲染并用浏览器截图检查中英文、表格和图片。Mermaid采用GitHub支持的语法，但未在GitHub线上实际渲染，不标为线上验证通过。|
|项目许可|已确认MIT|用户已授权推荐方案，根目录LICENSE已创建；第三方版权保留，系统字体不分发。|
|创建公开仓库/推送|用户已授权，执行中|实际完成状态以GitHub仓库及发布记录为准；Dashboard不公开部署。|

## 公开候选与排除范围

公开候选包含完整六表模拟raw/哈希、清洗CSV和异常证据、两个正式Notebook、四个SQL、V1脚本、质量/经营/验收报告、离线Dashboard、质检Excel、中文英文简历材料、七张真实展示图、依赖与第三方说明。原始六表约1.1MB，可以完整公开，README没有把样本冒充完整复现数据。

本地保留但排除：原学习Notebook、orders.xlsx（含WPS作者元数据）、旧学习进度与面试草稿、生成数据脚本、本地Codex质检Excel渲染工具、.venv、node_modules链接、浏览器缓存、临时验收/发布副本、pycache、可重建SQLite和重复事实表。不是仅删除当前敏感文件掩盖历史；此前没有提交历史，本地新增历史也要检查。

## 展示与结果边界

7张图：月度销售/贡献利润、平台变化、利润桥梁、SKU变化、ROAS与退款、Dashboard真实截图、六表质检摘要。中文字体正常、金额USD、标注样本差异，非AI生成的虚构图表。

经营发现保持验收口径：TK贡献变化-13546.85 USD；SKU001四日零库存；TK优惠3.91%→11.99%、ROAS4.87→2.30；SKU004统一12天退款率3.31%→17.40%。未将贡献利润改名为净利润，未将情景估算或相关性提升为已证实因果。

## 本地Git与审批

本地仓库使用main分支，提交身份使用已连接GitHub的公开账号与noreply邮箱，不写真实私人邮箱到提交。目录所有权差异仅通过当前项目命令级safe.directory处理，没有扩大全局信任。

建议提交说明：`Prepare verified V1 analytics portfolio for GitHub`。本地提交和提交后扫描由执行日志与Git记录核对，本清单不嵌入自身提交哈希，避免循环修改。

建议仓库名：`ecommerce-business-analysis`。

简介：`Cross-border e-commerce sales, profit diagnostics, data quality and business analytics using Python, SQL and Pandas.`

Topics：python、sql、pandas、data-analysis、business-analytics、ecommerce、data-quality、portfolio。

用户已确认按推荐方案采用MIT并创建公开仓库、推送。Dashboard部署是另一项权限，本次不部署。

## 可检查的证据

- [实际公开候选复现](github_reproduction_evidence.json)
- [Git候选与历史审核结果](github_release_evidence.json)
- [候选文件清单](github_candidate_manifest.json)
- [隔离环境版本](acceptance_environment.json)
- [V1正式验收](v1_acceptance_report.md)
- [许可与第三方说明](../docs/third_party_notices.md)

当前检查不是形式化安全证明；许可决定、生产费用完整性和因果验证仍有明确边界。未执行的远程推送、在线Markdown渲染和公开部署均不标为通过。
