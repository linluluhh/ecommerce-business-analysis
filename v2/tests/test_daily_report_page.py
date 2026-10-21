from copy import deepcopy
from datetime import date
from html import escape
import json

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from test_daily_report import ROOT, TODAY, seed, snapshot, assert_snapshot
from v2.service import Store
from v2.alerts import AlertEngine
from v2.daily_report import build_daily_report
from v2.daily_evidence import read_history, build_guidance
from v2.daily_report_export import public_view, report_html


def historical(tmp_path):
    store = Store(tmp_path)
    store.ingest('Synthetic.xlsx', (ROOT/'v2/demo_data/phase2_synthetic.xlsx').read_bytes(), 'workbook', 'demo')
    engine = AlertEngine(store)
    engine.run('demo', as_of=TODAY)
    assert len(read_history(store, 'demo', '2026-09-14')['entries']) > 0
    return store, engine


def daily(store, day='2026-09-14', horizon=TODAY, workspace='demo'):
    return build_daily_report(store, workspace, day, horizon, current_date=TODAY)


def append_detection(store, alert_id, evidence, stamp='2026-10-22T00:00:00+00:00', value=123):
    with store.connect() as con:
        return con.execute('INSERT INTO alert_detections(alert_id,metric_value,evidence_json,created_at) VALUES(?,?,?,?)',
                           (alert_id,value,json.dumps(evidence),stamp)).lastrowid


def test_history_uses_evidence_window_not_creation_or_initial_alert_window(tmp_path):
    store, engine = historical(tmp_path)
    e = read_history(store, 'demo', '2026-09-14')['entries'][0]
    with store.connect() as con:
        con.execute("UPDATE alerts SET period_end='2026-09-30',current_triggered=0,status='已解决' WHERE id=?", (e['alert_id'],))
    result = read_history(store, 'demo', '2026-09-14')
    found = next(r for r in result['entries'] if r['alert_id'] == e['alert_id'])
    assert found['end'] == '2026-09-14' and found['status'] == '已解决'
    assert read_history(store, 'demo', '2026-09-30')['entries'] == []
    assert '不是报告日' in result['limits'] and '历史触发' in result['limits']


def test_latest_detection_dedup_tie_break_and_versions_stay_separate(tmp_path):
    store, engine = historical(tmp_path)
    first = store.query('SELECT * FROM alert_detections ORDER BY id').iloc[0]
    evidence = json.loads(first.evidence_json)
    id1 = append_detection(store, int(first.alert_id), evidence)
    id2 = append_detection(store, int(first.alert_id), evidence, value=124)
    rows = read_history(store, 'demo', '2026-09-14')['entries']
    assert id2 in {r['detection_id'] for r in rows} and id1 not in {r['detection_id'] for r in rows}
    alert = store.query('SELECT * FROM alerts WHERE id=?', (int(first.alert_id),)).iloc[0]
    rule = next(r for r in engine.rules('demo') if r['id'] == int(alert.rule_id))
    engine.configure('demo', rule['id'], rule['version'], 'test', 'Synthetic版本核查', name='第二版规则')
    engine.run('demo', as_of=TODAY)
    rows = [r for r in read_history(store, 'demo', '2026-09-14')['entries'] if r['rule_id'] == rule['id']]
    assert {r['version'] for r in rows} == {1,2}
    assert all(r['name'] == '第二版规则' for r in rows if r['version'] == 2)
    assert all(r['name'] != '第二版规则' for r in rows if r['version'] == 1)


@pytest.mark.parametrize('fault', ['json', 'period', 'snapshot', 'timestamp'])
def test_incomplete_history_is_explicit_and_does_not_invent_advice(tmp_path, fault):
    store, _ = historical(tmp_path)
    row = store.query('SELECT * FROM alert_detections ORDER BY id').iloc[0]
    evidence = json.loads(row.evidence_json)
    if fault == 'json':
        evidence = ['not-an-object']
    elif fault == 'period':
        evidence['period'] = {'end':'bad-date'}
    elif fault == 'snapshot':
        with store.connect() as con:
            con.execute("UPDATE alerts SET rule_snapshot='{}' WHERE id=?", (int(row.alert_id),))
    append_detection(store, int(row.alert_id), evidence, stamp='bad' if fault == 'timestamp' else '2026-10-22T00:00:00+00:00')
    report = daily(store)
    assert report['history']['incomplete'] > 0
    assert '历史证据不足' in report['history']['message']
    incomplete_ids = {e['detection_id'] for e in report['history']['entries'] if not e['complete']}
    assert not any(f'检测证据 #{idx}；' in g['basis'] for idx in incomplete_ids for g in report['guidance'])


