from datetime import date
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from v2.alerts import AlertEngine
from v2.metrics import MetricCenter
from v2.migrate import migrate
from v2.revisions import Revisions
from v2.service import Store
from v2.synthetic_phase2 import frames

ROOT=Path(__file__).resolve().parents[2]


def encode_frames(data):
    buf=BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        for name,frame in data.items():frame.to_excel(writer,sheet_name=name,index=False)
    return buf.getvalue()


def seed(store,errors=True,mutate=None,workspace='demo'):
    data=frames()
    if not errors:data['orders']=data['orders'].iloc[:-2].copy()
    if mutate:mutate(data)
    result=store.ingest('Synthetic-14days.xlsx',encode_frames(data),'workbook',workspace)
    assert result['status']=='imported',result


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path);seed(s);return s


def metric(store,**kw):
    return MetricCenter(store).calculate('demo','2026-09-08','2026-09-14',as_of='2026-10-10',**kw)


def kinds(store):
    return set(store.query('SELECT r.kind FROM alerts a JOIN alert_rules r ON a.rule_id=r.id').kind)


def test_unified_metrics_unknown_cost_and_lineage(store):
    m=metric(store)
    assert m['sales']==524 and m['known_cost_sales']==504
    assert m['gross_profit']==196 and m['goods_cost']==308
    assert m['unknown_orders']==1 and m['unknown_sales']==20
    assert m['profit_orders']==28 and m['orders']==29
    assert m['cost_coverage']==Decimal(504)/524
    assert sum(r['sales'] for r in m['orders_detail'])==m['sales']
    assert any(not r['known'] and r['goods_cost'] is None for r in m['orders_detail'])
    assert m['contribution']==-36
    total=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    legacy=store.metrics('demo')
    for key in ('sales','orders','gross_profit','goods_cost','refund_cost','recorded_ad_cost','contribution'):
        assert total[key]==legacy[key]


@pytest.mark.parametrize('filters',[{'sku':'SKU001'},{'platform':'Amazon'},{'sku':'SKU002','platform':'Amazon'},{'country':'US'},{'status':'cancelled'}])
def test_filtered_details_and_trends_agree(store,filters):
    center=MetricCenter(store)
    m=center.calculate('demo','2026-09-08','2026-09-14',as_of='2026-10-10',**filters)
    if m['sales'] is not None:
        assert sum(r['sales'] for r in m['orders_detail'])==m['sales']
        assert sum((r['sales'] or 0 for r in center.trend('demo','2026-09-08','2026-09-14',as_of='2026-10-10',**filters)))==m['sales']
    for row in m['orders_detail']:
        for k,v in filters.items():assert row[k]==v
    if filters.get('country'):assert m['contribution'] is None


def test_space_isolation(store):
    m=MetricCenter(store).calculate('business',as_of='2026-10-10')
    assert m['sales'] is None and m['gross_profit'] is None and m['orders']==0
    assert AlertEngine(store).run('business')['triggered']==0


def test_empty_unknown_only_metrics_are_not_zero(tmp_path):
    store=Store(tmp_path)
    empty=MetricCenter(store).calculate('demo')
    assert all(empty[k] is None for k in ['sales','gross_profit','gross_margin','roas','refund_rate','contribution'])
    data=frames();data['orders']=data['orders'][data['orders'].order_id.eq('SYNTH-UNKNOWN')]
    assert store.ingest('unknown.xlsx',encode_frames(data),'workbook','demo')['status']=='imported'
    m=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    assert m['sales']==20 and m['gross_profit'] is None and m['contribution'] is None


def test_full_metric_idempotency_and_migration(store):
    center=MetricCenter(store);before=center.calculate('demo',as_of='2026-10-10')
    file=store.query('SELECT raw_path FROM batches').iloc[0].raw_path
    assert store.ingest('renamed.xlsx',(store.root/file).read_bytes(),'workbook','demo')['added']==0
    for name,frame in frames().items():
        assert store.ingest(name+'.csv',frame.to_csv(index=False).encode('utf-8-sig'),name,'demo')['added']==0
    assert MetricCenter(Store(store.root)).calculate('demo',as_of='2026-10-10')==before
    migrate(store);migrate(store)
    assert len(store.query('SELECT * FROM schema_migrations'))==len(list((ROOT/'v2/migrations').glob('*.sql')))


