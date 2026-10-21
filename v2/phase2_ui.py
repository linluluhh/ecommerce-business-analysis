"""Streamlit views: no business formula or threshold logic in the UI."""
from datetime import timedelta
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from v2.metrics import MetricCenter,DEFINITIONS,today
from v2.alerts import AlertEngine,FORMULAS,safe_json
from v2.revisions import Revisions,effective_rows
from v2.rules import SCHEMAS,GRAINS
from v2.ui_status import Status, TEXT, workspace_has_data, value_state, render_status
from v2.ui_format import money, percent, roas, number, rule_value, display_times
from v2.analysis_presentation import scope_summary, trend_summary, rank_rows, INTERPRETATIONS

KPI_STYLE='''<style>
.st-key-monitor_primary_kpis [data-testid="stHorizontalBlock"],
.st-key-monitor_secondary_kpis [data-testid="stHorizontalBlock"] {
    display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem;
}
.st-key-monitor_primary_kpis [data-testid="stHorizontalBlock"] {
    grid-template-columns:repeat(4,minmax(0,1fr));
}
.st-key-monitor_primary_kpis [data-testid="stColumn"],
.st-key-monitor_secondary_kpis [data-testid="stColumn"] {
    width:100% !important; min-width:0 !important;
}
.st-key-monitor_primary_kpis [data-testid="stMetricValue"],
.st-key-monitor_secondary_kpis [data-testid="stMetricValue"] {
    font-size:clamp(1.25rem,2.2vw,2rem); font-variant-numeric:tabular-nums;
}
.st-key-monitor_primary_kpis [data-testid="stMetricValue"] *,
.st-key-monitor_secondary_kpis [data-testid="stMetricValue"] * {
    font-size:inherit !important;
}
.st-key-monitor_primary_kpis [data-testid="stMetricValue"],
.st-key-monitor_primary_kpis [data-testid="stMetricValue"] *,
.st-key-monitor_secondary_kpis [data-testid="stMetricValue"],
.st-key-monitor_secondary_kpis [data-testid="stMetricValue"] *,
.st-key-monitor_primary_kpis [data-testid="stMetricLabel"] *,
.st-key-monitor_secondary_kpis [data-testid="stMetricLabel"] * {
    white-space:normal !important; overflow:visible !important;
    text-overflow:clip !important; overflow-wrap:anywhere; line-height:1.3;
}
@media(max-width:1100px) {
    .st-key-monitor_primary_kpis [data-testid="stHorizontalBlock"],
    .st-key-monitor_secondary_kpis [data-testid="stHorizontalBlock"] {
        grid-template-columns:repeat(2,minmax(0,1fr));
    }
}
@media(max-width:640px) {
    .st-key-monitor_primary_kpis [data-testid="stHorizontalBlock"],
    .st-key-monitor_secondary_kpis [data-testid="stHorizontalBlock"] {
        grid-template-columns:minmax(0,1fr);
    }
}
</style>'''


def shown(value,as_percent=False):
    return percent(value) if as_percent else money(value)


def table(rows,rename=None):
    if isinstance(rows,list):
        rows=pd.DataFrame(rows)
    if rows.empty:
        render_status(Status.NO_MATCH_DATA, '当前没有记录。');return
    display=display_times(rows)
    money_columns={'sales','known_cost_sales','gross_profit','contribution','refund_cost','recorded_ad_cost','goods_cost','shipping_cost','platform_cost','销售额','成本已知销售额','毛利','暂估贡献'}
    for col in display:
        if col in money_columns:
            display[col]=display[col].map(money)
            continue
        if col=='成本覆盖率':
            display[col]=display[col].map(percent)
            continue
        display[col]=display[col].map(lambda v:float(v) if hasattr(v,'as_tuple') else safe_json(v) if isinstance(v,(dict,list)) else v)
    st.dataframe(display.rename(columns=rename or {}),width='stretch',hide_index=True)


def render(store,workspace,actor,section):
    engine=AlertEngine(store)
    if not workspace_has_data(store, workspace):
        render_status(Status.EMPTY_DATA, '未评估：请先导入数据。')
    with st.container():
        if 'phase2_notice' in st.session_state:
            st.success(st.session_state.pop('phase2_notice'))
    st.caption('第二阶段 · 本地规则监控 · 操作员为演示审计标识，无身份认证')
    if section in ('经营分析','经营总览','经营监控'):
        dashboard(store,workspace,section)
    elif section=='智能预警':
        alerts(store,workspace,actor,engine)
    elif section=='规则配置':
        rules(workspace,actor,engine)
    elif section=='数据修订':
        revisions(store,workspace,actor)


