-- 基于模拟数据。每个订单只算一次，统一下单后12天退款确认窗口。
SELECT o.sku_standard,o.month,COUNT(*) completed_orders,
 SUM(CASE WHEN EXISTS (
  SELECT 1 FROM profit_refunds r WHERE r.order_id=o.order_id AND r.days_to_refund BETWEEN 0 AND 12
 ) THEN 1 ELSE 0 END) refunded_orders,
 100.0*SUM(CASE WHEN EXISTS (
  SELECT 1 FROM profit_refunds r WHERE r.order_id=o.order_id AND r.days_to_refund BETWEEN 0 AND 12
 ) THEN 1 ELSE 0 END)/COUNT(*) refund_rate_pct
FROM profit_orders o GROUP BY o.sku_standard,o.month ORDER BY o.sku_standard,o.month;
