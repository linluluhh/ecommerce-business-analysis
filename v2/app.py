from pathlib import Path
import os
import sys
import importlib
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from v2.service import Store
from v2.rules import SCHEMAS
from v2.metrics import MetricCenter
from v2.demo import error_csv
from v2.ui_status import Status, TEXT, workspace_has_data, render_status, quality_status, value_state
from v2.ui_format import money, display_times

st.set_page_config(page_title='跨境电商 · 智能经营监控 V2',page_icon='📊',layout='wide')
st.markdown('''<style>.stApp{background:#f6f8fc}h1{letter-spacing:-1px}
[data-testid="stMetric"]{background:white;padding:18px;border-radius:12px;border:1px solid #e5eaf2}
[data-testid="stSidebar"]{background:#eaf0f8}</style>''',unsafe_allow_html=True)
store = Store(os.environ.get('V2_DATA_DIR',str(Path(__file__).with_name('runtime'))))
if getattr(store,'api_version',0)<3:
    service=importlib.reload(importlib.import_module('v2.service'))
    for module in ('v2.metrics','v2.revisions','v2.alerts','v2.phase2_ui'):
        if module in sys.modules:
            importlib.reload(sys.modules[module])
    store=service.Store(store.root)
with st.sidebar:
    st.title('经营监控 V2')
    st.caption('第二阶段 · 经营指标与规则预警')
    space = st.radio('数据空间',['模拟演示','业务数据','第二阶段独立模拟演示'])
    workspace = 'business' if space=='业务数据' else 'demo'
    if space=='第二阶段独立模拟演示':
        store=Store(store.root/'phase2_demo')
    actor = st.text_input('操作员',value='本地操作员')
    section=st.radio('功能导航',['数据运营工作台','经营分析','经营日报','智能预警','数据修订','规则配置'])
    st.divider()
    st.info('USD · 单 SKU 订单\n\n收入、退款确认月及成本口径沿用 V1。')
    st.caption('模拟演示和业务数据独立保存。业务空间从空库开始，请上传自己的主数据。')
    st.caption('第二阶段独立模拟演示使用单独数据库，避免与第一阶段商品/库存模拟场景冲突；不删除任何已有场景。')

st.title('跨境电商智能经营监控与自动化预警')
st.caption(f'{space} / 数据质量 → 异常隔离 → 人工审核 → 有效样本经营指标')
# Keep a stable container position so a flash disappearing cannot reset the tab.
with st.container():
    if 'flash' in st.session_state:
        result = st.session_state.pop('flash')
        if result['status']=='failed':
            st.error('导入失败，原文件和失败日志已保留：'+result['error'])
        elif result['status']=='duplicate':
            st.warning('识别到重复上传：新增 0 条记录，订单及金额保持不变。')
            st.caption(f"本次批次 {result['batch_id']} · 重复来源 {result['duplicate_of']}。当前指标累计全部已导入批次。")
        else:
            st.success(f"导入完成：新增 {result['added']} 条；跳过 {result['duplicates']} 条相同业务记录。")

if section=='经营日报':
    from v2.daily_report_ui import render_daily_report
    render_daily_report(store,workspace,space)
    st.stop()

m = store.metrics(workspace)
# Streamlit can rerun app.py while retaining an older imported service module.
# Upgrade the backend contract before rendering newly introduced fields.
if 'sales_records' not in m:
    service = importlib.reload(importlib.import_module('v2.service'))
    store = service.Store(store.root)
    m = store.metrics(workspace)
if section!='数据运营工作台':
    from v2.phase2_ui import render
    render(store,workspace,actor,section)
    st.stop()
has_data = workspace_has_data(store, workspace)
strict_display = MetricCenter(store).calculate(workspace)
if not has_data:
    render_status(Status.EMPTY_DATA, '未评估：请先导入数据。')
cards = st.columns(5)
for col,label,value in zip(cards,['有效订单','折后销售额 USD','商品毛利 USD','隔离记录','待核实异常'],
                           [m['orders'],money(m['sales'], value_state(strict_display['sales'], has_data=has_data)),money(m['gross_profit'], value_state(m['gross_profit'] if m['profit_orders'] else None, has_data=has_data)),m['isolated_records'],m['unreviewed']]):
    col.metric(label,value)