def dashboard(store,workspace,section):
    st.markdown(KPI_STYLE,unsafe_allow_html=True)
    center=MetricCenter(store);facts=center.facts(workspace)
    namespace=str(store.root)+workspace
    dates=[r['date'] for r in facts['candidates'] if r['date']]
    lo=pd.Timestamp(min(dates)).date() if dates else today()
    hi=pd.Timestamp(max(dates)).date() if dates else today()
    st.subheader('经营分析 · USD')
    a,b,c,d=st.columns(4)
    date_range=a.date_input('统计日期范围',value=(lo,hi),key='p2_range_'+namespace)
    platforms=sorted({r['platform'] for r in facts['orders'] if r['platform']})
    skus=sorted({r['sku'] for r in facts['orders']})
    platform=b.selectbox('监控平台',['全部']+platforms,key='p2_platform_'+namespace)
    sku=c.selectbox('监控SKU',['全部']+skus,key='p2_sku_'+namespace)
    status=d.selectbox('监控订单状态',['全部','completed','cancelled'],key='p2_status_'+namespace)
    country=st.selectbox('国家/地区（广告不分摊）',['全部']+sorted({r['country'] for r in facts['orders'] if r['country']}),key='p2_country_'+namespace)
    horizon=st.date_input('退款观察截止日',value=today(),key='p2_horizon_'+namespace)
    if len(date_range)!=2:
        st.info('请选择起止日期。');return
    start,end=date_range
    filters={k:v if v!='全部' else None for k,v in {'platform':platform,'sku':sku,'status':status,'country':country}.items()}
    result=center.calculate(workspace,start,end,as_of=horizon,**filters)
    st.info(scope_summary(result,start,end,horizon,filters))
    has_data=workspace_has_data(store, workspace)
    from v2.metrics import in_scope
    candidates=[r for r in facts['candidates'] if r['table']=='orders']
    matched=any(r['date'] and in_scope(r,start,end,**filters) for r in candidates)
    # Unparseable dates prevent a reliable no-match conclusion.
    no_match=bool(candidates) and not matched and not any(not r['date'] for r in candidates)
    def metric_state(value, applicable=True):
        return value_state(value, has_data=has_data, has_match=value is not None or not no_match, applicable=applicable)

    queue=store.query('SELECT * FROM alerts WHERE workspace=?',(workspace,))
    if not queue.empty:
        queue['period_end']=queue.evidence_json.map(lambda value:json.loads(value)['period']['end'])
        queue=queue[queue.period_end.ge(str(start)) & queue.period_end.le(str(end))]
        if filters['country'] or filters['status']=='cancelled' or (filters['platform'] and filters['sku']):
            queue=queue.iloc[:0]  # no country, cancelled or joint-dimension rules are configured
        elif filters['platform']:
            queue=queue[queue.object_key.eq('平台:'+filters['platform'])]
        elif filters['sku']:
            queue=queue[queue.object_key.eq('SKU:'+filters['sku'])]
    st.caption('经营指标、图表和来源明细使用相同筛选。预警按观测期结束日及已配置的公司/平台/SKU对象筛选；国家、取消订单或平台×SKU组合暂无直接适用规则，不分摊已有预警。')
    render_business_summary(result,queue,metric_state)
    render_trend_analysis(center,workspace,start,end,horizon,filters)
    render_business_breakdown(center,workspace,start,end,horizon,filters,result,queue)
    render_metric_definition(result,start,end,horizon)


