"""Public daily-report view and offline HTML; consumes one assembled report only."""
from html import escape

from v2.daily_report import KPIS, formatted
from v2.daily_evidence import public_text
from v2.metrics import DEFINITIONS
from v2.ui_format import percent, timestamp
from v2.ui_status import quality_status, TEXT


NOTES = [
    'Synthetic 模拟业务场景；按当前有效数据版本重算，不是还原历史当天已知信息。',
    '范围：当前空间全部平台、SKU和国家；USD、单SKU订单。经营日不是生成日或导入日。',
    '两日使用同一退款观察截止日H；H仅影响12天退款队列，不是全部数据的历史截断日。',
    '确认退款按确认日、退款率按下单队列；暂估贡献不是净利润。',
    '严格D对D−1，缺日不补0；销售零基期不算增长率，利润用金额差，退款率用百分点，ROAS用倍数差。',
    '订单可用率不是综合质量评分；0笔和未发现异常均不证明账本收齐。',
    '建议是确定性核查模板，不是AI分析、根因判断或财务损失估计；下载不运行检测、审核或审批。',
]


def sample_lines(result):
    return [f"有效完成订单：{result['orders']} 笔；成本已知订单：{result['profit_orders']} 笔；成熟退款样本：{result['mature_orders']} 笔。",
            f"成本覆盖率：{percent(result['cost_coverage'])}；订单可用率：{percent(result['data_completeness'])}。",
            f"未知成本订单：{result['unknown_orders']} 笔；确认期间隔离退款：{result['missing_refunds']} 条；隔离/缺失广告记录：{result['missing_ads']} 条。"]


def public_view(report, workspace_label):
    kpis = [{'指标': label, 'D日': formatted(key, report['current'][key], report['states'][key]['state']),
             'D−1日': formatted(key, report['previous'][key], report['previous_states'][key]['state']),
             '比较': report['comparisons'][key]['text'], 'D日说明': report['states'][key]['reason'],
             'D−1日说明': report['previous_states'][key]['reason']} for key, label, _ in KPIS]
    state, detail = quality_status(report['has_data'], report['has_quality_issues'])
    # Explicit allowlist: do not serialize the metric details, source files, actors or paths.
    return {'space': public_text(workspace_label), 'day': str(report['day']), 'previous_day': str(report['previous_day']),
            'horizon': str(report['horizon']), 'generated_at': timestamp(report['generated_at']), 'kpis': kpis,
            'samples': [{'label': label, 'date': r['filters']['start'], 'lines': sample_lines(r),
                         'limits': [public_text(v) for v in r['limits']]} for label, r in (('D日', report['current']), ('D−1日', report['previous']))],
            'quality': TEXT[state] + '；' + detail + ' 当前空间整体情况，不是当日异常统计。请在数据运营工作台的质量检查中查看证据。',
            'history': report['history'], 'guidance': report['guidance'], 'notes': NOTES,
            'definitions': [{'指标': label, '公式': DEFINITIONS[key][1], '范围': DEFINITIONS[key][2]} for key, label, _ in KPIS]}


def report_html(view):
    def text(value):
        return escape(public_text(value), quote=True)
    def table(rows, columns, table_id=''):
        return ('<div class="table-wrap"><table' + (f' id="{table_id}"' if table_id else '') + '><thead><tr>' +
                ''.join('<th>'+text(c)+'</th>' for c in columns) + '</tr></thead><tbody>' +
                ''.join('<tr>'+''.join('<td>'+text(row.get(c,''))+'</td>' for c in columns)+'</tr>' for row in rows) +
                '</tbody></table></div>')
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>经营日报 · V2.1</title>',
             '<style>body{font:16px/1.6 sans-serif;max-width:1200px;margin:24px auto;padding:16px;color:#182638;background:#f6f8fc}h1,h2{line-height:1.3}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #ccd4df;padding:10px;vertical-align:top;overflow-wrap:anywhere}.table-wrap{overflow-x:auto}p,li,summary{overflow-wrap:anywhere}article,details{background:white;padding:16px;margin:12px 0;border:1px solid #ccd4df;border-radius:8px}small{color:#536176}@media(max-width:640px){body{padding:12px;margin:0}th,td{min-width:100px}}</style></head><body><h1>经营日报 · V2.1</h1>']
    for label, key in (('数据空间','space'), ('报告经营日D','day'), ('对比日D−1','previous_day'), ('退款观察截止日H','horizon'), ('生成时间（Asia/Shanghai）','generated_at')):
        parts.append('<p>'+label+'：'+text(view[key])+'</p>')
    parts.append('<h2>范围与重要解释</h2><ul>'+''.join('<li>'+text(n)+'</li>' for n in view['notes'])+'</ul>')
    parts.append('<h2>当日表现与前一日比较</h2>'+table(view['kpis'],['指标','D日','D−1日','比较','D日说明','D−1日说明'],'daily-kpis'))
    parts.append('<h2>样本与数据限制</h2>')
    for sample in view['samples']:
        parts.append('<article><h3>'+text(sample['label']+' · '+sample['date'])+'</h3>'+''.join('<p>'+text(v)+'</p>' for v in sample['lines'])+'<ul>'+''.join('<li>'+text(v)+'</li>' for v in sample['limits'])+'</ul></article>')
    parts.append('<p>'+text(view['quality'])+'</p><h2>观测期截至D日的历史预警证据</h2>')
    parts.append('<p>'+text(view['history']['message'])+'</p><p>'+text(view['history']['limits'])+'</p>')
    for e in view['history']['entries']:
        parts.append('<details><summary>'+text(f"证据 #{e['detection_id']} · {e['name']} · {e['object']}")+'</summary>')
        details = {'预警ID':e['alert_id'], '检测证据ID':e['detection_id'], '规则ID':e['rule_id'], '规则版本':e['version'],
                   '类型':e['kind'], '严重程度':e['severity'], '观测窗口':e['start']+' 至 '+e['end'],
                   '证据保存时间（Asia/Shanghai）':e['saved_at'], '检测参考日':e['as_of'], '历史指标值':e['value'],
                   '历史阈值':e['threshold'], '公式':e['formula'], '触发依据':e['basis'],
                   '当前处理状态（非D日状态）':e['status'], '来源批次ID':', '.join(e['batch_ids']),
                   '证据完整性':'可核验留存证据' if e['complete'] else '历史证据不足'}
        parts.extend('<p>'+text(k)+'：'+text(v)+'</p>' for k,v in details.items())
        parts.append('<ul>'+''.join('<li>'+text(v)+'</li>' for v in e['limits'])+'</ul></details>')
    parts.append('<h2>运营关注与核查建议</h2>')
    for item in view['guidance']:
        parts.append('<article><h3>'+text(item['title'])+'</h3>'+''.join('<p>'+label+'：'+text(item[key])+'</p>' for label,key in [('依据','basis'),('对象','object'),('建议核查','action'),('限制','limit')])+'</article>')
    parts.append('<h2>指标口径</h2>'+table(view['definitions'],['指标','公式','范围'])+'</body></html>')
    return ''.join(parts).encode('utf-8')
