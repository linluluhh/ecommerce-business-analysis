from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from v2.ui_format import money, percent, percentage_points, roas, timestamp, display_times, rule_value
from v2.ui_status import Status, TEXT, value_state, quality_status
from v2.service import Store
from v2.metrics import MetricCenter
from v2.demo import frames

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('formatter,value,expected', [
    (money, Decimal('1364'), '1364.00 USD'),
    (money, Decimal('0'), '0.00 USD'),
    (money, Decimal('-15.48'), '-15.48 USD'),
    (percent, Decimal('0.1786'), '17.86%'),
    (percentage_points, Decimal('0.1548'), '上涨15.48个百分点'),
    (percentage_points, Decimal('-0.05'), '下降5.00个百分点'),
    (percentage_points, Decimal('0'), '持平0.00个百分点'),
    (roas, Decimal('1.8'), '1.80倍'),
    (money, None, '数据不足'),
    (percent, None, '数据不足'),
    (percent, 'not-a-number', '数据不足'),
    (percentage_points, 'not-a-number', '数据不足'),
    (percent, Decimal('sNaN'), '数据不足'),
    (money, Decimal('NaN'), '数据不足'),
    (timestamp, '2026-10-14T08:28:59+00:00', '2026-10-14 16:28'),
    (timestamp, '2026-10-14T16:28:00+08:00', '2026-10-14 16:28'),
    (timestamp, '2026-10-14', '2026-10-14'),
])
def test_display_formats(formatter, value, expected):
    assert formatter(value) == expected


def test_status_priority_and_legitimate_zero():
    assert value_state(0, has_data=False) == Status.EMPTY_DATA
    assert value_state(None, has_match=False) == Status.NO_MATCH_DATA
    assert value_state(None) == Status.INSUFFICIENT_DATA
    assert value_state(None, applicable=False) == Status.NOT_APPLICABLE
    assert value_state(0) == Status.NORMAL
    assert value_state(0, warning=True) == Status.WARNING
    assert roas(None, Status.NOT_APPLICABLE) == '不适用'
    assert quality_status(False, False)[0] == Status.EMPTY_DATA
    assert quality_status(True, False)[0] == Status.NORMAL
    assert quality_status(True, True)[0] == Status.WARNING


def test_formatting_copies_leave_source_and_units_unchanged():
    source = pd.DataFrame([{'created_at': '2026-10-14T08:28:00Z', 'threshold': Decimal('.05')}])
    before = source.copy(deep=True)
    display = display_times(source)
    assert source.equals(before)
    assert display.created_at.iloc[0] == '2026-10-14 16:28'
    assert rule_value('margin_drop', source.threshold.iloc[0]) == '5.00个百分点'
    assert rule_value('roas_low', Decimal('1.8')) == '1.80倍'
    assert rule_value('sales_drop', Decimal('.2')) == '20.00%'
    assert rule_value('stock_low', 40) == '40.00件'


def app_for(tmp_path, monkeypatch):
    monkeypatch.setenv('V2_DATA_DIR', str(tmp_path))
    return AppTest.from_file(str(ROOT/'v2/app.py'), default_timeout=30).run()


def test_same_empty_database_consistent_on_all_pages_and_quality(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch)
    assert not app.exception
    assert app.metric[1].value == app.metric[2].value == TEXT[Status.EMPTY_DATA]
    assert any('未评估' in x.value for x in app.info)
    assert not any('未发现异常' in x.value or '没有异常' in x.value for x in app.success)
    for section in ('经营分析', '智能预警', '数据修订', '规则配置'):
        app.sidebar.radio[1].set_value(section).run()
        assert not app.exception
        assert any(TEXT[Status.EMPTY_DATA] in x.value for x in app.info)
        if section in ('经营分析'):
            assert app.metric[0].value == app.metric[3].value == TEXT[Status.EMPTY_DATA]


