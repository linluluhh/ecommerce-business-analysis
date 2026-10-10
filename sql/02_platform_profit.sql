-- 基于模拟数据。退款用原订单归平台，用确认日期归月份。
WITH o AS (
 SELECT platform_standard,month,SUM(order_sales) sales,SUM(before_refunds_ads) base
 FROM profit_orders GROUP BY platform_standard,month
), r AS (
 SELECT platform_standard,refund_month month,SUM(refund_amount) refunds
 FROM profit_refunds GROUP BY platform_standard,refund_month
), a AS (
 SELECT platform_standard,month,SUM(ad_spend) ads FROM ads GROUP BY platform_standard,month
)
SELECT o.platform_standard,o.month,o.sales,COALESCE(r.refunds,0) refunds,a.ads,
 o.base-COALESCE(r.refunds,0)-a.ads contribution
FROM o LEFT JOIN r USING(platform_standard,month) LEFT JOIN a USING(platform_standard,month)
ORDER BY o.platform_standard,o.month;
