from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import sys
import pytest
from streamlit.testing.v1 import AppTest
from v2.audit_duplicate import independent_aggregates
from v2.demo import error_csv, frames, workbook
from v2.service import Store

ROOT=Path(__file__).resolve().parents[2]
NORMAL=(ROOT/'v2/demo_data/normal.xlsx').read_bytes()
DUPLICATE=(ROOT/'v2/demo_data/duplicate.xlsx').read_bytes()


@pytest.mark.parametrize('with_errors',[False,True])
def test_duplicate_preserves_every_metric_and_reopen(tmp_path,with_errors):
    assert NORMAL==DUPLICATE
    assert hashlib.sha256(NORMAL).digest()==hashlib.sha256(DUPLICATE).digest()
    store=Store(tmp_path)
    store.ingest('normal.xlsx',NORMAL,'workbook','demo')
    if with_errors:
        store.ingest('errors.csv',error_csv(),'orders','demo')
    before=store.metrics('demo')
    aggregates=independent_aggregates(store.db)
    for key in ('orders','sales','gross_profit','goods_cost','shipping_cost','platform_cost','refund_cost','recorded_ad_cost','contribution'):
        assert before[key]==aggregates['sql'][key]
    records_before=store.query('SELECT * FROM records')
    flags_before=store.query('SELECT * FROM anomalies')
    for _ in range(3):
        assert store.ingest('duplicate.xlsx',DUPLICATE,'workbook','demo')['status']=='duplicate'
        assert store.metrics('demo')==before  # all totals, costs, months, scope, and lineage
    assert store.query('SELECT * FROM records').equals(records_before)
    assert store.query('SELECT * FROM anomalies').equals(flags_before)
    assert independent_aggregates(store.db)==aggregates
    assert Store(tmp_path).metrics('demo')==before
    # Fresh interpreter proves results do not depend on cached Python/session state.
    code="from v2.service import Store; from v2.audit_duplicate import encode; import json,sys; print(json.dumps(Store(sys.argv[1]).metrics('demo'),sort_keys=True,default=encode))"
    output=subprocess.check_output([sys.executable,'-c',code,str(tmp_path)],cwd=ROOT,text=True)
    expected=json.loads(json.dumps(before,sort_keys=True,default=lambda v:str(v)))
    assert json.loads(output)==expected


def test_regenerated_excel_and_csv_preserve_full_metrics(tmp_path):
    store=Store(tmp_path)
    store.ingest('normal.xlsx',NORMAL,'workbook','demo')
    before=store.metrics('demo')
    new_workbook=workbook()
    assert new_workbook!=NORMAL
    assert store.ingest('new.xlsx',new_workbook,'workbook','demo')['added']==0
    for name,frame in frames().items():
        assert store.ingest(name+'.csv',frame.to_csv(index=False).encode('utf-8-sig'),name,'demo')['added']==0
        assert store.metrics('demo')==before


def test_parallel_duplicate_clicks_preserve_every_metric(tmp_path):
    store=Store(tmp_path)
    store.ingest('normal.xlsx',NORMAL,'workbook','demo')
    before=store.metrics('demo')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:store.ingest('duplicate.xlsx',DUPLICATE,'workbook','demo'),range(2)))
    assert all(r['status']=='duplicate' for r in results)
    assert store.metrics('demo')==before


def test_ui_duplicate_rerun_and_reopened_session(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    app=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    app.button[1].click().run()
    before=Store(tmp_path).metrics('demo')
    ui_before=[(metric.label,metric.value) for metric in app.metric]
    assert before['sales']==35
    assert before['monthly']['2026-09']['contribution']==10
    for _ in range(2):
        app.button[2].click().run()
        assert not app.exception
        assert [(metric.label,metric.value) for metric in app.metric]==ui_before
        assert Store(tmp_path).metrics('demo')==before
    app.run()
    reopened=AppTest.from_file(str(ROOT/'v2/app.py'),default_timeout=30).run()
    assert not reopened.exception
    assert [(metric.label,metric.value) for metric in reopened.metric]==ui_before
    assert Store(tmp_path).metrics('demo')==before
    assert any('UNKNOWN_SKU' in element.value for element in reopened.info)
