# 数据交接说明

全部数据为 Synthetic / 模拟数据。业务期间为 2026 年 8–9 月，采用各业务系统的日粒度，无小时及时区转换。货币均为 USD 等值，保留两位小数。原始字段可能存在录入或导出不一致，以下描述的是约定口径，不代表每一条原始记录均符合约定。

## orders.csv：订单导出
一行原则上是一笔单 SKU 订单，`order_id` 是业务订单键，不应把原始行数直接当作订单数。

|字段|含义|
|---|---|
|order_id|订单编号|
|order_date|下单日期|
|customer_id|客户编号，关联 customers|
|sku|商品编码，关联 products|
|platform|销售渠道|
|country|收货国家，标准为 US、GB、DE、SG、MY、PH|
|quantity|件数|
|unit_price|折扣前单件商品价格|
|discount|整笔订单优惠金额，非折扣比例|
|shipping_fee|公司承担的整笔履约物流成本，非向买家收取的收入|
|order_status|completed 已完成支付并发货；cancelled 取消且不确认收入、不出库、不发生订单物流或佣金成本|
|platform_fee|整笔订单平台佣金，原始导出可能列示取消前的估计费用；取消订单实际费用为零|

订单商品实收 = quantity × unit_price − discount，不包含物流收入。完成订单成本按商品单位成本乘发货件数计提。

## products.csv：商品主数据
一行一个 SKU。`sku` 商品键；`product_name` 名称；`category` 品类；`unit_cost` 单位到仓采购成本（两个月保持不变）；`supplier` 模拟供应商编号；`launch_date` 上架日期。仅用于模拟，不代表真实供应商。

## inventory.csv：库存日报
一行一个日期 × SKU，覆盖所有渠道共享的可销售库存。`date` 日期；`sku` 商品键；`opening_stock` 期初件数；`inbound_qty` 当日入库件数；`sold_qty` 当日完成订单出库件数；`closing_stock` 期末件数。
约定：期末 = 期初 + 入库 − 出库，下一天期初承接前一天期末。取消订单不出库。退货本期间不恢复可销售库存。日报不能证明一天内每一时刻的可用库存，也不记录未下单的潜在需求。

## refunds.csv：售后申请
一行一笔退款申请，`refund_id` 申请键；`order_id` 关联订单；`refund_date` 售后处理日期（approved 为退款确认日，其余为申请处理记录日期）；`refund_amount` 商品退款申请金额；`refund_reason` 原因；`refund_status` approved 已批准退款、pending 待处理、rejected 拒绝；`restocked_qty` 恢复可售库存件数，本项目为零。
退款不返还原订单物流及佣金，已发货采购成本不冲回。退款可以发生在下单之后的月份。需区分当月退款现金影响与订单所属月份的售后表现；9 月订单的后续售后观察到 10 月 12 日。

## ads.csv：广告日报
一行一个日期 × 平台 × campaign_id × SKU。`date` 日期；`platform` 渠道；`campaign_id` 活动编号；`sku` 商品键；`impressions` 曝光次数；`clicks` 点击次数；`ad_spend` 广告成本；`conversions` 同日归因的完成订单数（不是件数）；`attributed_revenue` 同日归因的折后商品收入。
归因仅采用模拟系统的同日规则，无跨日窗口、多触点归因或自然流量去重。广告转化为订单子集。广告归因收入已包含在订单收入中，不能额外加到销售额上。平台销售额 / 广告费与广告归因 ROAS 是不同指标。

## customers.csv：客户主数据
一行原则上一个客户。`customer_id` 客户键；`country` 注册国家；`register_date` 注册日期；`customer_type` new 为 8 月 1 日及之后注册，existing 为此前注册。这是相对本项目起始日的固定标签，不是每个月实时计算的新客标签。

## 利润范围与限制
本项目能计算商品毛利和扣除退款、履约、佣金、广告后的经营贡献利润。工资、租金、税费、汇兑损益等未提供，因此不能把经营贡献利润称作财务净利润。公司口头使用“利润”时，需要先确认指标口径。毛利、退款归属和其他费用的具体分析口径由后续任务确认并记录。

## 文件操作
CSV 为 UTF-8 BOM 编码，可在 Excel 中通过“数据 → 从文本/CSV”导入。编号按文本导入，避免自动转换。探索时另存工作副本；不要覆盖 `data/raw/`。关联前先检查键、日期与重复记录，避免重复统计。