def test_additive_migration_backs_up_existing_phase1_db(tmp_path):
    p=tmp_path/'monitor.sqlite'
    with sqlite3.connect(p) as con:
        con.executescript((ROOT/'v2/schema.sql').read_text(encoding='utf-8'))
        con.execute("INSERT INTO batches(id,workspace,filename,sha256,import_kind,raw_path,status,created_at,rule_version) VALUES('old','demo','old.csv','hash','orders','old.csv','imported','old','old')")
        con.execute("INSERT INTO records(workspace,batch_id,table_name,source_row,business_key,fingerprint,raw_json) VALUES('demo','old','orders',2,'key','hash','{}')")
    store=Store(tmp_path)
    migration=store.query('SELECT * FROM schema_migrations').iloc[0]
    assert Path(migration.backup_path).exists()
    with sqlite3.connect(migration.backup_path) as backup:assert backup.execute('SELECT count(*) FROM records').fetchone()[0]==1
    assert store.query('SELECT count(*) n FROM records').iloc[0].n==1
    assert store.query('SELECT count(*) n FROM operation_logs').iloc[0].n==0
    migrate(store)
    assert len(list((tmp_path/'backups').glob('*.sqlite')))==len(list((ROOT/'v2/migrations').glob('*.sql')))


def test_stock_sales_ads_and_refund_rules(store):
    result=AlertEngine(store).run('demo','2026-10-10')
    assert result['new']>0
    assert {'stock_low','stock_cover','stock_trend','sales_drop','roas_low','ad_spend_up','roas_drop','refund_rate_high','refund_sku','refund_platform_up'}<=kinds(store)
    assert 'margin_drop' not in kinds(store)  # BAD/UNKNOWN change comparison coverage
    assert 'contribution_drop' not in kinds(store)
    assert any('覆盖范围变化' in s for s in result['skipped'])


def test_valid_profit_deterioration_triggers(tmp_path):
    store=Store(tmp_path);seed(store,errors=False)
    AlertEngine(store).run('demo','2026-10-10')
    assert {'margin_drop','contribution_drop'}<=kinds(store)


def test_unknown_cost_share_rule(store):
    engine=AlertEngine(store);rule=next(r for r in engine.rules('demo') if r['kind']=='unknown_cost_up')
    engine.configure('demo',rule['id'],rule['version'],'测试员','演示低阈值',threshold=.02)
    engine.run('demo','2026-10-10')
    assert 'unknown_cost_up' in kinds(store)


@pytest.mark.parametrize('threshold,trigger',[(.1999,True),(.2,True),(.2001,False)])
def test_sales_decline_threshold_boundary(tmp_path,threshold,trigger):
    store=Store(tmp_path)
    def change(data):
        data['orders']=data['orders'][data['orders'].sku.eq('SKU001')].iloc[:-1].copy()
        data['orders']['unit_price']=20
        data['orders']['quantity']=1
        # 5 identical valid orders per day, price falls exactly20% in second window.
        rows=[]
        for day in pd.date_range('2026-09-01','2026-09-14'):
            for n in range(5):
                row=data['orders'].iloc[0].to_dict();row['order_id']=f'B-{day.day}-{n}';row['order_date']=str(day.date())
                row['unit_price']=20 if day.day<=7 else 16;rows.append(row)
        data['orders']=pd.DataFrame(rows)
    seed(store,False,change)
    engine=AlertEngine(store);rule=next(r for r in engine.rules('demo') if r['kind']=='sales_drop')
    engine.configure('demo',rule['id'],rule['version'],'测试员','边界',threshold=threshold)
    engine.run('demo','2026-10-10')
    assert ('sales_drop' in kinds(store))==trigger


def test_no_false_profit_improvement_when_cost_or_ad_missing(tmp_path):
    store=Store(tmp_path)
    def change(data):
        data['ads'].loc[data['ads'].date.ge('2026-09-08'),'ad_spend']=None
    seed(store,False,change)
    m=metric(store)
    assert m['recorded_ad_cost'] is None and m['roas'] is None and m['contribution'] is None
    report=AlertEngine(store).run('demo','2026-10-10')
    assert 'contribution_drop' not in kinds(store)
    assert report['skipped']


