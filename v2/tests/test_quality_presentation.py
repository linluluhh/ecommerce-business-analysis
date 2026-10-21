from copy import deepcopy
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from v2.quality_presentation import category, prepare, select, summarize
from v2.service import Store
from v2.metrics import MetricCenter
from v2.demo import error_csv

ROOT = Path(__file__).resolve().parents[2]


def issue(idx, record, code, status='待核实', active=1):
    return dict(id=idx, record_id=record, code=code, status=status, active=active,
                table_name='orders', batch_id='batch-A')


@pytest.mark.parametrize('code,expected', [
    ('missing:sku','缺失字段'), ('missing_business_key','缺失字段'),
    ('type_invalid:unit_price','类型与日期解析'), ('date_invalid:order_date','类型与日期解析'),
    ('business_key_conflict','业务键冲突'), ('unknown_sku','主数据与关联'),
    ('invalid_price','金额与数量检查'), ('ad_revenue_order_difference','业务一致性'),
    ('sku_format','格式与去重提示'), ('future_code','其他规则'),
])
def test_category_only_translates_codes(code, expected):
    assert category(code) == expected


def test_dedup_precedence_history_and_no_source_mutation():
    source = pd.DataFrame([issue(1,10,'unknown_sku'), issue(2,10,'invalid_price'),
                           issue(3,11,'sku_format'), issue(4,12,'invalid_price',active=0)])
    before = source.copy(deep=True)
    rows = prepare(source)
    current = rows[rows.active.eq(1)]
    result = summarize(current,current)
    assert result['有效异常条数'] == 3
    assert result['受影响记录数'] == 2
    assert result['直接阻断记录数'] == 1
    assert result['effects'][0]['记录当前作用'] == '整行隔离'
    assert sum(r['受影响记录数'] for r in result['categories']) == 3
    pd.testing.assert_frame_equal(source,before)


def test_filtered_soft_rejection_does_not_hide_hard_block():
    rows = prepare(pd.DataFrame([issue(1,10,'review_high_price','驳回'),
                                 issue(2,10,'invalid_fee','确认'), issue(3,11,'review_high_price','驳回'),
                                 issue(4,12,'unknown_sku','驳回')]))
    selected = select(rows,{'status':'驳回'})
    result = summarize(selected,rows)
    assert result['有效异常条数'] == 3
    assert result['直接阻断记录数'] == 2
    assert [r['记录当前作用'] for r in result['effects']] == ['整行隔离','软规则已驳回','仅利润隔离']


def seeded(tmp_path):
    store = Store(tmp_path)
    store.ingest('normal.xlsx',(ROOT/'v2/demo_data/normal.xlsx').read_bytes(),'workbook','demo')
    store.ingest('errors.csv',error_csv(),'orders','demo')
    return store


def test_effects_match_existing_service_after_reviews(tmp_path):
    store = seeded(tmp_path)
    for _, row in store.anomalies('demo').iterrows():
        if row.code in ('review_high_price','invalid_price','unknown_sku'):
            store.review(int(row.id),'驳回','模拟核查','test',int(row.version),'demo')
    rows = prepare(store.anomalies('demo'))
    current = rows[rows.active.eq(1)]
    summary = summarize(current,current)
    # Facts are authoritative for whether an order can enter revenue/profit samples.
    facts = MetricCenter(store).facts('demo')
    orders = {r['record_id']: r for r in facts['orders']}
    for item in summary['effects']:
        if item['业务表'] != 'orders':
            continue
        if item['记录当前作用'] == '整行隔离':
            assert item['记录ID'] not in orders
        elif item['记录当前作用'] == '仅利润隔离':
            assert item['记录ID'] in orders and not orders[item['记录ID']]['known']


def test_empty_and_no_match_summaries(tmp_path):
    empty = prepare(Store(tmp_path).anomalies('demo'))
    result = summarize(empty,empty)
    assert result['有效异常条数'] == result['受影响记录数'] == result['直接阻断记录数'] == 0
    rows = prepare(pd.DataFrame([issue(1,1,'invalid_price')]))
    assert summarize(select(rows,{'batch_id':'absent'}),rows)['effects'] == []


