from pathlib import Path
import streamlit.testing.v1
import v2.service as service


def test_new_ui_recovers_from_legacy_backend_metrics(tmp_path,monkeypatch):
    """Reproduce an already-running process retaining the pre-lineage Store."""
    root=Path(__file__).resolve().parents[2]
    store=service.Store(tmp_path)
    store.ingest('normal.xlsx',(root/'v2/demo_data/normal.xlsx').read_bytes(),'workbook','demo')
    before=store.metrics('demo')
    real_metrics=service.Store.metrics
    calls=[]
    def legacy_metrics(self,workspace):
        calls.append(workspace)
        result=real_metrics(self,workspace)
        for key in ('sales_records','goods_cost','shipping_cost','platform_cost'):
            result.pop(key)
        return result
    monkeypatch.setattr(service.Store,'metrics',legacy_metrics)
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    app=streamlit.testing.v1.AppTest.from_file(str(root/'v2/app.py'),default_timeout=30).run()
    assert calls  # old contract was actually encountered
    assert not app.exception
    assert app.metric[1].value=='35.00 USD'
    assert service.Store(tmp_path).metrics('demo')==before
    assert len(app.tabs)==4
    app.button[2].click().run()
    assert not app.exception
    assert service.Store(tmp_path).metrics('demo')==before
