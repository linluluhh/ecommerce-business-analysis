-- 基于模拟数据。订单与退款、广告先分别聚合再连接，防止多对多金额放大。
WITH o AS (
 SELECT month, SUM(order_sales) sales, SUM(goods_cost) goods_cost,
 SUM(before_refunds_ads) before_refunds_ads FROM profit_orders GROUP BY month
), r AS (
 SELECT refund_month month, SUM(refund_amount) refund_cost FROM profit_refunds GROUP BY refund_month
), a AS (
 SELECT month, SUM(ad_spend) recorded_ad_cost FROM ads GROUP BY month
)
SELECT o.month, o.sales, o.goods_cost, COALESCE(r.refund_cost,0) refund_cost,
 a.recorded_ad_cost,
 o.before_refunds_ads-COALESCE(r.refund_cost,0)-a.recorded_ad_cost contribution
FROM o LEFT JOIN r USING(month) LEFT JOIN a USING(month) ORDER BY o.month;
