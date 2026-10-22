from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from v2.portfolio_sessions import DemoSessions, DemoUnavailable
from v2.metrics import MetricCenter
from v2.revisions import Revisions
from v2.daily_report import build_daily_report
from v2.daily_report_export import public_view, report_html

ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture
def manager(tmp_path):
    value = DemoSessions(parent=tmp_path, sweep=0)
    yield value
    value.close()


def counts(store):
    return {t: int(store.query('SELECT COUNT(*) n FROM '+t).iloc[0].n)
            for t in ('records','batches','alerts','alert_detections','record_revisions')}


def revise(store):
    record = store.query("SELECT id FROM records WHERE json_extract(raw_json, '$.order_id')='SYNTH-BAD' AND table_name='orders'")
    rid=Revisions(store).request('demo',int(record.iloc[0].id),{'unit_price':'20'},'模拟核对','SYNTH-ONLY','模拟')
    Revisions(store).decide('demo',rid,'已批准','模拟','模拟批准')


def test_seed_idempotent_metrics_rules_reports(manager):
    with manager.lease() as (token,s):
        before=counts(s)
        assert before['alerts'] > 0
        assert len(s.query('SELECT * FROM alert_rules'))==13
        assert MetricCenter(s).calculate('demo')['sales']==1364
        report=build_daily_report(s,'demo','2026-09-14','2026-10-21',current_date=date(2026,10,22))
        assert report['history']['entries']
        html=report_html(public_view(report,'Synthetic'))
        assert b'92.00' in html and b'<script' not in html
        assert counts(s)==before
    with manager.lease(token) as (same,s):
        assert same==token and counts(s)==before


def test_concurrent_session_revision_isolation(manager):
    def create(_):
        with manager.lease() as (token,store):return token,store
    with ThreadPoolExecutor(max_workers=2) as pool: a,b=list(pool.map(create,range(2)))
    assert a[0]!=b[0] and a[1].db!=b[1].db
    baseline=counts(b[1]);revise(a[1])
    assert MetricCenter(a[1]).calculate('demo')['sales']==1384
    assert MetricCenter(b[1]).calculate('demo')['sales']==1364
    assert counts(b[1])==baseline


def test_expiry_does_not_delete_active_and_restart_is_fresh(tmp_path):
    now=[0]
    m=DemoSessions(parent=tmp_path,clock=lambda:now[0],ttl=5,lifetime=10,sweep=0)
    try:
        with m.lease() as (token,s):
            revise(s);now[0]=20;m.cleanup();assert s.db.exists()
        m.cleanup();assert not s.db.exists()
        with m.lease(token) as (new,s):assert new!=token and MetricCenter(s).calculate('demo')['sales']==1364
        fresh=DemoSessions(parent=tmp_path,sweep=0)
        try:
            with fresh.lease(new) as (other,copy):assert other!=new and copy.db!=s.db
        finally:fresh.close()
    finally:m.close()


@pytest.mark.parametrize('bad',['missing','invalid'])
def test_failed_initialization_has_safe_error_and_no_partial_session(tmp_path,bad):
    p=tmp_path/'fixture.xlsx'
    if bad=='invalid':p.write_bytes(b'broken')
    m=DemoSessions(parent=tmp_path,seed=p,sweep=0)
    try:
        with pytest.raises(DemoUnavailable,match='初始化失败') as exc:
            with m.lease():pass
        assert str(tmp_path) not in str(exc.value)
        assert not m.entries and not list(m.root.iterdir())
    finally:m.close()


def test_capacity_quota_and_reset(manager):
    manager.capacity=1
    with manager.lease() as (token,s): pass
    with pytest.raises(DemoUnavailable,match='已满'):
        with manager.lease():pass
    manager.max_bytes=1
    with pytest.raises(DemoUnavailable,match='限额'):
        with manager.lease(token):pass
    manager.discard(token);assert not s.root.exists()
    manager.max_bytes=8*1024*1024
    with manager.lease() as (new,s):assert new!=token


def test_cleanup_never_touches_unregistered_paths(manager,tmp_path):
    outside=tmp_path/'keep';outside.mkdir();(outside/'important').write_text('keep')
    with manager.lease('../../keep') as (token,s):assert s.root.parent==manager.root
    manager.discard('../../keep');manager.close()
    assert (outside/'important').read_text()=='keep'


def app(manager,monkeypatch):
    monkeypatch.setattr('v2.portfolio_sessions.sessions',lambda:manager)
    return AppTest.from_file(str(ROOT/'v2/portfolio_app.py'),default_timeout=60).run()


def nav(a,name):
    next(r for r in a.radio if r.label=='功能导航').set_value(name).run()
    assert not a.exception


def test_public_entry_navigation_downloads_and_no_business_env(manager,monkeypatch,tmp_path):
    forbidden=tmp_path/'real-business'
    monkeypatch.setenv('V2_DATA_DIR',str(forbidden))
    a=app(manager,monkeypatch);assert not a.exception
    assert not forbidden.exists()
    assert list(next(r for r in a.radio if r.label=='数据空间').options)==['Synthetic 独立会话']
    nav(a,'经营日报')
    assert any(x.label=='下载 HTML 日报' for x in a.get('download_button'))
    nav(a,'数据运营工作台')
    assert not a.get('file_uploader')
    assert any('HTML' in x.label for x in a.get('download_button'))
    assert not any('导入' in b.label for b in a.button)
    for page in ['智能预警','数据修订','规则配置']:nav(a,page)


def test_two_app_sessions_and_reset(manager,monkeypatch):
    a=app(manager,monkeypatch);b=app(manager,monkeypatch)
    ta=a.session_state['_public_session'];tb=b.session_state['_public_session']
    assert ta!=tb
    revise(manager.entries[ta].store)
    assert MetricCenter(manager.entries[tb].store).calculate('demo')['sales']==1364
    next(x for x in a.button if x.label=='重置我的演示').click().run()
    assert not a.exception and a.session_state['_public_session']!=ta
    assert tb in manager.entries


def test_public_initialization_error_is_visible_without_traceback(tmp_path,monkeypatch):
    m=DemoSessions(parent=tmp_path,seed=tmp_path/'absent',sweep=0)
    try:
        a=app(m,monkeypatch)
        assert not a.exception and any('初始化失败' in e.value for e in a.error)
        assert str(tmp_path) not in str([e.value for e in a.error])
    finally:m.close()


def test_background_sweep_reclaims_idle_sessions(tmp_path):
    import time
    now=[0]
    m=DemoSessions(parent=tmp_path,clock=lambda:now[0],ttl=5,sweep=0.01)
    try:
        with m.lease() as (_,store):pass
        now[0]=10
        until=time.monotonic()+2
        while store.root.exists() and time.monotonic()<until:time.sleep(0.02)
        assert not store.root.exists()
    finally:m.close()


def test_process_manager_created_once_under_concurrency(monkeypatch,manager):
    import v2.portfolio_sessions as module
    calls=[]
    monkeypatch.setattr(module,'_manager',None)
    monkeypatch.setattr(module,'DemoSessions',lambda:(calls.append(1) or manager))
    with ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(lambda _:module.sessions(),range(8)))
    assert len(calls)==1 and all(v is manager for v in values)
