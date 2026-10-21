from pathlib import Path
from streamlit.testing.v1 import AppTest
from v2.service import Store

ROOT=Path(__file__).resolve().parents[2]


def test_phase2_empty_pages_have_explicit_empty_states(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    app=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    for section in ['经营分析','智能预警','数据修订','规则配置']:
        app.sidebar.radio[1].set_value(section).run()
        assert not app.exception,section
    app.sidebar.radio[1].set_value('经营分析').run()
    assert app.metric[0].value=='尚未导入数据'
    assert app.metric[3].value=='尚未导入数据'


def test_phase2_ui_filter_and_space_switch(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    store=Store(tmp_path)
    store.ingest('Synthetic-14days.xlsx',(ROOT/'v2/demo_data/phase2_synthetic.xlsx').read_bytes(),'workbook','demo')
    app=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    app.sidebar.radio[1].set_value('经营分析').run()
    assert not app.exception
    assert app.metric[0].value=='1364.00 USD'
    select=next(s for s in app.selectbox if s.label=='监控SKU')
    select.set_value('SKU001').run()
    assert not app.exception and app.metric[0].value=='924.00 USD'
    app.sidebar.radio[0].set_value('业务数据').run()
    assert not app.exception and app.metric[0].value=='尚未导入数据'


def test_phase2_demo_is_independent_of_existing_demo_history(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    store=Store(tmp_path)
    store.ingest('normal.xlsx',(ROOT/'v2/demo_data/normal.xlsx').read_bytes(),'workbook','demo')
    before=store.metrics('demo')
    app=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('第二阶段独立模拟演示').run()
    assert not app.exception and app.metric[1].value=='尚未导入数据'
    button=next(b for b in app.button if b.label=='导入14天第二阶段模拟数据')
    button.click().run()
    assert not app.exception and app.metric[1].value=='1364.00 USD'
    assert Store(tmp_path).metrics('demo')==before
    app.sidebar.radio[0].set_value('模拟演示').run()
    assert not app.exception and app.metric[1].value=='35.00 USD'


def test_phase2_contract_upgrade_reloads_cached_services(tmp_path,monkeypatch):
    import v2.service as module
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    store=module.Store(tmp_path)
    store.ingest('Synthetic-14days.xlsx',(ROOT/'v2/demo_data/phase2_synthetic.xlsx').read_bytes(),'workbook','demo')
    monkeypatch.setattr(module.Store,'api_version',2)
    app=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    assert not app.exception and module.Store.api_version==3
    app.sidebar.radio[1].set_value('经营分析').run()
    assert not app.exception and app.metric[0].value=='1364.00 USD'