def render_business_summary(result, queue, metric_state):
    st.subheader('经营摘要')
    st.caption('当前经营怎么样？指标仅代表当前筛选的有效模拟样本。')
    with st.container(key='monitor_primary_kpis'):
        st.markdown('#### 核心经营指标')
        columns=st.columns(4)
        for col,key in zip(columns,['sales','orders','gross_profit','contribution']):
            unit='笔' if key=='orders' else 'USD'
            col.metric(f'{DEFINITIONS[key][0]}（{unit}）',str(result[key]) if key=='orders' else money(result[key],metric_state(result[key])))
    with st.container(key='monitor_secondary_kpis'):
        st.markdown('#### 经营效率')
        efficiency=st.columns(3)
        efficiency[0].metric('商品毛利率',percent(result['gross_margin'],metric_state(result['gross_margin'])))
        efficiency[1].metric('广告归因ROAS（倍）',roas(result['roas'],metric_state(result['roas'],result['recorded_ad_cost']!=0)))
        efficiency[2].metric('12天退款订单率',percent(result['refund_rate'],metric_state(result['refund_rate'])))
        st.markdown('#### 数据可信度')
        extra=st.columns(3)
        for col,key in zip(extra,['cost_coverage','data_completeness']):
            label='订单可用率' if key=='data_completeness' else DEFINITIONS[key][0]
            col.metric(label,percent(result[key],metric_state(result[key])))
        extra[2].metric('成本已知订单销售额（USD）',money(result['known_cost_sales'],metric_state(result['known_cost_sales'])))
    st.caption(f"成本未知订单 {result['unknown_orders']} 笔 / 收入 {money(result['unknown_sales'],metric_state(result['unknown_sales']))}；利润样本 {result['profit_orders']} 笔。退款率为成熟12天订单队列；退款金额按确认日。")
    render_status(Status.WARNING, '；'.join(result['limits']))
    if result['sales'] is None:
        render_status(metric_state(None), '不能将隔离数据或缺失数据当0。')
    st.markdown('#### 待办提醒')
    pending=int(queue.status.isin(['待处理','处理中']).sum()) if not queue.empty else 0
    st.metric('筛选适用待处理预警（条）',pending)
    st.caption('待办数量仅表示当前筛选适用的待处理/处理中预警，不是数据质量评分。')


def render_trend_analysis(center,workspace,start,end,horizon,filters):
    st.subheader('趋势分析')
    rows=center.trend(workspace,max(start,end-timedelta(days=1)) if (end-start).days>366 else start,end,as_of=horizon,**filters)
    st.info(trend_summary(rows,end))
    if (end-start).days>366:
        st.info('趋势图最多展示366天，请缩小范围；汇总和明细仍使用完整选择范围。')
    else:
        trend=pd.DataFrame(rows).set_index('date')
        numeric=trend.map(lambda v:None if v is None else float(v))
        st.write('销售趋势（USD，缺日不填0）');st.line_chart(numeric[['sales']].rename(columns={'sales':'折后销售额'}))
        st.write('毛利与贡献趋势（USD，两条独立曲线，不相加）')
        st.line_chart(numeric[['gross_profit','contribution']].rename(columns={'gross_profit':'商品毛利','contribution':'暂估贡献'}))
        st.write('有效订单趋势（笔，缺少可确认收入样本的日期留空）')
        st.line_chart(numeric[['orders']].where(numeric['sales'].notna(),axis=0).rename(columns={'orders':'有效订单数'}))
        st.write('确认退款趋势（USD，按确认日）');st.line_chart(numeric[['refund_cost']].rename(columns={'refund_cost':'有效批准退款'}))


