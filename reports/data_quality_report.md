# 数据质量检查报告V1

**基于模拟数据的业务分析项目。** raw六张CSV与初始SHA-256清单一致，未修改。

## 粒度和主键
| table | grain | business_key | raw_rows | columns | exact_duplicate_excess | duplicate_key_rows | missing_cells |
|---|---|---|---|---|---|---|---|
| orders | 一笔单SKU订单；根据数据字典及重复行全字段复核，非多商品订单明细 | order_id | 9970 | 12 | 18 | 36 | 12 |
| products | 一行一个商品SKU，成本两个月固定 | sku | 12 | 6 | 0 | 0 | 0 |
| inventory | 日期×SKU，共享库存日报 | date+sku | 732 | 6 | 0 | 0 | 0 |
| refunds | 一笔售后申请；order_id非主键，可有多笔退款 | refund_id | 312 | 7 | 0 | 0 | 0 |
| ads | 日期×平台×活动×SKU广告日报；conversions是订单数 | date+platform+campaign_id+sku | 2192 | 9 | 0 | 0 | 9 |
| customers | 一个注册客户；新老客标签相对8月1日固定 | customer_id | 4807 | 4 | 7 | 14 | 0 |

## 处理原则
订单是单SKU业务订单，不把订单编号重复自动当成脏数据。复核18组编号重复涉及36行，所有多余副本全字段一致；按全字段去重删除18行，剩余9952行且order_id唯一。客户主表有7条全字段重复，去重后4800客户。退款编号唯一，订单编号允许重复；广告按日期×平台×活动×SKU核验，无需按日期×SKU粗暴去重。

标准化新增列，原始字段保留。金额/数量异常保留在clean并另存quarantine；缺失客户不删除收入。SKU999未知成本不填0。超额退款不直接封顶。广告缺失不补0。库存平衡异常不自动反推修正。未知状态不确认收入。临时复核线：单价>100美元、数量>10件，并非行业通用规则。

## 问题汇总
| table | issue | flagged_rows |
|---|---|---|
| ads | missing:ad_spend | 9 |
| customers | exact_duplicate | 7 |
| inventory | inventory_order_difference | 9 |
| inventory | negative_inventory | 3 |
| inventory | stock_balance | 3 |
| inventory | stock_roll_forward | 3 |
| orders | country_format | 22 |
| orders | date_format:order_date | 35 |
| orders | exact_duplicate | 18 |
| orders | invalid_discount | 3 |
| orders | invalid_price | 2 |
| orders | invalid_quantity | 2 |
| orders | missing:customer_id | 12 |
| orders | platform_format | 25 |
| orders | review_high_price | 2 |
| orders | review_high_quantity | 2 |
| orders | sku_format | 40 |
| orders | unknown_sku | 3 |
| refunds | refund_exceeds_order_or_invalid | 2 |

广告缺失花费9条；按现有固定活动每日模式发现4条疑似漏报，需确认是否停投，不将推断当事实。详细证据见data/processed/quality_issues.csv和ads_missing_expected_rows.csv。库存与有效订单差异可能来自隔离异常及未知SKU，不直接认定库存错误。

## 范围与待核实
清洗并不代表真实性全部确认。采购成本仅有静态主表，缺少财务总账、平台补贴承担方、取消原因、活动日历、退款凭证、广告完整账单和库存小时级记录。需业务复核异常价格、数量、未知SKU、库存负数以及超额退款后，才能形成正式全公司利润。
