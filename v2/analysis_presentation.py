"""Display-only explanations and ordering of existing metric results."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from v2.ui_format import percent


def scope_summary(result, start, end, horizon, filters):
    return (f"当前分析范围：{start} 至 {end}；平台：{filters.get('platform') or '全部'}；"
            f"SKU：{filters.get('sku') or '全部'}；国家：{filters.get('country') or '全部'}；"
            f"订单状态：{filters.get('status') or '全部'}；有效完成订单数：{result['orders']}；"
            f"成本已知订单数：{result['profit_orders']}；退款观察截止日：{horizon}")


def trend_summary(rows, end):
    previous = end - timedelta(days=1)
    lookup = {str(row['date']): row for row in rows}
    current, base = lookup.get(str(end)), lookup.get(str(previous))
    prefix = f'{end}销售额较{previous}'
    if not current or not base or current['sales'] is None or base['sales'] is None:
        return prefix + '无法比较：缺少比较日期的可用销售数据。'
    current_value, base_value = Decimal(str(current['sales'])), Decimal(str(base['sales']))
    if base_value == 0:
        return prefix + '无法计算百分比变化：基期为0。'
    difference = current_value - base_value
    if difference == 0:
        return prefix + '持平。'
    direction = '上升' if difference > 0 else '下降'
    return prefix + direction + percent(abs(difference / base_value)) + '。仅比较这两日，不代表连续趋势或利润原因。'


def rank_rows(rows, value_key, identity_key, limit=None):
    """Exclude unknown values; preserve zero/negative values and source rows."""
    valid = []
    for row in rows:
        try:
            value = Decimal(str(row[value_key]))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if value.is_finite():
            valid.append((value, row))
    ordered = sorted(valid, key=lambda item: (-item[0], str(item[1][identity_key])))
    return [dict(row) for _, row in ordered[:limit]]


# Meaning, what it supports, and what it cannot establish. Formulas stay in metrics.py.
INTERPRETATIONS = {
    'orders': ('有效完成订单数量', '当前可用成交样本规模', '全部真实成交或完整账本'),
    'sales': ('有效完成订单折后收入', '当前样本的销售规模', '实收现金或利润'),
    'known_cost_sales': ('成本已知订单对应收入', '利润可计算的收入样本规模', '全部销售额'),
    'gross_profit': ('成本已知样本扣除商品成本后的余额', '商品层面的获利空间', '整体净利润；尚未扣除其他费用'),
    'gross_margin': ('已知成本样本的商品毛利比例', '同口径商品盈利效率', '未知成本订单的盈利水平'),
    'recorded_ad_cost': ('有效记录中的广告支出', '已观察到的广告投入', '广告账本已完整收齐'),
    'refund_cost': ('当前口径内确认的有效批准退款金额', '按确认日观察的退款负担', '所有历史订单最终退款损失'),
    'refund_rate': ('成熟成本已知订单中12天内批准退款的订单占比', '固定观察窗口内的退款频度', '金额退款率或尚未成熟订单的最终退款率'),
    'contribution': ('已知成本样本扣除已记录相关费用的暂估余额', '当前样本的经营贡献', '企业净利润或完整财务结算结果'),
    'data_completeness': ('可定位期间订单中有效完成记录的比例', '已导入订单记录的可用程度', '业务账本完整性或综合质量评分'),
    'cost_coverage': ('销售收入中成本已知部分的占比', '利润分析覆盖了多少收入', '订单数量覆盖率或成本准确性'),
    'unknown_orders': ('未进入利润计算的成本未知订单数', '需要补充成本信息的订单规模', '这些订单利润为0'),
    'unknown_sales': ('成本未知订单对应收入', '暂时无法评估利润的收入规模', '这些收入没有成本'),
    'goods_cost': ('利润样本的商品成本总额', '已知商品成本负担', '全部订单成本或全部经营费用'),
    'shipping_cost': ('利润样本中记录的物流费用', '已知样本的物流支出', '完整物流账单或退款后的费用返还'),
    'platform_cost': ('利润样本中记录的平台佣金', '已知样本的平台费用负担', '平台全部结算费用'),
    'roas': ('广告归因收入相对于广告支出的倍数', '广告投入对应的归因销售回报', '整体盈利或广告带来的增量因果效果'),
}
