from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_app_demo_actions_and_space_isolation(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    assert not app.exception
    assert app.metric[0].value=='0'
    app.button[1].click().run()
    assert not app.exception
    assert app.metric[1].value=='35.00 USD'
    app.button[2].click().run()
    assert app.metric[1].value=='35.00 USD'
    assert any('重复上传' in x.value for x in app.warning)
    app.button[3].click().run()
    assert app.metric[1].value=='70.00 USD'
    assert app.metric[3].value=='4'
    assert not app.exception
    app.sidebar.radio[0].set_value('业务数据').run()
    assert app.metric[1].value=='尚未导入数据'
    assert not app.exception


def test_blank_actor_disables_import(tmp_path,monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR',str(tmp_path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.sidebar.text_input[0].set_value('').run()
    assert all(button.disabled for button in app.button[:4])
    assert not app.exception
