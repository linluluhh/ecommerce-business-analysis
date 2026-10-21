"""Quality presentation over the existing workspace-scoped anomaly snapshot."""
import pandas as pd
import json
import streamlit as st
from v2.quality_presentation import prepare, select, summarize, EFFECT_ORDER
from v2.ui_status import Status, TEXT, render_status, quality_status
from v2.quality_presentation import TABLE_NAMES
from v2.quality_report import guidance, build_report, report_html


def render_quality(issues, has_data, namespace, workspace_label='当前空间'):
    st.subheader('质量检查结果与隔离证据')
    st.caption('Synthetic 模拟业务作品集；结果仅代表当前空间已导入数据，不代表账本完整性或真实企业收益。')
    rows = prepare(issues)
    all_current = rows[rows.active.eq(1)]
    render_status(*quality_status(has_data, not all_current.empty))
    columns = st.columns(4)
    filters = {}
    for col, field, label in zip(columns, ['table_name', 'batch_id', '异常分类', 'status'],
                                 ['质量业务表', '质量来源批次', '质量异常分类', '质量审核状态']):
        options = ['待核实', '确认', '驳回'] if field == 'status' else sorted(rows[field].dropna().unique().tolist())
        chosen = col.selectbox(label, [None] + options, format_func=lambda value, field=field: '全部' if value is None else TABLE_NAMES.get(value,value) if field=='table_name' else value,
                               key='quality_' + field + namespace)
        filters[field] = chosen
    st.caption('当前范围：当前数据空间；' + '；'.join(f'{label}：{filters[field] or "全部"}' for field, label in
               [('table_name','业务表'),('batch_id','来源批次'),('异常分类','分类'),('status','审核状态')]) +
               '。不按业务日期筛选，无法解析日期的异常仍保留。批次选项来自已有异常证据。')
    current = select(all_current, filters)
    summary = summarize(current, all_current)
    st.markdown('#### 当前质量摘要')
    for col, label in zip(st.columns(4), ['有效异常条数', '受影响记录数', '待核实异常数', '直接阻断记录数']):
        col.metric(label, summary[label] if has_data else TEXT[Status.EMPTY_DATA])
    st.caption('异常条数按异常ID计数，记录数按当前数据库全局唯一的记录ID去重；仅统计当前空间。分类之间可能重叠，不能相加。直接阻断数仅统计命中当前筛选的记录，不含推算的下游关联影响。')
    if has_data and current.empty and not all_current.empty:
        render_status(Status.NO_MATCH_DATA, '当前筛选没有有效异常，不表示整个空间没有问题。')
    if not current.empty:
        st.markdown('#### 异常分类统计')
        st.dataframe(pd.DataFrame(summary['categories']), hide_index=True, width='stretch')
        st.markdown('#### 业务影响摘要')
        effect_rows = summary['effects']
        st.dataframe(pd.DataFrame([{'记录当前作用': label, '记录数': sum(r['记录当前作用'] == label for r in effect_rows)}
                                   for label in EFFECT_ORDER]), hide_index=True, width='stretch')
        st.caption('作用按该记录全部有效规则判定，不受分类/审核筛选隐藏的其他规则影响；整行隔离优先于仅利润隔离。各作用互斥。非阻断或软规则驳回不保证相关主数据可用。')
        st.dataframe(pd.DataFrame(effect_rows), hide_index=True, width='stretch')
    st.caption('确认＝问题仍存在，不等于已修复；驳回仅可能放行软规则，硬性错误仍阻断。这里不推算损失金额，也不生成综合质量评分。')
    show_history = st.checkbox('包含已失效异常')
    view = select(rows if show_history else all_current, filters)
    if show_history:
        st.caption('下方包含历史异常；当前质量状态及上方摘要仅依据仍有效的异常，历史开关不改变统计。')
    if not view.empty:
        st.markdown('#### 问题明细与处理引导')
        business = view[['id','table_name','reason','异常分类','规则作用','status','active']].copy()
        business['table_name'] = business.table_name.map(lambda name:TABLE_NAMES.get(name,name))
        business['active'] = business.active.map({1:'当前有效',0:'历史已失效'})
        st.dataframe(business.rename(columns={'id':'异常ID','table_name':'业务表','reason':'问题说明',
                                              'status':'审核结论','active':'异常有效性'}), hide_index=True,width='stretch')
        selected = st.selectbox('查看质量问题及处理建议',view.id.tolist(),
                                format_func=lambda idx:f"异常 #{idx} · {view.set_index('id').loc[idx,'reason']}",
                                key='quality_detail_'+namespace)
        item = view.set_index('id',drop=False).loc[selected]
        st.write('建议下一步：'+guidance(item))
        st.caption(f"定位信息：记录 #{item.record_id}；异常 #{item.id}；来源批次 {item.batch_id}；源文件行号 {item.source_row}。这里只提供引导，不自动提交审核或修订。")
        with st.expander('所选问题的原始值与技术证据'):
            st.caption('下方为原始入库值；若存在修订，当前有效值与修订链请在“数据修订”中核查。')
            st.json(json.loads(item.raw_json))
            st.json({key:item[key] for key in ('code','fields','scope','hard','status','active','business_key')})
        fields = ['id','record_id','table_name','batch_id','source_row','异常分类','规则作用',
                  'code','reason','fields','severity','scope','hard','status','active']
        with st.expander('完整技术证据列表'):
            st.dataframe(view[fields], width='stretch', hide_index=True)
        # Preserve the original evidence-export schema; only apply the selected scope.
        st.download_button('导出质量检查证据', view[issues.columns].to_csv(index=False).encode('utf-8-sig'), file_name='quality_evidence.csv')
    st.markdown('#### 质量报告')
    report = build_report(view,summary,filters,workspace_label,has_data,not all_current.empty,show_history)
    st.caption(f"报告生成时间：{report['生成时间']}（Asia/Shanghai）。范围与当前筛选一致；历史开关只影响明细，不改变当前摘要。报告按需生成，不写入数据库。")
    st.download_button('下载数据质量报告（HTML）',report_html(report),file_name='quality_report.html',mime='text/html')
    st.caption('规则作用来自现有隔离策略；历史异常不参与当前隔离。收入、利润与关联影响请结合业务影响说明和指标来源核查。')
