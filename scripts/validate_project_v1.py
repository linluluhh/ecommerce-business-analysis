"""独立验证成果，失败立即退出；验证的是业务对账而不是代码实现的镜像。"""
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import pandas as pd
import nbformat
from weekly_report import generate

ROOT=Path(__file__).resolve().parents[1]


def main():
    raw=ROOT/'data/raw';out=ROOT/'data/processed';t=ROOT/'reports/tables'
    manifest=json.loads((raw/'manifest.json').read_text(encoding='utf-8'))
    for name,profile in manifest['files'].items():
        assert hashlib.sha256((raw/name).read_bytes()).hexdigest()==profile['sha256']
        assert len(pd.read_csv(raw/name))==profile['rows']
    o=pd.read_csv(out/'orders_clean.csv',dtype={'order_id':str,'customer_id':str})
    assert len(o)==9952 and o.order_id.is_unique and o.customer_id.isna().sum()==12
    assert o.needs_review.sum()==8
    assert pd.read_csv(out/'customers_clean.csv').customer_id.is_unique
    r=pd.read_csv(out/'refunds_clean.csv')
    assert r.amount_needs_review.sum()==2
    assert r.order_id.isin(o.order_id).all()
    assert len(pd.read_csv(out/'ads_missing_expected_rows.csv'))==4
    assert pd.read_csv(out/'ads_clean.csv').ad_spend.isna().sum()==9
    facts=pd.read_csv(out/'profit_orders.csv')
    assert facts.order_status.eq('completed').all() and not facts.needs_review.any()
    assert facts.unit_cost.notna().all() and facts.order_id.is_unique
    # 用原始商品成本和事实订单数量重新求成本，不依赖已导出的goods_cost列。
    products=pd.read_csv(raw/'products.csv').set_index('sku')
    calc=facts.quantity*facts.sku_standard.map(products.unit_cost)
    assert (calc-facts.goods_cost).abs().max()<1e-8
    m=pd.read_csv(t/'monthly_profit.csv').set_index('month')
    assert abs(m.loc['2026-08','contribution']-50981.79)<1e-6
    assert abs(m.loc['2026-09','contribution']-30449.66)<1e-6
    decline=m.loc['2026-08','contribution']-m.loc['2026-09','contribution']
    assert abs(pd.read_csv(t/'profit_bridge.csv').profit_decline_impact.sum()-decline)<1e-6
    for name in ['platform_changes','sku_changes']:
        assert abs(pd.read_csv(t/(name+'.csv')).contribution_change.sum()+decline)<1e-6
    cohort=pd.read_csv(t/'refund_cohorts_12d.csv');sku4=cohort.loc[cohort.sku_standard.eq('SKU004')]
    assert sku4.refunded_orders.tolist()==[14,71]
    with sqlite3.connect(out/'business_analysis.sqlite') as conn:
        for name in ['01_monthly_profit','02_platform_profit','03_sku_refund_rates','04_quality_checks']:
            result=pd.read_sql_query((ROOT/'sql'/(name+'.sql')).read_text(encoding='utf-8'),conn)
            assert len(result)>0
            if name=='02_platform_profit':
                pm=result.groupby('month').contribution.sum()
                assert (pm-m.contribution).abs().max()<1e-6
            if name=='03_sku_refund_rates':
                joined=result.merge(cohort,on=['sku_standard','month'])
                assert (joined.refund_rate_pct_x-joined.refund_rate_pct_y).abs().max()<1e-7
    for name in ['01_data_cleaning_v1.ipynb','02_business_analysis_v1.ipynb']:
        nb=nbformat.read(ROOT/'notebooks'/name,as_version=4);nbformat.validate(nb)
        assert all(not any(o.get('output_type')=='error' for o in c.get('outputs',[])) for c in nb.cells)
        assert all(c.execution_count is not None for c in nb.cells if c.cell_type=='code')
    # AI草稿非法指标与擅自生成数字应被拒绝；不发送任何外部请求。
    with tempfile.TemporaryDirectory() as tmp:
        draft=Path(tmp)/'bad.json'
        for bad in [{'bullets':[{'metric_keys':['current.invented_profit'],'comment':'无依据'}]}, {'bullets':[{'metric_keys':['current.sales'],'comment':'增长999美元'}]}]:
            draft.write_text(json.dumps(bad,ensure_ascii=False),encoding='utf-8')
            try:generate('2026-09-21','2026-09-27',draft)
            except ValueError:pass
            else:raise AssertionError('AI非法草稿未被拒绝')
    generate('2026-09-21','2026-09-27',ROOT/'reports/weekly/ai_draft_example.json')
    checks=json.loads((ROOT/'reports/validation.json').read_text(encoding='utf-8'))
    checks.update({'independent_raw_cost_check':True,'refund_sql_pandas_reconciled':True,'all_v1_notebooks_executed':True,'ai_invalid_metric_rejected':True,'ai_unprovided_numeric_claim_rejected':True})
    (ROOT/'reports/validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: raw protection, grains, costs, refunds, bridges, SQL, notebooks and AI evidence gates.')


if __name__=='__main__':main()