def test_roas_missing_attribution_is_unavailable(tmp_path):
    store=Store(tmp_path)
    def change(data):data['ads']['attributed_revenue']=None
    seed(store,False,change)
    m=metric(store)
    assert m['roas'] is None
    assert any('ROAS' in message for message in m['limits'])
    AlertEngine(store).run('demo','2026-10-10')
    assert 'roas_low' not in kinds(store)


def test_refund_cohort_vs_confirmation_date(store):
    m=metric(store)
    assert m['refund_rate']==Decimal(5)/28
    assert m['refund_cost']==50
    early=MetricCenter(store).calculate('demo','2026-09-08','2026-09-14',as_of='2026-09-15')
    assert early['refund_rate'] is None
    normal=Store(store.root/'crossmonth')
    normal.ingest('normal.xlsx',(ROOT/'v2/demo_data/normal.xlsx').read_bytes(),'workbook','demo')
    september=MetricCenter(normal).calculate('demo','2026-09-01','2026-09-30',as_of='2026-10-10')
    october=MetricCenter(normal).calculate('demo','2026-10-01','2026-10-10',as_of='2026-10-10')
    assert september['refund_cost']==0 and october['refund_cost']==5
    assert september['refund_rate']==0  # Oct1 is outside the12-day order cohort


def test_dedup_rule_versions_action_and_recurrence(store):
    engine=AlertEngine(store)
    first=engine.run('demo','2026-10-10');count=len(store.query('SELECT * FROM alerts'))
    assert engine.run('demo','2026-10-10')['new']==0
    assert len(store.query('SELECT * FROM alerts'))==count
    alert=store.query('SELECT * FROM alerts').iloc[0]
    for version,status in enumerate(['处理中','已解决','已忽略','待处理']):
        engine.action('demo',int(alert.id),status,'凭证核查','测试员',version)
    assert len(store.query('SELECT * FROM alert_actions'))==4
    with pytest.raises(ValueError):engine.action('demo',int(alert.id),'已解决','','测试员',4)
    assert engine.run('demo','2026-10-10')['new']==0
    rule=engine.rules('demo')[0]
    engine.configure('demo',rule['id'],rule['version'],'测试员','调整演示阈值',threshold=50)
    assert engine.run('demo','2026-10-10')['new']>0
    snapshot=json.loads(store.query('SELECT rule_snapshot FROM alerts WHERE id=?',(int(alert.id),)).iloc[0].rule_snapshot)
    assert snapshot['threshold']==40 and snapshot['version']==1
    # A new period creates a new task even if the previous period was resolved.
    engine.action('demo',int(alert.id),'已解决','本周期结束','测试员',4)
    newer=store.query("SELECT * FROM alerts WHERE rule_id=? AND object_key=? AND rule_version=2",(int(alert.rule_id),alert.object_key)).iloc[0]
    engine.action('demo',int(newer.id),'已解决','新版本周期结束','测试员',int(newer.state_version))
    new=frames()['orders'].iloc[[0]].copy();new['order_id']='NEXT';new['order_date']='2026-09-15'
    store.ingest('next.csv',new.to_csv(index=False).encode(),'orders','demo')
    inventory=pd.DataFrame([{'date':'2026-09-15','sku':'SKU001','opening_stock':21,'inbound_qty':0,'sold_qty':1,'closing_stock':20}])
    store.ingest('next_inventory.csv',inventory.to_csv(index=False).encode(),'inventory','demo')
    engine.run('demo','2026-10-10')
    assert store.query("SELECT count(*) n FROM alerts WHERE period_end='2026-09-15' AND rule_id=? AND object_key=?",(int(alert.rule_id),alert.object_key)).iloc[0].n>0


