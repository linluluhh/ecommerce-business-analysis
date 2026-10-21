from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from v2.daily_report import build_daily_report, default_day, KPIS
from v2.daily_report_ui import formatted
from v2.demo import frames, workbook, error_csv
from v2.metrics import MetricCenter
from v2.service import Store
from v2.ui_status import Status

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 21)
D = date(2026, 9, 2)
TABLES = ('batches', 'records', 'anomalies', 'reviews', 'record_revisions', 'revision_reviews',
          'alerts', 'alert_detections', 'alert_actions', 'alert_rules', 'alert_rule_versions', 'operation_logs')


def seed(tmp_path, mutate=None, workspace='demo'):
    data = frames()
    data['orders'].loc[1, 'order_status'] = 'completed'
    data['ads'] = pd.concat([data['ads'], data['ads'].assign(date='2026-09-02')], ignore_index=True)
    data['ads'].loc[1, 'attributed_revenue'] = 20
    if mutate:
        mutate(data)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        for name, frame in data.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    store = Store(tmp_path)
    assert store.ingest('Synthetic-daily.xlsx', out.getvalue(), 'workbook', workspace)['status'] == 'imported'
    return store


def report(store, day=D, horizon=TODAY, workspace='demo'):
    return build_daily_report(store, workspace, day, horizon, current_date=TODAY)


def snapshot(store):
    return {table: store.query('SELECT * FROM ' + table + ' ORDER BY rowid') for table in TABLES}


def assert_snapshot(store, expected):
    for table, frame in expected.items():
        pd.testing.assert_frame_equal(store.query('SELECT * FROM ' + table + ' ORDER BY rowid'), frame)


def test_metric_parity_shared_snapshot_and_exact_calendar_day(tmp_path, monkeypatch):
    store = seed(tmp_path)
    center = MetricCenter(store)
    calls = []
    evaluate = store.evaluate
    def counted(*args):
        calls.append(True)
        return evaluate(*args)
    monkeypatch.setattr(store, 'evaluate', counted)
    result = build_daily_report(store, 'demo', D, TODAY, center=center, current_date=TODAY)
    assert len(calls) == 1
    assert result['current'] == center.calculate('demo', D, D, as_of=TODAY)
    assert result['previous'] == center.calculate('demo', '2026-09-01', '2026-09-01', as_of=TODAY)
    assert result['comparisons']['sales']['value'] == (Decimal('20')-35)/35
    assert result['comparisons']['orders']['value'] == 0
    assert result['comparisons']['gross_profit']['value'] == -7
    assert result['comparisons']['roas']['value'] == Decimal('-3.75')
    assert result['comparisons']['refund_rate']['value'] == 0
    missing = report(store, date(2026, 9, 4))
    assert missing['previous_day'] == date(2026, 9, 3)
    assert missing['current']['sales'] is None and missing['previous']['sales'] is None
    assert missing['comparisons']['sales']['value'] is None


def test_default_day_uses_order_dates_not_upload_ads_or_today(tmp_path):
    store = seed(tmp_path, lambda data: data['ads'].__setitem__('date', ['2026-10-19', '2026-10-20']))
    facts = MetricCenter(store).facts('demo')
    assert default_day(facts, TODAY) == D
    assert default_day(facts, D) == date(2026, 9, 1)
    assert default_day({'candidates': []}, TODAY) == date(2026, 10, 20)


@pytest.mark.parametrize('day,horizon', [(TODAY, TODAY), (date(2026,10,22), TODAY),
                                       (D, date(2026,9,1)), (D, date(2026,10,22))])
def test_invalid_dates_rejected(tmp_path, day, horizon):
    with pytest.raises(ValueError):
        report(Store(tmp_path), day, horizon)


def test_empty_no_match_missing_previous_and_unlocated_dates(tmp_path):
    store = Store(tmp_path)
    empty = report(store)
    assert all(item['state'] == Status.EMPTY_DATA for item in empty['states'].values())
    store = seed(tmp_path)
    first = report(store, date(2026,9,1))
    assert first['previous_states']['orders']['state'] == Status.NO_MATCH_DATA
    assert first['comparisons']['sales']['value'] is None
    missing = report(store, date(2026,8,30))
    assert missing['states']['sales']['state'] == Status.NO_MATCH_DATA
    store = seed(tmp_path/'undated', lambda data: data['orders'].__setitem__('order_date', ['bad', 'bad']))
    undated = report(store)
    assert undated['states']['sales']['state'] == Status.INSUFFICIENT_DATA
    assert '无法定位' in undated['states']['sales']['reason']


def test_unknown_cost_and_quality_limits_are_not_zero(tmp_path):
    store = seed(tmp_path, lambda data: data['orders'].loc.__setitem__((1,'sku'), 'SKU999'))
    result = report(store)
    assert result['current']['sales'] == 20
    assert result['current']['gross_profit'] is None
    assert result['current']['cost_coverage'] == 0
    assert result['current']['unknown_orders'] == 1
    assert result['has_quality_blocks']
    assert result['comparisons']['gross_profit']['value'] is None
    assert any('成本未知' in text for text in result['current']['limits'])


def test_partial_profit_comparison_discloses_sample_boundary(tmp_path):
    store = seed(tmp_path)
    store.ingest('errors.csv', error_csv(), 'orders', 'demo')
    result = report(store)
    assert result['comparisons']['gross_profit']['value'] is not None
    assert '仅可计算样本' in result['comparisons']['gross_profit']['text']