st.warning('当前展示临时有效样本。未审核和已确认异常继续隔离；硬性金额、业务键或缺失值错误即使驳回也不放行。未知 SKU 保留有效收入、隔离利润。缺失客户不删除收入。')
st.caption(f"成本已知订单 {m['profit_orders']} 笔 · 未知成本利润隔离 {m['profit_isolated']} 条 · "
           f"已记录有效广告费：{money(m['recorded_ad_cost'], value_state(m['recorded_ad_cost'], has_data=has_data))} · "
           f"经营贡献利润（部分样本，非净利润）：{money(m['contribution'] if m['profit_orders'] else None, value_state(m['contribution'] if m['profit_orders'] else None, has_data=has_data))}")
with st.expander('逐笔销售额来源（当前空间全部有效批次）'):
    if 'sales_records' not in m:
        st.warning('后端版本尚未更新，逐笔来源暂不可用。请重启应用；当前经营指标和历史数据保留。')
    elif m['sales_records']:
        lineage = pd.DataFrame(m['sales_records']).copy()
        lineage['sales'] = lineage['sales'].map(money)
        st.dataframe(lineage.rename(columns={'order_id':'订单编号','month':'月份','sku':'SKU','sales':'计入销售额 USD',
                     'profit_included':'计入利润样本','source_file':'来源文件','batch_id':'来源批次','source_row':'源文件行号',
                     'record_id':'记录ID'}),width='stretch',hide_index=True)
    else:
        render_status(Status.INSUFFICIENT_DATA if has_data else Status.EMPTY_DATA, '当前没有可确认的销售记录。')
upload_tab,quality_tab,review_tab,ledger_tab = st.tabs(['数据导入','质量检查','异常审核','批次与日志'])

with upload_tab:
    st.subheader('上传业务数据')
    st.write('CSV 选择对应业务表；单表 Excel 选择对应表；多表 Excel 选择 workbook，工作表名使用业务表名。')
    kind = st.selectbox('业务表类型',list(SCHEMAS)+['workbook'])
    uploaded = st.file_uploader('选择 CSV 或 Excel 文件',type=['csv','xlsx'])
    if not actor.strip():
        st.error('请在左侧填写操作员后导入或审核。')
    if st.button('导入上传文件',type='primary',disabled=uploaded is None or not actor.strip()):
        st.session_state.flash = store.ingest(uploaded.name,uploaded.getvalue(),kind,workspace,actor)
        st.rerun()
    template = SCHEMAS['orders' if kind=='workbook' else kind]
    st.download_button('下载字段模板 CSV',pd.DataFrame(columns=template).to_csv(index=False).encode('utf-8-sig'),file_name=f'{kind}_template.csv')
    if workspace=='demo':
        st.divider()
        st.subheader('三种模拟测试场景')
        st.caption('正常场景：销售额 35、毛利 19、9月贡献 10、10月确认退款 5、跨月合计贡献 5。')
        st.info('上述预期适用于空演示空间只导入正常数据。三个场景累计保存在同一空间；正常/重复按钮不会清空历史。错误场景的 UNKNOWN_SKU 订单另计收入 35、隔离利润，累计销售额可为 70、9月贡献仍为 10。')
        a,b,c = st.columns(3)
        # Use bundled immutable fixture for byte-identical repeated uploads.
        fixture = Path(__file__).with_name('demo_data')/'normal.xlsx'
        if a.button('1 · 导入正常数据',disabled=not actor.strip()):
            st.session_state.flash = store.ingest('normal.xlsx',fixture.read_bytes(),'workbook',workspace,actor)
            st.rerun()
        if b.button('2 · 重复上传',disabled=not actor.strip()):
            st.session_state.flash = store.ingest('duplicate.xlsx',fixture.read_bytes(),'workbook',workspace,actor)
            st.rerun()
        if c.button('3 · 导入错误数据',disabled=not actor.strip()):
            st.session_state.flash = store.ingest('errors.csv',error_csv(),'orders',workspace,actor)
            st.rerun()
    st.subheader('按月有效样本')
    if m['monthly']:
        from v2.metrics import MetricCenter
        center=MetricCenter(store)
        rows={}
        for month in m['monthly']:
            start=pd.Timestamp(month+'-01');end=start+pd.offsets.MonthEnd(0)
            strict=center.calculate(workspace,str(start.date()),str(end.date()))
            rows[month]={key:strict[key] for key in ('sales','known_cost_sales','gross_profit','refund_cost','recorded_ad_cost','contribution')}
        monthly=pd.DataFrame.from_dict(rows,orient='index').sort_index().map(lambda v:float(v) if v is not None else float('nan'))
        st.dataframe(monthly.map(money),width='stretch')
        st.caption('月度销售与贡献为独立指标，不相加；费用为已记录样本。')
        st.line_chart(monthly[['sales','contribution']].rename(columns={'sales':'折后销售额 USD','contribution':'暂估贡献 USD'}))
    else:
        render_status(Status.INSUFFICIENT_DATA if has_data else Status.EMPTY_DATA, '尚无可确认的经营样本。')

