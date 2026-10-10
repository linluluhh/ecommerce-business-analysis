# 简历项目描述与面试介绍

**模拟业务作品集，非真实工作经历。使用Codex辅助开发，不能声称所有代码独立完成或产生真实收益。**

## 中文简历版本

跨境电商经营数据分析与利润异常诊断｜模拟业务个人项目（Codex辅助）

- 基于9,970行订单及商品、库存、退款、广告、客户六表，完成Excel探索、Pandas粒度/主键/缺失/关联质检；复核18条重复订单，建立异常隔离证据与六表质量台账。
- 使用SQL/SQLite与Pandas分析月度销售、商品毛利、履约佣金、退款和广告费用，构建可精确对账的贡献利润桥梁，复核有效销售下降18.92%、临时贡献利润下降40.27%。
- 按平台和SKU定位经营变化，结合库存日报、促销、CPC/ROAS及统一12天退款队列提出排查建议，区分描述性发现、情景估算与未确认因果。
- 交付可从原始数据复现的Notebook、SQL、经营报告、真实数据图、离线Dashboard及自动周报；在隔离环境执行和对账，披露Codex辅助及数据限制。

## English resume version

Cross-border E-commerce Business Analytics & Profit Diagnostics — Synthetic Portfolio Project, Codex-assisted

- Reviewed 9,970 order rows across six related tables with Excel and Pandas, validated data grain and keys, resolved 18 exact duplicate orders, and documented exceptions in a six-table quality log.
- Used SQLite/SQL and Pandas to reconcile sales, product costs, fulfilment, commissions, refunds and recorded advertising costs; verified an 18.92% decline in effective sales and a 40.27% decline in provisional operating contribution.
- Investigated platform/SKU changes using inventory records, discount metrics, CPC/ROAS and consistent 12-day refund cohorts, distinguishing evidence-based leads from scenarios and unverified causal claims.
- Delivered executed notebooks, reproducible scripts, reports, static charts, an offline dashboard and weekly reporting; disclosed AI assistance and unresolved data limitations without claiming realized commercial outcomes.

## 30秒项目介绍

这是一个Codex辅助完成的模拟跨境电商项目。我从六张业务表出发，先核实重复和异常，再用SQL、Pandas建立销售及贡献利润口径。质检后销售降幅约19%，临时贡献利润下降约40%，重点线索是TK、核心商品缺货和售后上升。最终交付可复现代码、质量台账、报告与Dashboard，数字不代表真实公司收益。

## 2分钟项目介绍

项目模拟广州一家约30人的跨境电商公司，主管希望解释九月经营下滑。我先用Excel理解订单字段、整单优惠和取消状态，随后用Pandas检查六表粒度、主键、缺失值、格式和关联。原始销售降幅约30%，但重复记录和极端价格数量影响很大；临时排除待核实记录后，有效销售降幅为18.92%。

接着关联商品成本，加上物流、佣金、按确认月统计的有效批准退款以及已记录广告费，得到成本已知样本贡献利润下降20,532.13美元、约40.27%。我把下降拆成六项可以精确加总的会计变化，再按平台和SKU定位：TK是最大平台下降来源，SKU001有连续四日零库存，TK优惠率和点击成本上升，SKU004统一12天窗口的退款比例明显增加。

我没有把这些线索全部称为因果，也没有把缺货、优惠和CPC情景加总成损失。广告缺失和未知成本仍披露为待核实。技术交付包括SQL/Pandas独立对账、两个执行过的Notebook、离线Dashboard、经营报告和周报。Codex协助编码与文档，我重点学习并准备解释业务口径、样本选择、验证方法和结果限制，不把AI协作部分描述为完全独立实现。

## 10个可能追问

|问题|回答要点|
|---|---|
|1. 如何判断18条订单可以去重？|先确认单SKU订单粒度；重复编号涉及36行，18条副本全字段一致；不能仅按订单ID删除可能不同的明细。|
|2. 为什么不是净利润？|贡献利润缺少工资、租金、税费等财务项目，且广告和部分原值未完整核实。|
|3. 销售与利润样本为什么不同？|销售保留3笔成本未知订单，利润额外排除它们；不得混用对应变化金额。|
|4. 怎么避免merge后金额膨胀？|商品键唯一、many_to_one校验；订单、退款和广告先分组汇总再关联，独立验证加总。|
|5. 退款按哪月统计？|期间费用按批准确认月；售后表现按下单月、统一12天窗口，避免观察时间不同。|
|6. ROAS大于1是否赚钱？|不是，归因收入未扣商品、履约、佣金、退款；ROAS不是利润率，缺失费样本还有限制。|
|7. 缺货估算如何得到？|四日零库存与完成订单为0同步；附近两个有货周共502件，对账后按日均和实收做情景，不代表实际损失。|
|8. 为何不把异常直接改成正常价格？|没有源凭证，猜测会编造数据；保留原值、隔离和质量日志，用临时口径并披露。|
|9. 如何确保别人能复现？|完整raw和哈希、锁定依赖、干净环境执行、明确内核、SQL/Pandas对账及GitHub链接检查。|
|10. Codex帮你做了什么？|帮助代码、图表与材料整理；我如实披露协作并解释口径与核验，不声称独立实现全部代码或真实商业收益。|

面试前应能亲自重跑并解释至少一个SQL CTE、一次merge、一项退款窗口计算及利润桥梁。不要背诵尚未理解的技术内容。