def test_quality_ui_filter_history_export_and_metric_invariance(tmp_path,monkeypatch):
    import streamlit as st
    store = seeded(tmp_path)
    before = MetricCenter(store).calculate('demo')
    records = store.query('SELECT * FROM records')
    exported = []
    original = st.download_button
    def capture(*args,**kwargs):
        if args and args[0] == '导出质量检查证据':
            exported.append(args[1])
        return original(*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    view = AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    assert not view.exception
    next(s for s in view.selectbox if s.label=='质量异常分类').set_value('主数据与关联').run()
    rows = prepare(store.anomalies('demo'))
    current = rows[rows.active.eq(1)]
    selected = select(current,{'异常分类':'主数据与关联'})
    expected = summarize(selected,current)
    values = {m.label:m.value for m in view.metric}
    assert values['受影响记录数'] == str(expected['受影响记录数'])
    from io import BytesIO
    evidence = pd.read_csv(BytesIO(exported[-1]))
    assert set(evidence.id) == set(selected.id)
    assert list(evidence.columns) == list(store.anomalies('demo').columns)
    next(c for c in view.checkbox if c.label=='包含已失效异常').check().run()
    assert {m.label:m.value for m in view.metric} == values
    assert MetricCenter(store).calculate('demo') == before
    pd.testing.assert_frame_equal(store.query('SELECT * FROM records'),records)
    next(s for s in view.selectbox if s.label=='质量审核状态').set_value('确认').run()
    assert not view.exception
    assert next(m.value for m in view.metric if m.label=='有效异常条数') == '0'
    assert any('当前筛选没有有效异常' in i.value for i in view.info)
    view.sidebar.radio[0].set_value('业务数据').run()
    assert not view.exception
    assert next(m.value for m in view.metric if m.label=='受影响记录数') == '尚未导入数据'


def test_approved_revision_removes_current_issue_keeps_history(tmp_path):
    from v2.revisions import Revisions
    store = seeded(tmp_path)
    bad = store.anomalies('demo').query("code == 'invalid_price'").iloc[0]
    flow = Revisions(store)
    request = flow.request('demo',int(bad.record_id),{'unit_price':'20'},'模拟修订','Synthetic凭证','test')
    flow.decide('demo',request,'已批准','test','模拟复核')
    rows = prepare(store.anomalies('demo'))
    assert rows.loc[rows.id.eq(bad.id),'规则作用'].iloc[0] == '已失效（仅历史）'
    current = rows[rows.active.eq(1)]
    assert int(bad.id) not in set(current.id)
    assert summarize(select(current,{'code':'invalid_price'}),current)['有效异常条数'] == 0


def test_summary_defensively_excludes_history():
    rows = prepare(pd.DataFrame([issue(1,1,'invalid_price',active=0),
                                 issue(2,2,'unknown_sku')]))
    result = summarize(rows,rows)
    assert result['有效异常条数'] == result['受影响记录数'] == 1
    assert result['effects'][0]['记录ID'] == 2


def test_record_identity_is_database_global_and_spaces_are_scoped(tmp_path):
    store = seeded(tmp_path)
    store.ingest('errors.csv',error_csv(),'orders','business')
    records = store.query('SELECT id,workspace,table_name FROM records')
    assert records.id.is_unique
    assert records.table_name.nunique() > 1
    demo_ids = set(records.loc[records.workspace.eq('demo'),'id'])
    business_ids = set(records.loc[records.workspace.eq('business'),'id'])
    assert demo_ids.isdisjoint(business_ids)
    for workspace, ids in [('demo',demo_ids),('business',business_ids)]:
        rows = prepare(store.anomalies(workspace))
        assert set(rows.record_id) <= ids
        current = rows[rows.active.eq(1)]
        assert summarize(current,current)['受影响记录数'] == current.record_id.nunique()


def test_phase_a_summary_stays_independent_with_phase_b_report_control(tmp_path,monkeypatch):
    import ast
    source = (ROOT/'v2/quality_presentation.py').read_text(encoding='utf8')
    modules = [node.module for node in ast.walk(ast.parse(source)) if isinstance(node,ast.ImportFrom)]
    assert 'v2.quality_report' not in modules
    assert (ROOT/'v2/quality_report.py').exists()
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    view = AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    assert not view.exception
    assert sum('HTML' in button.label for button in view.get('download_button')) == 1
    assert any(metric.label == '有效异常条数' for metric in view.metric)
