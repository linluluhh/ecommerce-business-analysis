"""Daily report C1 UI: dates, shared metrics, comparisons and sample limitations."""
from datetime import date, timedelta
import streamlit as st

from v2.daily_report import KPIS, AVAILABLE, default_day, build_daily_report, formatted
from v2.daily_report_export import public_view, report_html, sample_lines
from v2.metrics import MetricCenter, today
from v2.ui_format import money, percent, roas, timestamp
from v2.ui_status import TEXT, render_status, quality_status


STYLE = '''<style>
.st-key-daily_kpis [data-testid="stHorizontalBlock"] {
 display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;
}
.st-key-daily_kpis [data-testid="stColumn"] {width:100%!important;min-width:0!important}
.st-key-daily_kpis [data-testid="stMetricValue"],
.st-key-daily_kpis [data-testid="stMetricValue"] * {
 font-size:clamp(1.2rem,2vw,1.9rem)!important;font-variant-numeric:tabular-nums;
 white-space:normal!important;overflow:visible!important;overflow-wrap:anywhere;
}
@media(max-width:1100px){.st-key-daily_kpis [data-testid="stHorizontalBlock"] {
 grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:640px){.st-key-daily_kpis [data-testid="stHorizontalBlock"] {
 grid-template-columns:minmax(0,1fr);}}
</style>'''


def render_daily_report(store, workspace, workspace_label):
    st.subheader('经营日报 · USD')
    st.caption('Synthetic 模拟业务场景 · 按当前有效数据版本重算，不是还原历史当天已知信息。')
    st.markdown(STYLE, unsafe_allow_html=True)
    center = MetricCenter(store)
    facts = center.facts(workspace)
    current_date = today()
    namespace = str(store.root) + workspace
    dkey, hkey = 'daily_day_' + namespace, 'daily_horizon_' + namespace
    saved = st.session_state.get('daily_range_' + namespace, {})
    if saved.get('empty') and facts['candidates']:
        # An empty-space fallback must not hide the first imported business dates.
        for key in (dkey, hkey):
            st.session_state.pop(key, None)
        saved = {}
    initial_day = saved.get('day', default_day(facts, current_date))
    if not date.min < initial_day < current_date:
        initial_day = default_day(facts, current_date)
    if dkey in st.session_state and not date.min < st.session_state[dkey] < current_date:
        del st.session_state[dkey]
    left, right = st.columns(2)
    day = left.date_input('经营日期 D', value=initial_day,
                          min_value=date.min+timedelta(days=1), max_value=current_date-timedelta(days=1),
                          key=dkey, format='YYYY-MM-DD')
    if hkey in st.session_state and not day <= st.session_state[hkey] <= current_date:
        del st.session_state[hkey]
    initial_horizon = saved.get('horizon', current_date)
    if not day <= initial_horizon <= current_date:
        initial_horizon = current_date
    horizon = right.date_input('退款观察截止日 H', value=initial_horizon, min_value=day,
                               max_value=current_date, key=hkey, format='YYYY-MM-DD')
    report = build_daily_report(store, workspace, day, horizon, center=center, current_date=current_date)
    view = public_view(report, workspace_label)
    # Non-widget state survives Streamlit's cleanup when another space/page is selected.
    st.session_state['daily_range_' + namespace] = {'day': day, 'horizon': horizon, 'empty': not report['has_data']}
    st.info(f"数据空间：{workspace_label}；报告经营日：{day}；对比日：{report['previous_day']}。"
            '范围：当前空间全部平台、SKU和国家，按现有有效订单与费用口径。')
    st.caption(f"生成时间：{timestamp(report['generated_at'])}（Asia/Shanghai），不是业务日期或导入日期。"
               f'两日共同退款观察截止日：{horizon}；H仅影响12天退款队列，不是全部数据的历史截断日。')
    st.caption('确认退款按退款确认日计量；12天退款订单率按下单队列计量，两者不可混用。暂估贡献不是净利润。')
    st.subheader('当日表现与前一日比较')
    with st.container(key='daily_kpis'):
        for offset in (0, 3):
            for col, (key, label, _) in zip(st.columns(3), KPIS[offset:offset+3]):
                with col:
                    item, previous_item = report['states'][key], report['previous_states'][key]
                    st.metric(label, formatted(key, report['current'][key], item['state']))
                    st.caption(f"D−1（{report['previous_day']}）：" +
                               formatted(key, report['previous'][key], previous_item['state']))
                    st.write(report['comparisons'][key]['text'])
                    st.caption('D日：' + item['reason'])
                    if previous_item['state'] not in AVAILABLE:
                        st.caption('D−1日：' + previous_item['reason'])
    st.subheader('样本与数据限制')
    st.caption('订单可用率不是综合质量评分；0笔和未发现异常均不证明账本收齐。以下计数为服务返回的样本数量。')
    for col, label, result, states in zip(st.columns(2), ('D日', 'D−1日'),
                                        (report['current'], report['previous']),
                                        (report['states'], report['previous_states'])):
        with col:
            st.markdown(f"**{label} · {result['filters']['start']}**")
            for line in sample_lines(result):
                st.write(line)
            if states['orders']['state'] not in AVAILABLE:
                st.info(states['orders']['reason'])
            for limit in result['limits']:
                st.caption('• ' + limit)
    st.markdown('**质量检查入口（当前空间整体情况，不是当日异常统计）**')
    render_status(*quality_status(report['has_data'], report['has_quality_issues']))
    if report['has_quality_blocks']:
        st.caption('当前空间存在直接阻断记录；两日影响以各自样本、覆盖率和指标限制为准。')
    st.write('请在左侧选择“数据运营工作台”→“质量检查”，查看异常分类、原始证据及处理入口。')
    st.subheader('观测期截至D日的历史预警证据')
    st.info(view['history']['message'])
    st.caption(view['history']['limits'])
    for e in view['history']['entries']:
        with st.expander(f"证据 #{e['detection_id']} · {e['name']} · {e['object']}"):
            st.text(f"预警 #{e['alert_id']}；规则 #{e['rule_id']} v{e['version']}；类型 {e['kind']}；严重程度 {e['severity']}")
            st.text(f"观测窗口：{e['start']} 至 {e['end']}；证据保存时间：{e['saved_at']}（Asia/Shanghai）；检测参考日：{e['as_of']}")
            st.text(f"历史指标值：{e['value']}；历史阈值：{e['threshold']}；当前处理状态（非D日状态）：{e['status']}")
            st.text('公式：'+e['formula']+'；触发依据：'+e['basis'])
            st.text('来源批次ID：'+', '.join(e['batch_ids']))
            if not e['complete']:
                st.warning('历史证据不足，不生成该条业务核查建议。')
            for limit in e['limits']:
                st.text(limit)
    st.subheader('运营关注与核查建议')
    st.caption('确定性模板；历史证据核查与当前数据使用提醒分开列示，不自动创建待办。')
    for item in view['guidance']:
        with st.container(border=True):
            st.text(item['title'])
            for label, key in (('依据','basis'),('对象','object'),('建议核查','action'),('限制','limit')):
                st.text(label+'：'+item[key])
    with st.expander('日报指标口径与重要解释'):
        for note in view['notes']:
            st.text(note)
        for definition in view['definitions']:
            st.text('；'.join(definition.values()))
    st.download_button('下载 HTML 日报', report_html(view), file_name=f'daily_report_{day}.html', mime='text/html')
    return report
