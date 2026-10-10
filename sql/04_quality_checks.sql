-- 基于模拟数据。clean保留异常，分析样本独立隔离。
SELECT 'orders_duplicate_keys' check_name,COUNT(*) issue_count FROM (
 SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*)>1
)
UNION ALL SELECT 'missing_customers',COUNT(*) FROM orders WHERE customer_id IS NULL
UNION ALL SELECT 'unknown_sku',COUNT(*) FROM orders o LEFT JOIN products p USING(sku_standard) WHERE p.sku_standard IS NULL
UNION ALL SELECT 'missing_ad_spend',COUNT(*) FROM ads WHERE ad_spend IS NULL
UNION ALL SELECT 'refund_amount_review',COUNT(*) FROM refunds WHERE amount_needs_review=1;