def test_revision_approval_single_effective_version_and_stale_request(store):
    row=store.query("SELECT id,raw_json FROM records WHERE raw_json LIKE '%SYNTH-BAD%'").iloc[0]
    workflow=Revisions(store);before=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    original=row.raw_json
    rid=workflow.request('demo',int(row.id),{'unit_price':20},'负价录入错误','凭证 SYNTH-001','申请人')
    stale=workflow.request('demo',int(row.id),{'unit_price':30},'另一旧版本申请','凭证 SYNTH-002','申请人')
    assert MetricCenter(store).calculate('demo',as_of='2026-10-10')==before
    workflow.decide('demo',rid,'已批准','复核员','核对原始平台凭证')
    after=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    assert after['sales']==before['sales']+20 and after['orders']==before['orders']+1
    assert store.query('SELECT raw_json FROM records WHERE id=?',(int(row.id),)).iloc[0].raw_json==original
    assert len([r for r in after['orders_detail'] if r['record_id']==row.id])==1
    assert next(r for r in after['orders_detail'] if r['record_id']==row.id)['revision_ids']==[rid]
    with pytest.raises(ValueError,match='旧版本'):workflow.decide('demo',stale,'已批准','复核员','审核旧版本')
    workflow.decide('demo',stale,'已驳回','复核员','旧版本拒绝')
    assert MetricCenter(Store(store.root)).calculate('demo',as_of='2026-10-10')['sales']==after['sales']


def test_revision_rejection_invalid_values_and_cross_space(store):
    row=store.query("SELECT id FROM records WHERE raw_json LIKE '%SYNTH-BAD%'").iloc[0]
    r=Revisions(store)
    with pytest.raises(ValueError):r.request('business',int(row.id),{'unit_price':20},'原因','证据','人')
    with pytest.raises(ValueError):r.request('demo',int(row.id),{'order_id':'new'},'原因','证据','人')
    with pytest.raises(ValueError):r.request('demo',int(row.id),{'unit_price':20},'原因','','人')
    before=store.metrics('demo')
    rid=r.request('demo',int(row.id),{'unit_price':20},'原因','证据','人')
    r.decide('demo',rid,'已驳回','复核','证据不足')
    assert store.metrics('demo')==before
    rid=r.request('demo',int(row.id),{'unit_price':-50},'原因','证据','人')
    r.decide('demo',rid,'已批准','复核','仅批准版本，不授权非法金额')
    assert store.metrics('demo')['sales']==before['sales']


def test_missing_period_or_zero_base_skips_comparison(tmp_path):
    store=Store(tmp_path)
    seed(store,False,lambda data:data.update(orders=data['orders'][data['orders'].order_date.ge('2026-09-08')]))
    report=AlertEngine(store).run('demo','2026-10-10')
    assert 'sales_drop' not in kinds(store)
    assert any('记录不连续' in s for s in report['skipped'])


def test_rule_validation_workspace_and_migration_checksum(store):
    engine=AlertEngine(store);rule=engine.rules('demo')[0]
    with pytest.raises(ValueError):engine.configure('business',rule['id'],1,'人','原因',threshold=10)
    with pytest.raises(ValueError):engine.configure('demo',rule['id'],1,'人','原因',threshold=float('nan'))
    with pytest.raises(ValueError):engine.configure('demo',rule['id'],1,'人','原因',window_days=0)
    with store.connect() as con:con.execute("UPDATE schema_migrations SET sha256='bad'")
    with pytest.raises(RuntimeError,match='迁移文件'):migrate(store)


def test_cross_window_invalid_refund_cannot_improve_cohort_rate(store):
    order=frames()['orders'][frames()['orders'].order_date.eq('2026-09-14')].iloc[0].order_id
    refund=frames()['refunds'].iloc[[0]].copy()
    refund['refund_id']='INVALID-CROSS-WINDOW';refund['order_id']=order;refund['refund_date']='2026-09-16';refund['refund_amount']=1000
    store.ingest('refund.csv',refund.to_csv(index=False).encode(),'refunds','demo')
    assert metric(store)['refund_rate'] is None


def test_engine_excludes_incomplete_today(store):
    AlertEngine(store).run('demo','2026-09-14')
    assert all(end<'2026-09-14' for end in store.query('SELECT period_end FROM alerts').period_end)


def test_zero_ad_spend_and_zero_base_unavailable(tmp_path):
    store=Store(tmp_path)
    def change(data):
        data['ads']['ad_spend']=0
        data['orders'].loc[data['orders'].order_date.le('2026-09-07'),'discount']=20
    seed(store,False,change)
    assert metric(store)['roas'] is None
    AlertEngine(store).run('demo','2026-10-10')
    assert 'sales_drop' not in kinds(store)


