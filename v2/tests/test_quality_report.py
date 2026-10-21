from datetime import datetime, timezone
from io import BytesIO
import json

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from test_quality_presentation import seeded, ROOT
from v2.quality_presentation import prepare, select, summarize
from v2.quality_report import guidance, build_report, report_html
from v2.metrics import MetricCenter
from v2.service import Store


@pytest.mark.parametrize('code,fields,active,expected', [
    ('invalid_price','unit_price',1,'数据修订'),
    ('review_high_price','unit_price',1,'异常审核'),
    ('business_key_conflict','order_id',1,'不支持修改业务键'),
    ('missing:order_id','order_id',1,'不支持修改业务键'),
    ('sku_format','sku',1,'不进入现有异常审核列表'),
    ('invalid_price','unit_price',0,'仅供追溯'),
])
def test_guidance_respects_existing_workflow(code,fields,active,expected):
    assert expected in guidance(dict(code=code,fields=fields,active=active,table_name='orders',record_id=3,id=7))


def make_report(store,filters=None,history=False):
    rows=prepare(store.anomalies('demo'))
    active=rows[rows.active.eq(1)]
    filters=filters or dict(table_name=None,batch_id=None,异常分类=None,status=None)
    view=select(rows if history else active,filters)
    summary=summarize(select(active,filters),active)
    return build_report(view,summary,filters,'模拟演示',bool(len(store.query('SELECT id FROM records'))),
                        not active.empty,history,datetime(2026,10,15,8,28,tzinfo=timezone.utc))


def test_report_filters_counts_time_and_escaped_source(tmp_path):
    store=seeded(tmp_path)
    report=make_report(store,{'异常分类':'主数据与关联'})
    assert report['生成时间']=='2026-10-15 16:28'
    assert report['时区']=='Asia/Shanghai'
    assert report['当前摘要']['有效异常条数']==len(report['证据明细'])
    assert all(r['异常分类']=='主数据与关联' for r in report['证据明细'])
    report['证据明细'][0]['reason']='<script>alert("source")</script>'
    html=report_html(report).decode('utf-8')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'Asia/Shanghai' in html and '不估算损失金额' in html


def test_history_changes_evidence_not_current_report_summary(tmp_path):
    from v2.revisions import Revisions
    store=seeded(tmp_path)
    bad=store.anomalies('demo').query("code == 'invalid_price'").iloc[0]
    flow=Revisions(store)
    rid=flow.request('demo',int(bad.record_id),{'unit_price':'20'},'模拟修订','Synthetic-test','test')
    flow.decide('demo',rid,'已批准','test','核查')
    current,history=make_report(store),make_report(store,history=True)
    assert current['当前摘要']==history['当前摘要']
    assert current['分类统计']==history['分类统计']
    assert int(bad.id) not in {r['id'] for r in current['证据明细']}
    old=next(r for r in history['证据明细'] if r['id']==int(bad.id))
    assert '仅供追溯' in old['处理建议']


def test_empty_no_match_and_normal_report_states(tmp_path):
    store=Store(tmp_path)
    empty=make_report(store)
    assert empty['数据状态']=='尚未导入数据' and empty['证据明细']==[]
    assert '尚未导入数据' in report_html(empty).decode('utf-8')
    store.ingest('normal.xlsx',(ROOT/'v2/demo_data/normal.xlsx').read_bytes(),'workbook','demo')
    assert make_report(store)['数据状态']=='正常'
    store=seeded(tmp_path)
    assert make_report(store,{'status':'确认'})['数据状态']=='当前范围无匹配数据'


def test_report_ui_download_matches_filters_and_preserves_database(tmp_path,monkeypatch):
    store=seeded(tmp_path)
    before=MetricCenter(store).calculate('demo')
    snapshots={name:store.query('SELECT * FROM '+name) for name in ('records','anomalies','reviews','record_revisions','revision_reviews','alerts','alert_detections','alert_actions','alert_rules','alert_rule_versions','operation_logs')}
    exports={}
    download=st.download_button
    def capture(*args,**kwargs):
        if args and args[0] in ('下载数据质量报告（HTML）','导出质量检查证据'):
            exports[args[0]]=args[1]
        return download(*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    view=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    next(s for s in view.selectbox if s.label=='质量异常分类').set_value('主数据与关联').run()
    assert not view.exception
    html=exports['下载数据质量报告（HTML）'].decode('utf-8')
    assert '模拟演示' in html and 'unknown_sku' in html and 'invalid_price' not in html
    csv=pd.read_csv(BytesIO(exports['导出质量检查证据']))
    assert set(csv.code)=={'unknown_sku'}
    assert any('建议下一步：' in m.value and '数据修订' in m.value for m in view.markdown)
    assert MetricCenter(store).calculate('demo')==before
    for name,expected in snapshots.items():
        pd.testing.assert_frame_equal(store.query('SELECT * FROM '+name),expected)
    view.sidebar.radio[0].set_value('业务数据').run()
    assert not view.exception
    html=exports['下载数据质量报告（HTML）'].decode('utf-8')
    assert '业务数据' in html and '尚未导入数据' in html and 'unknown_sku' not in html