issues = store.anomalies(workspace)
with quality_tab:
    from v2.quality_ui import render_quality
    render_quality(issues, has_data, str(store.root)+workspace, space)

with review_tab:
    st.subheader('异常审核工作台')
    st.write('确认 = 异常确实存在，继续隔离；驳回 = 误报，仅软规则可放行；待核实 = 继续隔离。硬性错误需后续带证据修订，不直接改原记录。')
    current = issues[(issues.active.eq(1)) & (issues.scope.ne('none'))] if not issues.empty else issues
    status_filter = st.selectbox('审核状态筛选',['全部','待核实','确认','驳回'])
    if status_filter!='全部' and not current.empty:
        current = current[current.status.eq(status_filter)]
    if current.empty:
        render_status(Status.NO_MATCH_DATA if has_data else Status.EMPTY_DATA, '当前筛选下没有待处理异常。')
    else:
        choice = st.selectbox('选择异常',current.id.tolist(),format_func=lambda idx: f"#{idx} · {current.set_index('id').loc[idx,'code']} · {current.set_index('id').loc[idx,'business_key']}")
        item = current.set_index('id').loc[choice]
        st.write('异常原因：'+item.reason)
        st.caption(f'影响字段：{item.fields} · 严重程度：{item.severity} · 原文件行号：{int(item.source_row)}')
        with st.expander('原始记录与技术来源详情'):
            st.json({'原始值':json.loads(item.raw_json),'批次':item.batch_id,'原文件行号':int(item.source_row),'硬性隔离':bool(item.hard)})
        with st.form('review_form'):
            status = st.selectbox('审核结论',['待核实','确认','驳回'])
            note = st.text_area('处理说明（必填）')
            submit = st.form_submit_button('保存审核',type='primary')
        if submit:
            try:
                store.review(int(choice),status,note,actor,int(item.version),workspace)
                st.session_state['review_saved'] = True
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if st.session_state.pop('review_saved',False):
        st.success('审核已保存，处理说明和操作日志已留存。')
    reviews = store.query('SELECT rev.* FROM reviews rev JOIN anomalies a ON rev.anomaly_id=a.id JOIN records r ON a.record_id=r.id WHERE r.workspace=? ORDER BY rev.id DESC',(workspace,))
    st.dataframe(display_times(reviews),width='stretch',hide_index=True)

with ledger_tab:
    st.subheader('历史批次（不覆盖）')
    batches = store.query('SELECT * FROM batches WHERE workspace=? ORDER BY created_at DESC',(workspace,))
    st.dataframe(display_times(batches),width='stretch',hide_index=True)
    if not batches.empty:
        batch_id = st.selectbox('下载原始上传文件',batches.id.tolist())
        item = batches.set_index('id').loc[batch_id]
        path = store.root / item.raw_path
        st.download_button('下载原文件',path.read_bytes(),file_name=item.filename)
    st.subheader('操作日志（追加保存）')
    logs = store.query('SELECT * FROM operation_logs WHERE workspace=? ORDER BY id DESC',(workspace,))
    st.dataframe(display_times(logs),width='stretch',hide_index=True)
    if workspace=='demo':
        st.divider()
        st.subheader('第二阶段 · Synthetic / 14天模拟业务')
        st.caption('含两个7天可比窗口、库存、广告、退款、未知成本及负价异常；累计导入当前演示空间，不清空历史。')
        fixture=Path(__file__).with_name('demo_data')/'phase2_synthetic.xlsx'
        if st.button('导入14天第二阶段模拟数据',disabled=not actor.strip()):
            st.session_state.flash=store.ingest(fixture.name,fixture.read_bytes(),'workbook',workspace,actor)
            st.rerun()