def render_business_breakdown(center,workspace,start,end,horizon,filters,result,queue):
    st.subheader('经营拆解')
    orders=result['orders_detail']
    if orders:
        frame=pd.DataFrame(orders)
        frame['sales']=frame.sales.map(float)
        st.write('平台销售额对比（USD，同一筛选样本）')
        st.bar_chart(frame.groupby('platform').sales.sum().rename('折后销售额'))
        st.write('SKU经营表现（USD，未知成本毛利保留为空）')
        summaries=[]
        for name in sorted({r['sku'] for r in orders}):
            sub=center.calculate(workspace,start,end,as_of=horizon,**{**filters,'sku':name})
            summaries.append({'SKU':name,'有效订单':sub['orders'],'销售额':sub['sales'],'成本已知销售额':sub['known_cost_sales'],
                              '毛利':sub['gross_profit'],'暂估贡献':sub['contribution'],'成本覆盖率':sub['cost_coverage']})
        table(summaries)
        st.bar_chart(pd.DataFrame(summaries).set_index('SKU')[['销售额']].map(float))
        st.markdown('#### 销售 Top SKU')
        st.caption('按当前筛选销售额降序取前5名；并列按 SKU 排序。')
        table(rank_rows(summaries,'销售额','SKU',5))
        st.markdown('#### 商品毛利 Top SKU')
        st.caption('按成本已知样本商品毛利降序取前5名；保留零和负值，未知利润不填0、不参与排名。成本覆盖率按收入计算，部分覆盖不代表整个 SKU 的利润。')
        table(rank_rows(summaries,'毛利','SKU',5))
        st.markdown('#### 平台贡献排序')
        st.caption('按现有暂估贡献利润降序；只比较可计算值，未知值不参与排名。样本覆盖不同需结合成本覆盖率阅读，不等于净利润排名。')
        platforms=[]
        for name in sorted({r['platform'] for r in orders}):
            sub=center.calculate(workspace,start,end,as_of=horizon,**{**filters,'platform':name})
            platforms.append({'平台':name,'暂估贡献':sub['contribution'],'成本覆盖率':sub['cost_coverage']})
        ranked=rank_rows(platforms,'暂估贡献','平台')
        if ranked:table(ranked)
        else:render_status(Status.INSUFFICIENT_DATA,'当前筛选没有可计算的平台贡献利润，无法排名；国家筛选不分摊广告。')
        st.caption(f'平台贡献未参与排名：{len(platforms)-len(ranked)} 个平台；原因：贡献利润不可计算。')
        st.write('国家地区表现（销售额、有效订单数、商品毛利与成本覆盖率）')
        countries=[]
        for name in sorted({r['country'] for r in orders if r['country']}):
            sub=center.calculate(workspace,start,end,as_of=horizon,**{**filters,'country':name})
            countries.append({'国家/地区':name,'有效订单':sub['orders'],'销售额':sub['sales'],
                              '毛利':sub['gross_profit'],'成本覆盖率':sub['cost_coverage']})
        table(countries)
        st.caption('国家地区不分摊广告费用，不展示国家 ROAS 或暂估贡献利润。各维度是同一批订单的不同切片，不能相加。')
    else:
        render_status(Status.NO_MATCH_DATA, '当前筛选没有可拆解的有效完成订单。')
    distribution=queue.groupby('severity').size().rename('数量').reset_index() if not queue.empty else pd.DataFrame()
    if not distribution.empty:
        st.write('筛选适用预警严重程度分布');st.bar_chart(distribution.set_index('severity').rename(columns={'数量':'预警数量'}))


def render_metric_definition(result,start,end,horizon):
    st.subheader('指标说明')
    st.caption(f'数据范围：{start} 至 {end}；退款观察截止日：{horizon}。全部结果基于 Synthetic 模拟场景或当前导入数据。')
    st.caption(f"样本：有效完成订单 {result['orders']} 笔；成本已知订单 {result['profit_orders']} 笔。订单可用率不等于账本完整率。")
    with st.expander('指标公式、纳入规则和数据血缘'):
        table([{'指标':'订单可用率' if key=='data_completeness' else name,'指标含义':INTERPRETATIONS[key][0],'能说明什么':INTERPRETATIONS[key][1],'不能说明什么':INTERPRETATIONS[key][2],'公式':formula,'纳入/排除与完整性':meaning,'期间':f'{start} 至 {end}','来源':'当前空间有效版本：订单/商品/退款/广告；源批次见明细'}
               for key,(name,formula,meaning) in DEFINITIONS.items()])
    orders=result['orders_detail']
    st.subheader('筛选后逐笔销售来源')
    table(pd.DataFrame(orders).drop(columns=['cost_source']) if orders else [],{'record_id':'原始记录ID','order_id':'订单','date':'下单日期','platform':'平台','sales':'计入销售额 USD','known':'成本已知','revision_ids':'生效修订版本','source_file':'来源文件','batch_id':'源批次'})
    with st.expander('商品成本来源和成本修订版本'):
        sources={r['cost_source']['record_id']:r['cost_source'] for r in orders if r['cost_source']}
        table(list(sources.values()))
    st.download_button('导出筛选后经营指标与血缘 JSON',safe_json(result).encode('utf-8'),file_name='经营指标与来源.json')


