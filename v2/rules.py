"""Execute the original V1 quality statements without running its output pipeline.

The AST boundary excludes all file writes and fixed-demo acceptance assertions.
The original rule expressions, thresholds and mappings are executed unchanged.
Conflict keys must be isolated by the caller before this adapter is called.
"""
import ast
import hashlib
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/run_project_v1.py'
spec = importlib.util.spec_from_file_location('v1_readonly', SOURCE)
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)  # __main__ guard prevents run()
GRAINS = v1.GRAINS
VERSION = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
SCHEMAS = {n: pd.read_csv(ROOT / f'data/raw/{n}.csv', nrows=0).columns.tolist() for n in GRAINS}


class NoAssertions(ast.NodeTransformer):
    def visit_Assert(self, node):
        return ast.copy_location(ast.Pass(), node)


tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run').body
start = next(i for i,n in enumerate(body) if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='original' for t in n.targets))
end = next(i for i,n in enumerate(body) if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='missing_ad' for t in n.targets))
module = NoAssertions().visit(ast.Module(body=body[start:end], type_ignores=[]))
CODE = compile(ast.fix_missing_locations(module), str(SOURCE), 'exec')


def check(tables):
    env = {'pd': pd, 'np': np, 'GRAINS': GRAINS, 'PLATFORMS': v1.PLATFORMS,
           'COUNTRIES': v1.COUNTRIES, 'tables': {n: t.copy() for n,t in tables.items()}}
    exec(CODE, env)
    return env['tables'], env['issues']


def policy(code, table):
    """V2 quarantine policy; formulas remain V1. Confirmation never means release."""
    if code in ('sku_format','platform_format','country_format','exact_duplicate') or code.startswith('date_format:'):
        return 'none', False, '信息'
    if table == 'orders' and code in ('missing:customer_id','unknown_customer'):
        return 'none', False, '警告'
    if table == 'orders' and code == 'unknown_sku':
        return 'profit', True, '高'
    soft = code in ('review_high_price','review_high_quantity','order_before_registration',
                    'order_before_launch','inventory_order_difference','stock_roll_forward',
                    'ad_conversion_order_difference','ad_revenue_order_difference','customer_type_conflict')
    return 'all', not soft, '中' if soft else '高'


def affected_fields(code, table):
    if ':' in code:
        return code.split(':',1)[1]
    mapping = {
        'invalid_price':'unit_price', 'invalid_quantity':'quantity', 'invalid_discount':'discount,quantity,unit_price',
        'invalid_fee':'shipping_fee,platform_fee', 'review_high_price':'unit_price', 'review_high_quantity':'quantity',
        'unknown_sku':'sku,unit_cost', 'unknown_status':'order_status', 'unknown_customer':'customer_id',
        'refund_exceeds_order_or_invalid':'refund_amount,order_id', 'refund_orphan':'order_id',
        'stock_balance':'opening_stock,inbound_qty,sold_qty,closing_stock', 'invalid_unit_cost':'unit_cost',
        'business_key_conflict':','.join(GRAINS[table][0]), 'non_finite':'数值字段'}
    return mapping.get(code, ','.join(SCHEMAS[table]))


def describe(code, action):
    """Human-readable explanations of the original V1 predicates, not new rules."""
    reasons = {
        'invalid_price':'单价缺失或不大于 0',
        'invalid_quantity':'数量缺失、不大于 0 或不是整数',
        'invalid_discount':'优惠缺失、小于 0 或超过数量×单价',
        'invalid_fee':'物流费或佣金缺失、或小于 0',
        'review_high_price':'单价超过 V1 临时复核线 100 USD',
        'review_high_quantity':'数量超过 V1 临时复核线 10 件',
        'unknown_sku':'标准 SKU 在商品主表中不存在，成本未知',
        'unknown_status':'订单状态不是 completed 或 cancelled',
        'unknown_customer':'客户编号在客户主表中不存在',
        'invalid_unit_cost':'单位成本缺失或不大于 0',
        'order_before_registration':'下单日期早于客户注册日期',
        'order_before_launch':'下单日期早于商品上架日期',
        'customer_type_conflict':'客户标签与 V1 固定 2026-08-01 注册基准不符',
        'negative_inventory':'库存数量中存在负数',
        'stock_balance':'期末库存不等于期初＋入库－出库',
        'stock_roll_forward':'期初库存与该 SKU 前一条库存记录的期末不同',
        'inventory_order_difference':'库存出库数量与有效完成订单数量不符',
        'fractional_units':'库存件数包含非整数',
        'refund_orphan':'退款无法关联订单',
        'refund_status_invalid':'退款状态不是 approved、pending 或 rejected',
        'refund_cancelled_order':'退款关联订单未完成',
        'refund_before_order':'退款日期早于下单日期',
        'refund_exceeds_order_or_invalid':'退款缺失、小于 0，或单笔/累计批准退款超过订单实收＋V1 0.01 容差',
        'unexpected_restock':'恢复可售库存数量非 0，与 V1 期间约定不符',
        'negative_ad_metric':'广告指标存在负数',
        'ad_funnel_invalid':'广告点击超过曝光，或转化超过点击',
        'fractional_ad_count':'曝光、点击或转化计数包含非整数',
        'ad_conversion_order_difference':'广告转化数超过同日同平台同 SKU 有效完成订单数',
        'ad_revenue_order_difference':'广告归因收入超过同范围有效订单实收＋V1 0.01 容差'}
    if code.startswith('missing:'):
        cause = f"字段 {code.split(':',1)[1]} 缺失"
    elif code.startswith('type_invalid:'):
        cause = f"字段 {code.split(':',1)[1]} 无法解析为数值"
    elif code.startswith('date_invalid:'):
        cause = f"字段 {code.split(':',1)[1]} 无法解析为 YYYY-MM-DD 日期"
    else:
        cause = reasons.get(code)
    return f'{cause}；{action}' if cause else action