def test_latest_inventory_missing_and_zero_demand_skip_cover(tmp_path):
    store=Store(tmp_path)
    def change(data):
        data['orders']['order_status']='cancelled'
        data['inventory']['sold_qty']=0
        data['inventory']['opening_stock']=0
        data['inventory']['closing_stock']=0
    seed(store,False,change)
    report=AlertEngine(store).run('demo','2026-10-10')
    assert 'stock_cover' not in kinds(store)
    assert any('样本不足' in text for text in report['skipped'])


def test_phase2_financial_metrics_match_v1_monthly_profit(tmp_path):
    from v2.rules import SCHEMAS
    store=Store(tmp_path)
    data={name:pd.read_csv(ROOT/f'data/raw/{name}.csv',dtype='string') for name in SCHEMAS}
    assert store.ingest('Synthetic-V1-reference.xlsx',encode_frames(data),'workbook','demo')['status']=='imported'
    reference=pd.read_csv(ROOT/'reports/tables/monthly_profit.csv')
    center=MetricCenter(store)
    for row in reference.to_dict('records'):
        start=pd.Timestamp(row['month']+'-01');end=start+pd.offsets.MonthEnd(0)
        m=center.calculate('demo',str(start.date()),str(end.date()),as_of='2026-10-12')
        for key,source in [('known_cost_sales','sales'),('goods_cost','goods_cost'),('gross_profit','gross_profit'),
                           ('refund_cost','refund_cost'),('recorded_ad_cost','recorded_ad_cost'),('contribution','contribution')]:
            assert abs(m[key]-Decimal(str(row[source])))<Decimal('0.00001'),(key,m[key],row[source])


def test_disabled_rule_and_cross_space_alert_action(store):
    engine=AlertEngine(store);rule=engine.rules('demo')[0]
    engine.configure('demo',rule['id'],1,'测试员','停用演示规则',enabled=0)
    engine.run('demo','2026-10-10')
    assert store.query('SELECT count(*) n FROM alerts WHERE rule_id=?',(rule['id'],)).iloc[0].n==0
    alert=store.query('SELECT * FROM alerts').iloc[0]
    with pytest.raises(ValueError):engine.action('business',int(alert.id),'已忽略','跨空间','测试员',0)


def test_revision_chain_keeps_one_effective_record(store):
    record=int(store.query("SELECT id FROM records WHERE raw_json LIKE '%SYNTH-BAD%'").iloc[0].id)
    workflow=Revisions(store);initial=store.metrics('demo')['sales']
    first=workflow.request('demo',record,{'unit_price':20},'模拟纠错','证据-1','申请')
    workflow.decide('demo',first,'已批准','审批','核验')
    second=workflow.request('demo',record,{'unit_price':22},'再次核查','证据-2','申请')
    workflow.decide('demo',second,'已批准','审批','核验新版本')
    data=MetricCenter(Store(store.root)).calculate('demo',as_of='2026-10-10')
    records=[r for r in data['orders_detail'] if r['record_id']==record]
    assert len(records)==1 and records[0]['sales']==22 and records[0]['revision_ids']==[first,second]
    assert data['sales']==initial+22


def test_inventory_rule_respects_configured_snapshot_minimum(store):
    engine=AlertEngine(store);rule=engine.rules('demo')[0]
    engine.configure('demo',rule['id'],1,'测试员','要求足够库存快照',min_sample=8)
    engine.run('demo','2026-10-10')
    assert store.query('SELECT count(*) n FROM alerts WHERE rule_id=?',(rule['id'],)).iloc[0].n==0


def test_reimport_approved_effective_record_is_idempotent(store):
    data=frames()['orders'];row=data[data.order_id.eq('SYNTH-BAD')].copy()
    record=int(store.query("SELECT id FROM records WHERE raw_json LIKE '%SYNTH-BAD%'").iloc[0].id)
    workflow=Revisions(store)
    rid=workflow.request('demo',record,{'unit_price':20},'修正','凭证','申请')
    workflow.decide('demo',rid,'已批准','审核','核实')
    before=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    count=len(store.query('SELECT * FROM records'))
    row['unit_price']=20
    result=store.ingest('corrected-export.csv',row.to_csv(index=False).encode(),'orders','demo')
    assert result['added']==0 and result['duplicates']==1
    assert len(store.query('SELECT * FROM records'))==count
    assert MetricCenter(store).calculate('demo',as_of='2026-10-10')==before