def test_zero_sales_zero_base_and_negative_profit(tmp_path):
    def zero(data):
        data['orders'].loc[0, 'discount'] = 40
    result = report(seed(tmp_path, zero))
    assert result['previous']['sales'] == 0
    assert formatted('sales', 0, result['previous_states']['sales']['state']) == '0.00 USD'
    assert result['comparisons']['sales']['state'] == Status.NOT_APPLICABLE
    assert result['comparisons']['sales']['value'] is None
    assert result['previous']['gross_profit'] < 0
    assert result['comparisons']['gross_profit']['value'] == 28
    assert 'USD' in result['comparisons']['gross_profit']['text']


def test_isolated_zero_count_is_not_a_comparable_zero(tmp_path):
    result = report(seed(tmp_path, lambda data: data['orders'].loc.__setitem__((1,'unit_price'), -10)))
    assert result['current']['orders'] == 0
    assert result['states']['orders']['state'] == Status.INSUFFICIENT_DATA
    assert result['comparisons']['orders']['value'] is None
    assert result['current']['sales'] is None


def test_cancelled_order_preserves_legitimate_zero(tmp_path):
    store = Store(tmp_path)
    store.ingest('normal.xlsx', workbook(), 'workbook', 'demo')
    result = report(store)
    assert formatted('orders', result['current']['orders'], result['states']['orders']['state']) == '0 笔'
    assert formatted('sales', result['current']['sales'], result['states']['sales']['state']) == '0.00 USD'
    assert result['comparisons']['orders']['value'] == -1


def test_refund_horizon_and_ads_independent_of_orders(tmp_path):
    store = seed(tmp_path)
    immature = report(store, horizon=D)
    assert immature['current']['refund_rate'] is None
    assert '尚未观察满12天' in immature['states']['refund_rate']['reason']
    mature = report(store, horizon=date(2026,9,14))
    assert mature['current']['refund_rate'] == 0
    assert mature['current'] == MetricCenter(store).calculate('demo', D, D, as_of=date(2026,9,14))
    # A valid advertising KPI must not be hidden just because orders have no matching date.
    store = seed(tmp_path/'ads-only-day', lambda data: data['ads'].loc.__setitem__((1,'date'), '2026-09-03'))
    # Confirm the deliberate timing difference through the existing soft-rule review.
    for issue in store.anomalies('demo').query("table_name == 'ads' and hard == 0 and scope == 'all'").itertuples():
        store.review(int(issue.id), '驳回', 'Synthetic归因时间差已核对', 'test', int(issue.version), 'demo')
    result = report(store, date(2026,9,3))
    assert result['states']['sales']['state'] == Status.NO_MATCH_DATA
    assert result['current']['roas'] == Decimal('5')
    assert formatted('roas', result['current']['roas'], result['states']['roas']['state']) == '5.00倍'


def test_service_and_page_read_only_and_workspace_isolation(tmp_path, monkeypatch):
    from v2.alerts import AlertEngine
    from v2.revisions import Revisions
    store = seed(tmp_path)
    store.ingest('errors.csv', error_csv(), 'orders', 'demo')
    issue = store.anomalies('demo').query("code == 'invalid_price'").iloc[0]
    store.review(int(issue.id), '确认', 'Synthetic核查', 'test', int(issue.version), 'demo')
    Revisions(store).request('demo', int(issue.record_id), {'unit_price':'20'}, 'Synthetic', '凭证', 'test')
    AlertEngine(store).run('demo', as_of=TODAY)
    before = snapshot(store)
    result = report(store)
    assert result['workspace'] == 'demo'
    assert report(store, workspace='business')['states']['sales']['state'] == Status.EMPTY_DATA
    monkeypatch.setenv('V2_DATA_DIR', str(tmp_path))
    view = AppTest.from_file(str(ROOT/'v2/app.py'), default_timeout=30).run()
    view.sidebar.radio[1].set_value('经营日报').run()
    assert not view.exception
    assert [m.label for m in view.metric] == [label for _, label, _ in KPIS]
    assert view.date_input[0].value == D
    assert view.metric[0].value == '20.00 USD'
    assert [button.label for button in view.get('download_button')] == ['下载 HTML 日报']
    next(item for item in view.date_input if item.label == '退款观察截止日 H').set_value(D).run()
    assert view.metric[5].value == '数据不足'
    next(item for item in view.date_input if item.label == '经营日期 D').set_value(date(2026,9,4)).run()
    assert view.metric[0].value == '当前范围无匹配数据'
    assert view.date_input[1].value >= view.date_input[0].value
    view.sidebar.radio[0].set_value('业务数据').run()
    assert not view.exception
    assert all(m.value == '尚未导入数据' for m in view.metric)
    view.sidebar.radio[0].set_value('模拟演示').run()
    assert view.date_input[0].value == date(2026,9,4)
    view.sidebar.radio[1].set_value('经营分析').run()
    assert not view.exception and len(view.metric) == 11
    view.sidebar.radio[1].set_value('数据运营工作台').run()
    assert not view.exception
    assert_snapshot(store, before)


def test_empty_fallback_updates_after_first_import(tmp_path, monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR', str(tmp_path))
    view = AppTest.from_file(str(ROOT/'v2/app.py'), default_timeout=30).run()
    view.sidebar.radio[1].set_value('经营日报').run()
    assert view.metric[0].value == '尚未导入数据'
    seed(tmp_path)
    view.sidebar.radio[1].set_value('数据运营工作台').run()
    view.sidebar.radio[1].set_value('经营日报').run()
    assert not view.exception
    assert view.date_input[0].value == D
    assert view.metric[0].value == '20.00 USD'
