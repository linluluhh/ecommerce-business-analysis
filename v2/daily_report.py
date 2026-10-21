"""Read-only daily presentation model; business metrics belong to MetricCenter."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from v2.metrics import MetricCenter, today
from v2.quality_presentation import prepare, summarize
from v2.ui_status import Status, TEXT, value_state, workspace_has_data
from v2.ui_format import money, percent, percentage_points, roas
from v2.daily_evidence import read_history, build_guidance


KPIS = (
    ('sales', '折后销售额', 'sales_rate'),
    ('orders', '有效完成订单数', 'count'),
    ('gross_profit', '商品毛利', 'money'),
    ('contribution', '暂估贡献利润', 'money'),
    ('roas', '广告归因ROAS', 'multiple'),
    ('refund_rate', '12天退款订单率', 'points'),
)
AVAILABLE = (Status.NORMAL, Status.WARNING)


def formatted(key, value, state):
    if key == 'orders':
        return f'{value} 笔' if state in AVAILABLE else TEXT[state]
    formatter = roas if key == 'roas' else percent if key == 'refund_rate' else money
    return formatter(value, state)


def default_day(facts, current_date=None):
    current_date = current_date or today()
    dates = [date.fromisoformat(r['date']) for r in facts['candidates']
             if r['table'] == 'orders' and r['date'] and r['date'] < str(current_date)]
    return max(dates) if dates else current_date - timedelta(days=1)


def metric_status(key, result, facts, day, has_data):
    """Keep missing observations distinct from legitimate service-provided zeroes."""
    table = 'ads' if key == 'roas' else 'orders'
    candidates = [r for r in facts['candidates'] if r['table'] == table]
    matched = [r for r in candidates if r['date'] == str(day)]
    undated = any(not r['date'] for r in candidates)
    value = result[key]
    # The service's order count is zero even when no valid order sample exists.
    usable = any(r['date'] == str(day) for r in facts['orders'])
    display_value = None if key == 'orders' and not usable else value
    state = value_state(display_value, has_data=has_data,
                        has_match=display_value is not None or bool(matched) or undated or not candidates)
    if not has_data:
        reason = '当前空间尚未导入数据，未评估。'
    elif state == Status.NO_MATCH_DATA:
        reason = f'{day} 没有可定位的{"广告" if table == "ads" else "订单"}记录；缺日不填0。'
    elif state == Status.INSUFFICIENT_DATA:
        if not matched and undated:
            reason = '存在无法定位日期的记录，不能确认该日无业务。'
        elif not matched:
            reason = f'缺少可用的{"广告账本" if table == "ads" else "订单样本"}。'
        elif key == 'refund_rate' and result['profit_orders'] and not result['mature_orders']:
            reason = '订单队列尚未观察满12天，退款率不可评估。'
        elif key in ('gross_profit', 'contribution', 'refund_rate') and not result['profit_orders']:
            reason = '没有成本已知的有效完成订单样本；未知成本不按0计算。'
        elif key == 'orders':
            reason = '有效完成订单计数为0，但没有可用订单样本；不能据此认定业务为零。'
        elif key == 'roas':
            reason = '广告费用或归因收入不可用，或广告费用为0，ROAS不可计算。'
        elif key == 'refund_rate':
            reason = '退款账本或队列有效性不足，请查看样本与数据限制。'
        else:
            reason = '有效样本或必要费用不足，请查看样本与数据限制。'
    else:
        reason = '仅描述已导入有效样本，不证明业务账本完整。'
        if key == 'orders' and value == 0:
            reason = '有效完成订单为0笔；存在可用订单记录，但不证明业务账本收齐。'
    if state == Status.NORMAL and (result['partial'] or result['missing_refunds']):
        state = Status.WARNING
    return {'state': state, 'reason': reason}


def compare(key, kind, current, previous, states, previous_states):
    if states[key]['state'] not in AVAILABLE or previous_states[key]['state'] not in AVAILABLE:
        return {'value': None, 'state': Status.INSUFFICIENT_DATA,
                'text': f"不可比较：D日{TEXT[states[key]['state']]}，D−1日{TEXT[previous_states[key]['state']]}；不补0或替换比较日。"}
    now_value, old_value = current[key], previous[key]
    if kind == 'sales_rate' and old_value == 0:
        return {'value': None, 'state': Status.NOT_APPLICABLE,
                'text': '环比增长率不适用：D−1销售额为0，不计算普通增长率。'}
    change = ((now_value - old_value) / old_value if kind == 'sales_rate'
              else now_value - old_value)
    direction = '增加' if change > 0 else '减少' if change < 0 else '持平'
    if kind == 'sales_rate':
        text = f'销售额环比{direction} {percent(abs(change))}'
    elif kind == 'points':
        text = '退款订单率较前日' + percentage_points(change)
    elif kind == 'multiple':
        text = f'ROAS较前日{direction} {roas(abs(change))}；不代表整体盈利变化。'
    elif kind == 'count':
        text = f'有效完成订单较前日{direction} {abs(change)} 笔'
    else:
        text = f'金额较前日{direction} {money(abs(change))}'
        if any(r['partial'] or r['missing_refunds'] for r in (current, previous)):
            text += '；仅可计算样本，不代表全部订单利润变化。'
    return {'value': change, 'state': Status.NORMAL, 'text': text}


def build_daily_report(store, workspace, day=None, horizon=None, *, center=None, current_date=None):
    current_date = current_date or today()
    center = center or MetricCenter(store)
    facts = center.facts(workspace)
    day = date.fromisoformat(str(day)) if day is not None else default_day(facts, current_date)
    horizon = date.fromisoformat(str(horizon)) if horizon is not None else current_date
    if not date.min < day < current_date:
        raise ValueError('经营日必须为已结束日期，且能够计算前一自然日。')
    if not day <= horizon <= current_date:
        raise ValueError('退款观察截止日必须在经营日至今天之间。')
    previous_day = day - timedelta(days=1)
    has_data = workspace_has_data(store, workspace)
    current = center.calculate(workspace, day, day, as_of=horizon)
    previous = center.calculate(workspace, previous_day, previous_day, as_of=horizon)
    states = {key: metric_status(key, current, facts, day, has_data) for key, _, _ in KPIS}
    previous_states = {key: metric_status(key, previous, facts, previous_day, has_data) for key, _, _ in KPIS}
    # Global quality status is navigation context, never a daily anomaly count.
    rows = prepare(store.anomalies(workspace))
    active = rows[rows.active.eq(1)]
    quality = summarize(active, active)
    report = {
        'workspace': workspace, 'day': day, 'previous_day': previous_day, 'horizon': horizon,
        'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')), 'has_data': has_data,
        'current': current, 'previous': previous, 'states': states, 'previous_states': previous_states,
        'comparisons': {key: compare(key, kind, current, previous, states, previous_states)
                        for key, _, kind in KPIS},
        'has_quality_issues': bool(quality['有效异常条数']),
        'has_quality_blocks': bool(quality['直接阻断记录数']),
    }
    report['history'] = read_history(store, workspace, day)
    report['guidance'] = build_guidance(report)
    return report