def test_loaded_ui_formats_without_changing_metrics_or_evidence(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ingest('synthetic.xlsx', (ROOT/'v2/demo_data/phase2_synthetic.xlsx').read_bytes(), 'workbook', 'demo')
    before = MetricCenter(store).calculate('demo')
    records = store.query('SELECT * FROM records')
    app = app_for(tmp_path, monkeypatch)
    assert app.metric[1].value == '1364.00 USD'
    app.sidebar.radio[1].set_value('经营分析').run()
    assert not app.exception
    assert app.metric[0].value == '1364.00 USD'
    assert app.metric[5].value == '3.57倍'
    assert MetricCenter(store).calculate('demo') == before
    assert store.query('SELECT * FROM records').equals(records)


def test_no_match_filter_is_not_empty_database(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ingest('normal.xlsx', (ROOT/'v2/demo_data/normal.xlsx').read_bytes(), 'workbook', 'demo')
    app = app_for(tmp_path, monkeypatch)
    app.sidebar.radio[1].set_value('经营分析').run()
    app.date_input[0].set_value((pd.Timestamp('2025-01-01').date(), pd.Timestamp('2025-01-02').date())).run()
    assert not app.exception
    assert app.metric[0].value == TEXT[Status.NO_MATCH_DATA]


def test_all_isolated_orders_show_insufficient_not_zero(tmp_path, monkeypatch):
    store = Store(tmp_path)
    orders = frames()['orders'].copy()
    orders['unit_price'] = '-10'
    store.ingest('bad.csv', orders.to_csv(index=False).encode('utf-8-sig'), 'orders', 'demo')
    app = app_for(tmp_path, monkeypatch)
    assert app.metric[1].value == TEXT[Status.INSUFFICIENT_DATA]
    app.sidebar.radio[1].set_value('经营分析').run()
    assert not app.exception
    assert app.metric[0].value == TEXT[Status.INSUFFICIENT_DATA]


def test_failed_import_does_not_claim_quality_success(tmp_path, monkeypatch):
    store = Store(tmp_path)
    assert store.ingest('bad.csv', b'bad\n1', 'orders', 'demo')['status'] == 'failed'
    app = app_for(tmp_path, monkeypatch)
    assert not app.exception
    assert app.metric[1].value == TEXT[Status.EMPTY_DATA]
    assert not any('未发现异常' in x.value for x in app.success)


def test_cancelled_order_zero_stays_zero_in_ui(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ingest('normal.xlsx', (ROOT/'v2/demo_data/normal.xlsx').read_bytes(), 'workbook', 'demo')
    app = app_for(tmp_path, monkeypatch)
    app.sidebar.radio[1].set_value('经营分析').run()
    next(item for item in app.selectbox if item.label == '监控订单状态').set_value('cancelled').run()
    assert not app.exception
    assert app.metric[0].value == '0.00 USD'
    assert MetricCenter(store).calculate('demo', status='cancelled')['sales'] == 0


def test_history_toggle_does_not_change_current_quality_status(tmp_path, monkeypatch):
    from v2.revisions import Revisions
    store = Store(tmp_path)
    store.ingest('normal.xlsx', (ROOT/'v2/demo_data/normal.xlsx').read_bytes(), 'workbook', 'demo')
    # Create and resolve a formatting-only flag on the existing cancelled order.
    row = store.query("SELECT id FROM records WHERE table_name='orders' ORDER BY id DESC").iloc[0]
    flow = Revisions(store)
    revision = flow.request('demo', int(row.id), {'country':'us'}, '模拟格式核查', 'Synthetic-test', 'test')
    flow.decide('demo', revision, '已批准', 'test', '核实')
    revision = flow.request('demo', int(row.id), {'country':'US'}, '模拟格式修订', 'Synthetic-test', 'test')
    flow.decide('demo', revision, '已批准', 'test', '核实')
    issues = store.anomalies('demo')
    assert not issues.empty and not issues.active.eq(1).any()
    app = app_for(tmp_path, monkeypatch)
    before = [item.value for item in app.success]
    next(item for item in app.checkbox if item.label == '包含已失效异常').check().run()
    assert not app.exception
    assert [item.value for item in app.success] == before
    assert any('未发现异常' in item.value for item in app.success)
