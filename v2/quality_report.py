"""On-demand quality reports and guidance; no writes or workflow transitions."""
from datetime import datetime
from html import escape
import json
from zoneinfo import ZoneInfo

from v2.rules import policy, GRAINS
from v2.ui_status import Status, TEXT

from v2.quality_presentation import TABLE_NAMES
FILTER_NAMES = {'table_name':'业务表', 'batch_id':'来源批次', '异常分类':'异常分类', 'status':'审核状态'}
LIMITS = [
    '基于 Synthetic 模拟业务场景的作品集；当前报告仅描述所选空间已导入数据，不代表真实企业收益或账本完整性。',
    '摘要仅统计有效异常，明细是否包含历史由历史开关决定；异常条数与去重记录数不同，分类记录数不可相加。',
    '记录当前作用依据该记录全部有效规则判定；直接阻断数不包含推算的下游关联影响。',
    '确认异常不等于修复；驳回仅可能放行软规则，硬性错误仍阻断。不估算损失金额或综合质量评分。',
    '来源批次选项来自异常证据；不按业务日期筛选，保留无法解析日期的异常。',
]


def guidance(row):
    """Explain existing UI paths without offering forbidden key-field edits."""
    if not row['active']:
        return '历史异常已失效，仅供追溯。若要核查当前问题，请关闭历史开关查看有效异常。'
    scope, hard, _ = policy(row['code'], row['table_name'])
    keys = set(GRAINS[row['table_name']][0])
    fields = set(str(row['fields']).split(','))
    if row['code'] in ('business_key_conflict', 'missing_business_key') or fields & keys:
        return '先核对源文件和业务键。现有数据修订不支持修改业务键；不要重复上传覆盖，也不要通过驳回硬性错误放行。'
    if scope == 'none':
        return '当前规则不阻断收入。请核查格式或关联主数据；此类提示不进入现有异常审核列表。'
    if hard:
        return (f"核对源文件与凭证后，打开左侧“数据修订”，选择记录 #{row['record_id']}，"
                f"关联异常 #{row['id']}。填写修订原因和凭证，提交后仍需审批；批准后重新质检，不能保证直接放行。")
    return (f"打开本工作台“异常审核”标签，将审核状态筛选设为“全部”，选择异常 #{row['id']}。"
            '核对后填写处理说明；确认表示问题存在，驳回仅对本条软规则生效，其他有效规则仍可能阻断。')


def build_report(view, summary, filters, workspace_label, has_data, has_active, include_history, generated_at=None):
    state = (Status.EMPTY_DATA if not has_data else Status.WARNING if summary['有效异常条数']
             else Status.NO_MATCH_DATA if has_active else Status.NORMAL)
    generated_at = generated_at or datetime.now(ZoneInfo('Asia/Shanghai'))
    if generated_at.tzinfo is None:
        raise ValueError('Report timestamp must be timezone-aware')
    counts = {k:int(summary[k]) for k in ('有效异常条数','受影响记录数','待核实异常数','直接阻断记录数')}
    evidence = json.loads(view.to_json(orient='records',force_ascii=False))
    for row in evidence:
        row['处理建议'] = guidance(row)
    return {
        '报告名称':'数据质量报告', '报告版本':'V2.1', '数据空间':workspace_label,
        '生成时间':generated_at.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'),
        '时区':'Asia/Shanghai', '数据状态':TEXT[state],
        '筛选条件':{FILTER_NAMES[k]: (v if v is not None else '全部') for k,v in filters.items()},
        '明细包含历史':bool(include_history), '当前摘要':counts,
        '分类统计':summary['categories'], '记录影响':summary['effects'],
        '证据明细':evidence, '口径与限制':list(LIMITS),
    }


def report_html(report):
    """Standalone escaped HTML. Imported data is text, never executable markup."""
    def value(item):
        return escape(str(item), quote=True)
    def table(rows, columns):
        if not rows:
            return '<p>当前范围没有相应记录。</p>'
        return '<table><thead><tr>' + ''.join('<th>'+value(c)+'</th>' for c in columns) + '</tr></thead><tbody>' + ''.join(
            '<tr>' + ''.join('<td>'+value(row.get(c,''))+'</td>' for c in columns) + '</tr>' for row in rows) + '</tbody></table>'
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>数据质量报告</title>',
             '<style>body{font:16px sans-serif;max-width:1200px;margin:32px auto;padding:16px;color:#182638}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd4df;padding:8px;text-align:left;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{margin-top:32px}</style>',
             '<h1>数据质量报告 · V2.1</h1>']
    for key in ('数据空间','生成时间','时区','数据状态','明细包含历史'):
        parts.append('<p>'+value(key)+'：'+value(report[key])+'</p>')
    parts.append('<h2>筛选条件</h2>'+table([report['筛选条件']],list(report['筛选条件'])))
    parts.append('<h2>当前有效异常摘要</h2>'+table([report['当前摘要']],list(report['当前摘要'])))
    parts.append('<h2>分类统计</h2>'+table(report['分类统计'],['异常分类','异常条数','受影响记录数']))
    parts.append('<h2>记录影响</h2>'+table(report['记录影响'],['记录ID','业务表','记录当前作用','业务影响说明']))
    parts.append('<h2>口径与限制</h2><ul>'+''.join('<li>'+value(v)+'</li>' for v in report['口径与限制'])+'</ul>')
    parts.append('<h2>证据与处理建议</h2>')
    if not report['证据明细']:
        parts.append('<p>当前筛选没有证据明细。</p>')
    for row in report['证据明细']:
        parts.append('<details><summary>异常 #'+value(row['id'])+' · '+value(row['reason'])+'</summary>')
        parts.append('<p>'+value(row['处理建议'])+'</p><pre>'+value(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details>')
    parts.append('</html>')
    return ''.join(parts).encode('utf-8')
