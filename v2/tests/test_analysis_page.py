from pathlib import Path
import json
from datetime import date
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from v2.service import Store
from v2.metrics import MetricCenter
from v2.alerts import safe_json

ROOT=Path(__file__).resolve().parents[2]


def seed(tmp_path):
    store=Store(tmp_path)
    store.ingest('Synthetic.xlsx',(ROOT/'v2/demo_data/phase2_synthetic.xlsx').read_bytes(),'workbook','demo')
    return store


def app(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    view=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    view.sidebar.radio[1].set_value('经营分析').run()
    assert not view.exception
    return view


def test_single_analysis_navigation_and_four_sections(tmp_path,monkeypatch):
    view=app(tmp_path,monkeypatch)
    options=view.sidebar.radio[1].options
    assert options.count('经营分析')==1
    assert '经营总览' not in options and '经营监控' not in options
    headings=[h.value for h in view.subheader]
    assert [h for h in headings if h in ('经营摘要','趋势分析','经营拆解','指标说明')]==['经营摘要','趋势分析','经营拆解','指标说明']
    assert view.metric[0].value=='尚未导入数据'
    assert len(view.metric)==11


@pytest.mark.parametrize('route',['经营总览','经营监控'])
def test_legacy_internal_route_still_renders(tmp_path,route):
    seed(tmp_path)
    code=f"from v2.service import Store\nfrom v2.phase2_ui import render\nrender(Store({str(tmp_path)!r}), 'demo', '测试', {route!r})"
    view=AppTest.from_string(code,default_timeout=30).run()
    assert not view.exception
    assert view.metric[0].value=='1364.00 USD'
    assert any(h.value=='经营摘要' for h in view.subheader)


def test_filtered_export_exactly_matches_metric_service(tmp_path,monkeypatch):
    store=seed(tmp_path)
    before=MetricCenter(store).calculate('demo')
    exports=[]
    original=st.download_button
    def capture(*args,**kwargs):
        label=args[0] if args else kwargs.get('label')
        if label=='导出筛选后经营指标与血缘 JSON':
            exports.append(json.loads(args[1] if len(args)>1 else kwargs['data']))
        return original(*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    view=app(tmp_path,monkeypatch)
    next(s for s in view.selectbox if s.label=='监控SKU').set_value('SKU001').run()
    horizon=next(d.value for d in view.date_input if d.label=='退款观察截止日')
    start,end=next(d.value for d in view.date_input if d.label=='统计日期范围')
    expected=MetricCenter(store).calculate('demo',start,end,sku='SKU001',as_of=horizon)
    assert exports[-1]==json.loads(safe_json(expected))
    assert view.metric[0].value=='924.00 USD'
    assert len(view.metric)==11
    assert MetricCenter(store).calculate('demo')==before
    assert any('订单趋势' in t.value for t in view.markdown)
    country=next(d.value for d in view.dataframe if '国家/地区' in d.value.columns)
    assert set(country.columns)=={'国家/地区','有效订单','销售额','毛利','成本覆盖率'}
    assert country['销售额'].tolist()==['924.00 USD']


def test_country_filter_keeps_ads_unallocated(tmp_path,monkeypatch):
    store=seed(tmp_path)
    view=app(tmp_path,monkeypatch)
    next(s for s in view.selectbox if s.label=='国家/地区（广告不分摊）').set_value('US').run()
    assert not view.exception
    assert view.metric[3].value=='数据不足'
    assert view.metric[5].value=='数据不足'
    assert MetricCenter(store).calculate('demo',country='US')['roas'] is None