def alerts(store,workspace,actor,engine):
    st.subheader('智能规则预警与处理工作台')
    st.info('按最新有记录且已结束的订单日计算相同长度观测周期，不声称已收齐账本。库存为周期末快照，非实时库存。刷新页面不自动写入检测记录。')
    namespace=str(store.root)+workspace
    cutoff=st.date_input('检测参考日',value=today(),key='alert_cutoff_'+namespace)
    if st.button('运行规则检测',type='primary',disabled=not actor.strip()):
        try:
            result=engine.run(workspace,cutoff,actor)
            st.session_state['last_detection_'+namespace]=result
            st.success(f"检测完成：触发 {result['triggered']} 项，新增 {result['new']} 条待办。")
        except ValueError as exc:st.error(str(exc))
    result=st.session_state.get('last_detection_'+namespace)
    if result:
        with st.expander('不可计算/未达到阈值的规则说明'):st.write(result['skipped'])
    status=st.selectbox('预警处理状态',['全部','待处理','处理中','已解决','已忽略'])
    items=store.query('SELECT a.*,r.name FROM alerts a JOIN alert_rules r ON a.rule_id=r.id WHERE a.workspace=? ORDER BY a.id DESC',(workspace,))
    # Historical display names/thresholds always come from the detection snapshot.
    if not items.empty:
        items['name']=items.rule_snapshot.map(lambda s:json.loads(s)['name'])
        items['period_start']=items.evidence_json.map(lambda s:json.loads(s)['period']['start'])
        items['period_end']=items.evidence_json.map(lambda s:json.loads(s)['period']['end'])
    visible=items if status=='全部' else items[items.status.eq(status)]
    display_alerts=visible.copy()
    if not display_alerts.empty:
        for field in ('metric_value','threshold'):
            display_alerts[field]=display_alerts.apply(lambda row:rule_value(json.loads(row.rule_snapshot)['kind'],row[field]),axis=1)
    table(display_alerts[['id','name','object_key','first_detected','period_start','period_end','severity','metric_value','threshold','status','current_triggered']] if not visible.empty else display_alerts,
          {'id':'预警ID','name':'规则名称','object_key':'业务对象','first_detected':'首次触发','period_start':'统计开始','period_end':'统计结束','severity':'严重程度','metric_value':'当前检测值','threshold':'触发阈值','status':'处理状态','current_triggered':'最近同周期仍触发'})
    if visible.empty:return
    selected=st.selectbox('选择经营预警',visible.id.tolist(),format_func=lambda idx:f"#{idx} · {visible.set_index('id').loc[idx,'name']} · {visible.set_index('id').loc[idx,'object_key']}")
    item=visible.set_index('id').loc[selected];evidence=json.loads(item.evidence_json)
    st.write('发生了什么：'+evidence['what']);st.write('计算公式：'+evidence['formula'])
    st.write('涉及对象：'+evidence['object']);st.write('可能原因（排查假设）：'+ '；'.join(evidence['possible_causes']))
    st.write('建议检查：'+'；'.join(evidence['checklist']))
    with st.expander('完整指标、源批次、限制与规则版本快照'):
        st.json(evidence);st.json(json.loads(item.rule_snapshot))
    with st.form('alert_action'):
        new_status=st.selectbox('经营预警处理结论',['待处理','处理中','已解决','已忽略'])
        note=st.text_area('经营预警处理说明（必填）')
        submit=st.form_submit_button('保存预警处理')
    if submit:
        try:
            engine.action(workspace,int(selected),new_status,note,actor,int(item.state_version))
            st.session_state.phase2_notice='预警处理已保存，状态日志已追加。';st.rerun()
        except ValueError as exc:st.error(str(exc))
    table(store.query('SELECT * FROM alert_actions WHERE alert_id=? ORDER BY id DESC',(int(selected),)))