def test_empty_no_match_and_workspace_separation(tmp_path):
    store = Store(tmp_path)
    report = daily(store)
    assert report['history']['entries'] == [] and '未找到检测证据' in report['history']['message']
    assert [g['title'] for g in report['guidance']] == ['核查历史证据范围']
    store, _ = historical(tmp_path)
    assert read_history(store, 'business', '2026-09-14')['entries'] == []
    assert '不能据此认定无异常' in read_history(store, 'demo', '2026-09-01')['message']


def test_guidance_only_uses_proven_categories_and_current_data_limits(tmp_path):
    store, _ = historical(tmp_path)
    report = daily(store, horizon=date(2026,9,14))
    business = [g for g in report['guidance'] if g['title'].startswith('历史证据核查')]
    assert len(business) == sum(e['complete'] for e in report['history']['entries'])
    assert any('库存快照' in g['action'] for g in business)
    assert any('成本证据待补充' in g['title'] for g in report['guidance'])
    assert any('退款样本尚未成熟' in g['title'] for g in report['guidance'])
    report['history']['entries'] = []
    report['comparisons']['sales']['value'] = -1
    suggestions = build_guidance(report)
    assert not any(g['title'].startswith('历史证据核查') for g in suggestions)
    assert not any('销售下降' in g['title'] for g in suggestions)
    report = daily(store)
    report['history']['entries'][0]['status'] = '已忽略'
    assert '仅作复核参考，不计新待办' in build_guidance(report)[0]['limit']


def test_html_escaping_allowlist_and_no_environment_paths(tmp_path):
    store, _ = historical(tmp_path)
    report = daily(store)
    malicious = '<script>alert("x")</script><img src="https://example.invalid/leak">'
    report['history']['entries'][0]['name'] = malicious
    report['history']['entries'][0]['basis'] = '凭证 C:\\Users\\SecretUser\\private.sqlite'
    report['current']['orders_detail'][0]['source_file'] = '/home/SecretUser/raw.csv'
    report['current']['actor'] = 'SecretUser'
    view = public_view(report, '模拟演示')
    html = report_html(view).decode('utf8')
    assert '<script' not in html and '<img' not in html and escape(malicious, quote=True) in html
    assert 'SecretUser' not in html and 'private.sqlite' not in html
    assert str(tmp_path) not in html and 'source_file' not in html
    assert '<script' not in html and '<link' not in html
    for kpi in view['kpis']:
        for value in kpi.values():
            assert escape(value, quote=True) in html


def test_export_does_not_recompute_or_write_and_c1_metrics_unchanged(tmp_path, monkeypatch):
    store, _ = historical(tmp_path)
    report = daily(store)
    expected = deepcopy(report)
    before = snapshot(store)
    def forbidden(*args, **kwargs):
        raise AssertionError('Export must not access business services')
    monkeypatch.setattr(store, 'query', forbidden)
    monkeypatch.setattr(AlertEngine, 'run', forbidden)
    for _ in range(2):
        assert report_html(public_view(report, '模拟演示'))
    assert report == expected
    monkeypatch.undo()
    assert_snapshot(store, before)


def test_ui_and_html_share_values_guidance_dates_and_space(tmp_path, monkeypatch):
    store, _ = historical(tmp_path)
    before = snapshot(store)
    captured = {}
    original = st.download_button
    def capture(label, data, **kwargs):
        if label == '下载 HTML 日报':
            captured['html'] = data.decode('utf8')
        return original(label, data, **kwargs)
    monkeypatch.setattr(st, 'download_button', capture)
    monkeypatch.setenv('V2_DATA_DIR', str(tmp_path))
    view = AppTest.from_file(str(ROOT/'v2/app.py'), default_timeout=30).run()
    view.sidebar.radio[1].set_value('经营日报').run()
    assert not view.exception
    for metric in view.metric:
        assert escape(metric.value, quote=True) in captured['html']
    report = daily(store)
    for suggestion in report['guidance']:
        assert any(t.value == suggestion['title'] for t in view.text)
        assert escape(suggestion['title'], quote=True) in captured['html']
    view.date_input[1].set_value(date(2026,9,14)).run()
    assert '退款样本尚未成熟' in captured['html'] and view.metric[5].value == '数据不足'
    view.date_input[0].set_value(date(2026,9,1)).run()
    assert '暂无截至该日' in captured['html']
    view.sidebar.radio[0].set_value('业务数据').run()
    assert '业务数据' in captured['html'] and '尚未导入数据' in captured['html']
    assert '历史证据核查：' not in captured['html']
    assert not view.exception
    assert_snapshot(store, before)
