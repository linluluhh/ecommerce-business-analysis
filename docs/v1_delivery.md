# V1交付清单

**基于模拟数据的业务分析项目。**

|要求|交付|
|---|---|
|原始业务数据|data/raw六张CSV及原SHA-256清单，未重新生成、未修改|
|数据质量报告|reports/data_quality_report.md及data/processed/quality_issues.csv|
|清洗Notebook|notebooks/01_data_cleaning_v1.ipynb，已从干净内核运行；原01_data_quality.ipynb保留|
|清洗后数据|data/processed六张clean CSV、异常隔离与利润事实数据|
|SQL|sql四个查询及派生SQLite，SQL与Pandas结果核验|
|业务分析Notebook|notebooks/02_business_analysis_v1.ipynb，已执行|
|Dashboard|dashboard/index.html离线交互页面、overview.png及预览截图|
|经营报告|reports/september_business_report.md，含样本范围、费用桥梁、维度贡献和行动建议|
|自动周报|scripts/weekly_report.py及reports/weekly示例；无外部发送或定时任务|
|GitHub README|README.md，含业务、数据、方法、发现、建议、复现与AI参与说明|
|流程图|docs/project_flow.md中的Mermaid图|
|简历描述|docs/resume_project_description.md（GitHub公开版本）|
|面试介绍|docs/resume_project_description.md|
|追问及答案|docs/resume_project_description.md；旧面试草稿保留本地|

核验见reports/validation.json：原始哈希、订单粒度、采购成本、退款、会计桥梁、平台/SKU加总、SQL/Pandas、Notebook执行、AI指标白名单与数字拒绝检查。

## 仍属业务待核实，而非技术交付缺失
异常价格数量的正确值、SKU999成本、两笔超额退款、缺失广告花费及疑似停投/漏报，均无可靠源凭证，未编造修正。V1采用透明的临时分析范围，不能给精确财务净利润，也不能从观察数据识别全部独立因果贡献。AI周报示例未调用外部API，结构和指标引用验证不能替代人对解释的核查。

## 已有学习成果保护
原始学习Notebook、orders.xlsx、generate_data.py、data_quality_progress.md均保留。新增_v1 Notebook用于整理复现；没有重写学习过程。项目尚未上传GitHub，上传时排除.gitignore列出的环境和浏览器缓存。
