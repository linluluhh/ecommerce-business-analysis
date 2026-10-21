"""Read saved detections and produce deterministic guidance; never run detection."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import re

from v2.ui_format import rule_value, timestamp


HISTORY_LIMIT = ('历史触发，不代表当前仍触发；当前处理状态不是报告日当时的状态。'
                 '经营指标按当前有效数据重算，历史证据保留当时版本，两者可能不同。'
                 '历史证据不足以证明该日所有规则均已检测；未保存触发不等于无异常。')
KINDS = {'stock_low','stock_cover','stock_trend','sales_drop','margin_drop','contribution_drop',
         'unknown_cost_up','roas_low','ad_spend_up','roas_drop','refund_rate_high','refund_sku','refund_platform_up'}


def public_text(value):
    """Export business text, not machine paths; never include actor/raw-file fields."""
    text = str(value) if value is not None else '历史证据不足'
    return re.sub(r'(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|/(?:home|Users|users|tmp|var|mnt|etc)/)[^\r\n<>]*',
                  '[本地路径已隐藏]', text)


def strings(value):
    return [public_text(v) for v in value if isinstance(v, str)] if isinstance(value, list) else []


def object_json(value):
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def valid_date(value):
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def finite(value):
    try:
        return Decimal(str(value)).is_finite()
    except (InvalidOperation, ValueError):
        return False


def read_history(store, workspace, day):
    rows = store.query('''SELECT d.id AS detection_id,d.alert_id,d.metric_value,d.evidence_json,d.created_at,
        a.rule_id,a.rule_version,a.rule_snapshot,a.object_key,a.status
        FROM alert_detections d JOIN alerts a ON a.id=d.alert_id
        WHERE a.workspace=? ORDER BY d.id''', (workspace,))
    latest, incomplete = {}, 0
    for row in rows.to_dict('records'):
        evidence = object_json(row['evidence_json'])
        period = evidence.get('period')
        if not isinstance(period, dict) or not valid_date(period.get('end')):
            incomplete += 1
            continue
        if period['end'] != str(day):
            continue
        rule = object_json(row['rule_snapshot'])
        try:
            saved_at = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            if saved_at.tzinfo is None:
                raise ValueError('No proven timezone')
            order = (saved_at.timestamp(), row['detection_id'])
        except (ValueError, TypeError, AttributeError):
            incomplete += 1
            continue
        complete = (valid_date(period.get('start')) and period['start'] <= period['end']
                    and rule.get('id') == row['rule_id'] and rule.get('version') == row['rule_version']
                    and rule.get('workspace') == workspace and rule.get('kind') in KINDS
                    and bool(rule.get('name')) and finite(rule.get('threshold'))
                    and finite(row['metric_value']) and bool(evidence.get('formula'))
                    and valid_date(evidence.get('as_of')) and evidence.get('object') == row['object_key'])
        kind = rule.get('kind') if rule.get('kind') in KINDS else None
        batch_ids = [v for v in evidence.get('data_sources', [])
                     if isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', v)] if isinstance(evidence.get('data_sources'), list) else []
        entry = {
            'detection_id': row['detection_id'], 'alert_id': row['alert_id'],
            'rule_id': row['rule_id'], 'version': row['rule_version'], 'kind': kind,
            'name': public_text(rule.get('name')), 'severity': public_text(rule.get('severity')),
            'object': public_text(row['object_key']), 'start': public_text(period.get('start')), 'end': period['end'],
            'saved_at': timestamp(saved_at), 'as_of': public_text(evidence.get('as_of')),
            'status': public_text(row['status']), 'complete': bool(complete),
            'value': rule_value(kind, row['metric_value']) if kind else '历史证据不足',
            'threshold': rule_value(kind, rule.get('threshold')) if kind else '历史证据不足',
            'formula': public_text(evidence.get('formula')), 'basis': public_text(evidence.get('what')),
            'checklist': strings(evidence.get('checklist')), 'limits': strings(evidence.get('limits')),
            'batch_ids': batch_ids,
        }
        key = (row['rule_id'], row['rule_version'], row['object_key'], str(period.get('start')), period['end'])
        if key not in latest or order > latest[key][0]:
            latest[key] = (order, entry)
    entries = [item[1] for item in sorted(latest.values(), key=lambda item: item[0], reverse=True)]
    incomplete += sum(not e['complete'] for e in entries)
    message = ('已展示观测期截至报告日的最新留存触发证据，不等于最新一次检测结果。' if entries else
               '未找到检测证据，请前往智能预警查看或手动运行检测。' if rows.empty else
               '暂无截至该日的已保存触发证据，不能据此认定无异常。')
    if incomplete:
        message += ' 历史证据不足：当前空间存在缺失或无法核验的窗口、快照或时间；不能据此补推历史结论。'
    return {'entries': entries, 'message': message, 'incomplete': incomplete, 'limits': HISTORY_LIMIT}


def build_guidance(report):
    suggestions = []
    for e in report['history']['entries']:
        if not e['complete']:
            continue
        kind = e['kind']
        if kind.startswith('stock_'):
            action = '核查库存快照、覆盖天数、补货周期及已知在途信息，不推算未提供的在途数量。'
        elif kind in ('roas_low','roas_drop','ad_spend_up'):
            action = '核查广告账单、归因口径及商品组合，不直接据此增加预算。'
        elif kind.startswith('refund_'):
            action = '核查历史成熟观察窗口、批准退款及售后凭证，不将当前未成熟样本解释为经营恶化。'
        elif kind == 'sales_drop':
            action = '在经营分析中核对相同窗口的平台和SKU销售变化、订单隔离与活动记录，不推定下降原因。'
        else:
            action = '先核查成本覆盖率、成本修订及费用完整性，再核对活动与相关账单。'
        suggestions.append({'title': '历史证据核查：' + e['name'],
            'basis': f"检测证据 #{e['detection_id']}；规则 #{e['rule_id']} v{e['version']}；{e['start']} 至 {e['end']}；值 {e['value']}，阈值 {e['threshold']}",
            'object': e['object'], 'action': '；'.join(e['checklist'] + [action]),
            'limit': f"当前处理状态：{e['status']}；" + ('仅作复核参考，不计新待办。' if e['status'] in ('已解决','已忽略') else '仅为核查建议，不自动生成待办。') + HISTORY_LIMIT})
    # These are current-data usability reminders, not new business alert rules.
    for label, result in (('D日', report['current']), ('D−1日', report['previous'])):
        if result['unknown_orders']:
            suggestions.append({'title': f'{label}成本证据待补充', 'basis': f"当前重算样本中成本未知订单 {result['unknown_orders']} 笔。",
                'object': '利润样本', 'action': '在质量检查中核对商品成本与凭证，按既有修订审批流程处理。',
                'limit': '未知成本不填0，当前利润差额不能代表全部订单利润变化。'})
        if result['profit_orders'] > result['mature_orders']:
            suggestions.append({'title': f'{label}退款样本尚未成熟', 'basis': f"成本已知订单 {result['profit_orders']} 笔，成熟样本 {result['mature_orders']} 笔；H={report['horizon']}。",
                'object': '12天退款订单率', 'action': '核对观察截止日并待样本成熟后复核，不使用未成熟退款率判断经营恶化。',
                'limit': '这是当前数据使用提醒，不是历史预警或新检测结论。'})
    if not report['history']['entries'] or report['history']['incomplete']:
        suggestions.append({'title': '核查历史证据范围', 'basis': report['history']['message'], 'object': '历史检测证据',
            'action': '在智能预警中查看检测参考日、规则版本及实际观测窗口；需要新检测时由用户手动运行。',
            'limit': '不生成无证据支持的库存、广告或销售异常结论。'})
    return suggestions