def test_country_normalization_keeps_completeness_denominator_consistent(tmp_path):
    store=Store(tmp_path)
    def change(data):data['orders']['country']='USA'
    seed(store,True,change)
    result=metric(store,country='US')
    assert result['sales']==524 and result['orders']==29
    assert result['data_completeness']==Decimal(29)/30


def test_cancelled_status_never_includes_completed_refunds(store):
    cancelled=frames()['orders'].iloc[[0]].copy();cancelled['order_id']='CANCELLED-SCOPE'
    cancelled['order_date']='2026-09-14';cancelled['order_status']='cancelled'
    store.ingest('cancelled.csv',cancelled.to_csv(index=False).encode(),'orders','demo')
    result=metric(store,status='cancelled')
    assert result['sales']==0 and result['orders']==0
    assert result['refund_cost']==0 and result['refunds_detail']==[] and result['ads_detail']==[]


def test_persistent_issue_across_periods_reuses_open_task(store):
    engine=AlertEngine(store);engine.run('demo','2026-10-10')
    alert=store.query("SELECT a.* FROM alerts a JOIN alert_rules r ON a.rule_id=r.id WHERE r.kind='stock_low' AND a.object_key='SKU:SKU001'").iloc[0]
    order=frames()['orders'].iloc[[0]].copy();order['order_id']='CONTINUOUS';order['order_date']='2026-09-15'
    store.ingest('next.csv',order.to_csv(index=False).encode(),'orders','demo')
    inventory=pd.DataFrame([{'date':'2026-09-15','sku':'SKU001','opening_stock':21,'inbound_qty':0,'sold_qty':1,'closing_stock':20}])
    store.ingest('stock.csv',inventory.to_csv(index=False).encode(),'inventory','demo')
    engine.run('demo','2026-10-10')
    same=store.query('SELECT * FROM alerts WHERE rule_id=? AND object_key=?',(int(alert.rule_id),alert.object_key))
    assert len(same)==1 and same.iloc[0].id==alert.id
    assert json.loads(same.iloc[0].evidence_json)['period']['end']=='2026-09-15'
    assert engine.run('demo','2026-09-15')['new']==0  # re-run prior historical period, no new task


def test_profit_sources_include_approved_cost_master_version(store):
    product=int(store.query("SELECT id FROM records WHERE table_name='products' AND raw_json LIKE '%SKU001%'").iloc[0].id)
    workflow=Revisions(store)
    rid=workflow.request('demo',product,{'unit_cost':9},'核对采购成本','采购凭证','申请')
    workflow.decide('demo',rid,'已批准','审核','核实成本')
    m=metric(store,sku='SKU001')
    assert all(r['cost_source']['record_id']==product and r['cost_source']['revision_ids']==[rid] for r in m['orders_detail'])
    AlertEngine(store).run('demo','2026-10-10')
    evidence=[json.loads(v) for v in store.query('SELECT evidence_json FROM alerts').evidence_json]
    assert any(any(source['record_id']==product and source['revision_ids']==[rid] for source in e['source_versions']) for e in evidence)


def test_inventory_only_can_alert_safety_but_not_coverage(tmp_path):
    store=Store(tmp_path);data=frames()
    for name in ('orders','ads','refunds'):data[name]=data[name].iloc[:0]
    data['inventory']=data['inventory'].iloc[:2].copy()
    data['inventory']['opening_stock']=0;data['inventory']['sold_qty']=0;data['inventory']['closing_stock']=0
    assert store.ingest('Inventory-only.xlsx',encode_frames(data),'workbook','demo')['status']=='imported'
    result=AlertEngine(store).run('demo','2026-10-10')
    assert 'stock_low' in kinds(store) and 'stock_cover' not in kinds(store)
    assert any('样本不足' in text for text in result['skipped'])


def test_all_rules_disabled_returns_zero_without_error(store):
    engine=AlertEngine(store)
    for rule in engine.rules('demo'):
        engine.configure('demo',rule['id'],rule['version'],'测试员','停用全部规则',enabled=0)
    assert engine.run('demo','2026-10-10')['triggered']==0
    assert store.query('SELECT count(*) n FROM alerts').iloc[0].n==0
