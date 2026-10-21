"""Read-only grouping of existing quality findings; no new detection rules."""
import pandas as pd
from v2.rules import policy

TABLE_NAMES = {'orders':'订单', 'products':'商品', 'customers':'客户', 'inventory':'库存', 'refunds':'退款', 'ads':'广告'}


def category(code):
    if code.startswith('missing:') or code == 'missing_business_key':
        return '缺失字段'
    if code.startswith(('type_invalid:', 'date_invalid:')) or code == 'non_finite':
        return '类型与日期解析'
    if code == 'business_key_conflict':
        return '业务键冲突'
    if code in {'unknown_sku', 'unknown_customer', 'refund_orphan'}:
        return '主数据与关联'
    if code.startswith('date_format:') or code in {'sku_format', 'platform_format', 'country_format', 'exact_duplicate'}:
        return '格式与去重提示'
    if code in {'invalid_price', 'invalid_quantity', 'invalid_discount', 'invalid_fee', 'invalid_unit_cost',
                'review_high_price', 'review_high_quantity', 'negative_inventory', 'fractional_units',
                'refund_exceeds_order_or_invalid', 'negative_ad_metric', 'fractional_ad_count'}:
        return '金额与数量检查'
    if code in {'order_before_registration', 'order_before_launch', 'customer_type_conflict',
                'inventory_order_difference', 'stock_roll_forward', 'stock_balance', 'ad_funnel_invalid',
                'ad_conversion_order_difference', 'ad_revenue_order_difference', 'refund_before_order',
                'refund_cancelled_order', 'unexpected_restock'}:
        return '业务一致性'
    return '其他规则'


def effect(row):
    if not row['active']:
        return '已失效（仅历史）'
    scope, hard, _ = policy(row['code'], row['table_name'])
    if scope == 'none':
        return '非阻断提示'
    if not hard and row['status'] == '驳回':
        return '软规则已驳回'
    return '整行隔离' if scope == 'all' else '仅利润隔离'


def prepare(issues):
    rows = issues.copy(deep=True)
    rows['异常分类'] = rows['code'].map(category)
    rows['规则作用'] = rows.apply(effect, axis=1) if not rows.empty else pd.Series(dtype='object')
    return rows


def select(rows, filters):
    selected = rows
    for column, value in filters.items():
        if value is not None:
            selected = selected[selected[column].eq(value)]
    return selected.copy()


EFFECT_ORDER = ['整行隔离', '仅利润隔离', '软规则已驳回', '非阻断提示']
TABLE_IMPACT = {
    'orders': '订单记录隔离时不进入相应经营样本；未知SKU订单保留有效收入，仅利润不可计算。',
    'products': '商品成本不可用可能影响关联订单利润；不据此推算下游订单数量或损失金额。',
    'refunds': '退款记录不可用可能影响退款分析及贡献利润，具体适用范围由指标服务确定。',
    'ads': '广告记录不可用可能影响费用、ROAS和贡献利润，缺失费用不补0。',
    'inventory': '库存记录不可用影响库存分析和预警，不代表已经发生缺货损失。',
    'customers': '客户记录异常需核查关联与客户分析，不能直接认定关联订单收入无效。',
}


def summarize(current, all_current):
    """Count selected findings, but resolve record effects using ALL active rules.

    A category/status filter must not hide another blocking rule on the same record.
    """
    # records.id is the database-wide primary key across tables/workspaces.
    # Callers supply a single Store/workspace, never concatenate separate databases.
    current = current[current.active.eq(1)]
    all_current = all_current[all_current.active.eq(1)]
    ids = set(current['record_id'])
    related = all_current[all_current['record_id'].isin(ids)]
    effects = []
    for record_id, group in related.groupby('record_id', sort=True):
        applied = set(group['规则作用'])
        label = next(label for label in EFFECT_ORDER if label in applied)
        table = group.iloc[0]['table_name']
        effects.append({'记录ID': record_id, '业务表': table, '记录当前作用': label,
                        '业务影响说明': TABLE_IMPACT.get(table, '请结合该业务表和原规则证据核查，不推算经营损失。')})
    stats = [{'异常分类': name, '异常条数': group['id'].nunique(), '受影响记录数': group['record_id'].nunique()}
             for name, group in current.groupby('异常分类', sort=True)]
    return {
        '有效异常条数': current['id'].nunique(),
        '受影响记录数': len(ids),
        '待核实异常数': current.loc[current['status'].eq('待核实'), 'id'].nunique(),
        '直接阻断记录数': sum(row['记录当前作用'] in ('整行隔离', '仅利润隔离') for row in effects),
        'categories': stats, 'effects': effects,
    }