def rules(workspace,actor,engine):
    st.subheader('本地预警规则配置')
    st.warning('默认值仅为模拟演示配置，不是行业标准。比例/百分点使用小数：20%=0.2；毛利率下降5个百分点=0.05。修改会创建新版本，旧预警保留旧阈值。')
    rows=engine.rules(workspace);lookup={r['id']:r for r in rows}
    display_rules=[{**row,'threshold':rule_value(row['kind'],row['threshold'])} for row in rows]
    table(display_rules)
    selected=st.selectbox('选择配置规则',list(lookup),format_func=lambda idx:lookup[idx]['name'])
    row=lookup[selected]
    st.write('触发口径：'+FORMULAS[row['kind']])
    with st.form('configure_rule'):
        name=st.text_input('规则名称',row['name']);enabled=st.checkbox('启用规则',bool(row['enabled']))
        threshold=st.number_input('规则阈值（比例用小数）',min_value=0.,value=float(row['threshold']),format='%.4f')
        window=st.number_input('观察周期（天）',min_value=1,max_value=90,value=int(row['window_days']))
        severity=st.selectbox('规则严重程度',['高','中','低'],index=['高','中','低'].index(row['severity']))
        sample=st.number_input('最小样本量',min_value=1,value=int(row['min_sample']))
        note=st.text_area('规则修改说明（必填）')
        submit=st.form_submit_button('保存规则版本')
    if submit:
        try:
            engine.configure(workspace,selected,row['version'],actor,note,name=name,enabled=int(enabled),threshold=threshold,window_days=window,severity=severity,min_sample=sample)
            st.session_state.phase2_notice='规则新版本已保存，历史快照保留。';st.rerun()
        except ValueError as exc:st.error(str(exc))


def revisions(store,workspace,actor):
    st.subheader('带凭证的数据修订与版本审批')
    st.info('原始值不可覆盖；待审核和已驳回不进入计算。批准后仍执行 V1 质检，不会因批准而放行非法金额。业务键不能修订；身份为本地自报审计标识。')
    with store.connect() as con:
        rows=effective_rows(con,workspace)
    if not rows:
        render_status(Status.EMPTY_DATA, '请先导入需要修订的业务记录。');return
    lookup={r['id']:r for r in rows}
    record_id=st.selectbox('修订原始记录',list(lookup),format_func=lambda idx:f"#{idx} · {lookup[idx]['table_name']} · {lookup[idx]['business_key']}")
    record=lookup[record_id];value=json.loads(record['raw_json'])
    with st.expander('当前有效值与修订链'):st.json(value);st.write(record['revision_ids'])
    fields=[c for c in SCHEMAS[record['table_name']] if c not in GRAINS[record['table_name']][0]]
    field=st.selectbox('允许修订字段',fields)
    st.write('当前字段值：',value[field])
    flags=store.query('SELECT id,code FROM anomalies WHERE record_id=?',(record_id,))
    link=st.selectbox('关联质量异常（可选）',[None]+flags.id.tolist(),format_func=lambda idx:'不关联' if idx is None else f'异常 #{idx}')
    with st.form('revision_request'):
        new_value=st.text_input('建议新值（文本，空值用勾选）',value='' if value[field] is None else str(value[field]))
        missing=st.checkbox('建议设为缺失值（仍需质检）')
        reason=st.text_area('修订原因（必填）')
        evidence=st.text_input('证据引用（凭证编号或本地文件路径，必填）')
        submit=st.form_submit_button('提交修订申请')
    if submit:
        try:
            rid=Revisions(store).request(workspace,int(record_id),{field:None if missing else new_value},reason,evidence,actor,link)
            st.session_state.phase2_notice=f'修订 #{rid} 已申请，审批前指标不变。';st.rerun()
        except ValueError as exc:st.error(str(exc))
    revisions=store.query('SELECT * FROM record_revisions WHERE workspace=? ORDER BY id DESC',(workspace,))
    table(revisions.drop(columns=['original_json','changes_json']) if not revisions.empty else revisions)
    if not revisions.empty:
        inspection=st.selectbox('查看修订版本与审批',revisions.id.tolist())
        rev=revisions.set_index('id').loc[inspection]
        with st.expander('原值、新值、凭证及审批历史'):
            st.json(json.loads(rev.original_json));st.json(json.loads(rev.changes_json));st.write(rev.evidence_ref)
            table(store.query('SELECT * FROM revision_reviews WHERE revision_id=?',(int(inspection),)))
        if rev.status=='待审核':
            with st.form('revision_approve'):
                decision=st.selectbox('修订审核结论',['已批准','已驳回'])
                note=st.text_area('修订审核说明（必填）')
                submit=st.form_submit_button('保存修订审批')
            if submit:
                try:
                    Revisions(store).decide(workspace,int(inspection),decision,actor,note)
                    st.session_state.phase2_notice='修订审批已保存，质检与有效版本已重新评估；预警请运行规则检测。';st.rerun()
                except ValueError as exc:st.error(str(exc))
