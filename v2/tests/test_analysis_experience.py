from datetime import date
from decimal import Decimal
from copy import deepcopy

import pytest

from v2.analysis_presentation import scope_summary, trend_summary, rank_rows, INTERPRETATIONS
from v2.metrics import DEFINITIONS
from test_analysis_page import seed, app


def test_kpi_layers_and_all_metrics_preserved(tmp_path, monkeypatch):
    seed(tmp_path)
    view = app(tmp_path, monkeypatch)
    assert [m.label for m in view.metric] == [
        '折后销售额（USD）', '有效订单数（笔）', '商品毛利（USD）', '暂估经营贡献利润（USD）',
        '商品毛利率', '广告归因ROAS（倍）', '12天退款订单率', '成本覆盖率', '订单可用率',
        '成本已知订单销售额（USD）', '筛选适用待处理预警（条）']
    assert [m.value for m in view.markdown if m.value.startswith('#### ')] [:4] == [
        '#### 核心经营指标', '#### 经营效率', '#### 数据可信度', '#### 待办提醒']


def test_scope_summary_uses_exact_result_and_filters():
    result = {'orders': 8, 'profit_orders': 6}
    filters = dict(platform='Amazon', sku='SKU001', country='US', status='completed')
    text = scope_summary(result, date(2026, 10, 1), date(2026, 10, 14), date(2026, 10, 20), filters)
    for value in ('2026-10-01 至 2026-10-14', '平台：Amazon', 'SKU：SKU001', '国家：US',
                  '订单状态：completed', '有效完成订单数：8', '成本已知订单数：6', '退款观察截止日：2026-10-20'):
        assert value in text


def test_scope_and_definitions_visible_after_filter(tmp_path, monkeypatch):
    store = seed(tmp_path)
    view = app(tmp_path, monkeypatch)
    next(s for s in view.selectbox if s.label == '监控SKU').set_value('SKU001').run()
    from v2.metrics import MetricCenter
    start, end = view.date_input[0].value
    horizon = view.date_input[1].value
    result = MetricCenter(store).calculate('demo', start, end, sku='SKU001', as_of=horizon)
    expected = scope_summary(result, start, end, horizon, dict(sku='SKU001'))
    assert expected in [i.value for i in view.info]
    definitions = next(d.value for d in view.dataframe if '指标含义' in d.value.columns)
    assert len(definitions) == len(DEFINITIONS)
    assert all(definitions[c].str.len().gt(0).all() for c in ('指标含义', '能说明什么', '不能说明什么'))


@pytest.mark.parametrize('rows,expected', [
    ([], '无法比较'),
    ([{'date':'2026-10-14','sales':10}], '无法比较'),
    ([{'date':'2026-10-12','sales':20},{'date':'2026-10-14','sales':10}], '无法比较'),
    ([{'date':'2026-10-13','sales':None},{'date':'2026-10-14','sales':10}], '无法比较'),
    ([{'date':'2026-10-13','sales':0},{'date':'2026-10-14','sales':10}], '基期为0'),
    ([{'date':'2026-10-13','sales':100},{'date':'2026-10-14','sales':Decimal('91.5')}], '下降8.50%'),
    ([{'date':'2026-10-13','sales':10},{'date':'2026-10-14','sales':10}], '持平'),
    ([{'date':'2026-10-13','sales':10},{'date':'2026-10-14','sales':20}], '上升100.00%'),
])
def test_trend_only_compares_calendar_last_two_days(rows, expected):
    text = trend_summary(rows, date(2026, 10, 14))
    assert text.startswith('2026-10-14销售额较2026-10-13')
    assert expected in text
    if expected in ('基期为0', '无法比较'):
        assert '%' not in text


def test_rankings_keep_unknown_out_and_negative_profit_in():
    rows = [{'SKU':'unknown','销售额':100,'毛利':None,'成本覆盖率':0},
            {'SKU':'loss','销售额':40,'毛利':-10,'成本覆盖率':1},
            {'SKU':'zero','销售额':30,'毛利':0,'成本覆盖率':1},
            {'SKU':'partial','销售额':50,'毛利':8,'成本覆盖率':Decimal('.5')}]
    before = deepcopy(rows)
    assert [r['SKU'] for r in rank_rows(rows,'销售额','SKU',2)] == ['unknown','partial']
    ranked = rank_rows(rows,'毛利','SKU')
    assert [r['SKU'] for r in ranked] == ['partial','zero','loss']
    assert ranked[0]['成本覆盖率'] == Decimal('.5')
    assert rows == before
    assert rank_rows([{'平台':'A','暂估贡献':None}], '暂估贡献','平台') == []
    assert [r['平台'] for r in rank_rows([{'平台':'A','暂估贡献':-5},{'平台':'B','暂估贡献':2}], '暂估贡献','平台')] == ['B','A']


def test_explanations_cover_all_existing_metrics():
    assert set(INTERPRETATIONS) == set(DEFINITIONS)
    assert '整体盈利' in INTERPRETATIONS['roas'][2]


def test_rendered_rankings_use_existing_service_results(tmp_path, monkeypatch):
    from v2.metrics import MetricCenter
    from v2.ui_format import money
    store = seed(tmp_path)
    view = app(tmp_path, monkeypatch)
    sku_tables = [d.value for d in view.dataframe if 'SKU' in d.value.columns and '毛利' in d.value.columns]
    assert len(sku_tables) == 3  # Original table, sales ranking, gross-profit ranking.
    original, sales, gross = sku_tables
    sales_values = {row['SKU']: Decimal(row['销售额'].removesuffix(' USD')) for _, row in original.iterrows()}
    assert sales['SKU'].tolist() == sorted(sales_values, key=lambda key: (-sales_values[key], key))[:5]
    assert gross['毛利'].str.endswith(' USD').all()
    assert '成本覆盖率' in gross.columns
    start, end = view.date_input[0].value
    horizon = view.date_input[1].value
    center = MetricCenter(store)
    result = center.calculate('demo', start, end, as_of=horizon)
    expected = [{'平台': name, '暂估贡献': center.calculate('demo', start, end, platform=name, as_of=horizon)['contribution']}
                for name in sorted({r['platform'] for r in result['orders_detail']})]
    expected = rank_rows(expected, '暂估贡献', '平台')
    platforms = next(d.value for d in view.dataframe if set(d.value.columns) == {'平台','暂估贡献','成本覆盖率'})
    assert platforms['平台'].tolist() == [r['平台'] for r in expected]
    assert platforms['暂估贡献'].tolist() == [money(r['暂估贡献']) for r in expected]
