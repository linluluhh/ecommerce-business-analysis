from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from v2.demo import frames, error_csv
from v2.rules import ROOT, SCHEMAS, check
from v2.service import Store

FIXTURE = ROOT/'v2/demo_data/normal.xlsx'


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    assert s.ingest('normal.xlsx',FIXTURE.read_bytes(),'workbook','demo')['status']=='imported'
    return s


def csv(frame):
    return frame.to_csv(index=False).encode('utf-8-sig')


def test_normal_amounts_and_confirmation_month(store):
    m = store.metrics('demo')
    assert (m['orders'],m['sales'],m['gross_profit'],m['contribution'])==(1,Decimal('35'),Decimal('19'),Decimal('5'))
    assert m['monthly']['2026-09']['contribution']==10
    assert m['monthly']['2026-10']['refund_cost']==5
    assert m['monthly']['2026-10']['contribution']==-5
    assert store.metrics('business')['orders']==0


def test_byte_identical_duplicate_and_evidence(store):
    assert store.ingest('renamed.xlsx',FIXTURE.read_bytes(),'workbook','demo')['status']=='duplicate'
    assert store.metrics('demo')['sales']==35
    batches = store.query('SELECT * FROM batches')
    assert len(batches)==2
    assert all((store.root/p).read_bytes()==FIXTURE.read_bytes() for p in batches.raw_path)
    assert len(store.query('SELECT * FROM operation_logs'))==2


def test_csv_excel_row_idempotency_and_reordered_columns(store):
    frame = frames()['orders']
    result = store.ingest('orders.csv',csv(frame[frame.columns[::-1]]),'orders','demo')
    assert result['added']==0 and result['duplicates']==2
    assert store.metrics('demo')['sales']==35


def test_partial_overlap_and_exact_duplicates(store):
    frame = frames()['orders']
    new = frame.iloc[[0]].copy()
    new['order_id']='NEW'
    result = store.ingest('overlap.csv',csv(pd.concat([frame,new,new])),'orders','demo')
    assert result['added']==1 and result['duplicates']==3
    assert store.metrics('demo')['sales']==70


def test_conflict_isolates_all_versions(store):
    frame = frames()['orders'].iloc[[0]].copy()
    frame['unit_price']=30
    assert store.ingest('conflict.csv',csv(frame),'orders','demo')['added']==1
    m = store.metrics('demo')
    assert m['orders']==0 and m['sales']==0 and m['refund_cost']==0
    issues = store.anomalies('demo')
    assert len(issues[(issues.code=='business_key_conflict') & issues.active.eq(1)])==2
    assert store.query("SELECT count(*) n FROM records WHERE table_name='orders'").iloc[0].n==3


def test_errors_are_not_filled_or_deleted(store):
    assert store.ingest('errors.csv',error_csv(),'orders','demo')['status']=='imported'
    m = store.metrics('demo')
    assert m['sales']==70  # unknown SKU retains 35 revenue, never assumes zero cost
    assert m['gross_profit']==19 and m['profit_orders']==1
    assert m['isolated_records']==4 and m['profit_isolated']==1
    records = store.query("SELECT raw_json FROM records WHERE table_name='orders'")
    assert any(json.loads(r)['shipping_fee'] is None for r in records.raw_json)
    assert len(records)==7


@pytest.mark.parametrize('status',['待核实','确认','驳回'])
def test_review_states_hard_error_never_released(store,status):
    store.ingest('errors.csv',error_csv(),'orders','demo')
    issue = store.anomalies('demo').query("code=='invalid_price'").iloc[0]
    store.review(int(issue.id),status,'核查凭证', '财务',int(issue.version),'demo')
    saved = store.anomalies('demo').set_index('id').loc[issue.id]
    assert saved.status==status and saved.version==1
    assert store.metrics('demo')['sales']==70
    assert len(store.query('SELECT * FROM reviews'))==1


def test_soft_false_positive_release_and_reopen(store):
    store.ingest('errors.csv',error_csv(),'orders','demo')
    issue = store.anomalies('demo').query("code=='review_high_price'").iloc[0]
    store.review(int(issue.id),'驳回','价格已核实为真实大额订单','财务',0,'demo')
    assert store.metrics('demo')['sales']==365  # +2*150-5
    store.review(int(issue.id),'待核实','需要复核凭证','财务',1,'demo')
    assert store.metrics('demo')['sales']==70
    assert len(store.query('SELECT * FROM reviews'))==2


def test_review_validates_note_and_optimistic_lock(store):
    store.ingest('errors.csv',error_csv(),'orders','demo')
    issue = store.anomalies('demo').query("code=='invalid_price'").iloc[0]
    with pytest.raises(ValueError):
        store.review(int(issue.id),'确认','','财务',0,'demo')
    with pytest.raises(ValueError):
        store.review(int(issue.id),'确认','凭证','财务',0,'business')
    store.review(int(issue.id),'确认','凭证','财务',0,'demo')
    with pytest.raises(ValueError,match='其他会话'):
        store.review(int(issue.id),'驳回','凭证','财务',0,'demo')


def test_bad_file_atomicity_and_preservation(store):
    bad = b'order_id,wrong\nABC,123\n'
    result = store.ingest('../bad.csv',bad,'orders','demo')
    assert result['status']=='failed'
    assert store.metrics('demo')['sales']==35
    batch = store.query('SELECT * FROM batches WHERE id=?',(result['batch_id'],)).iloc[0]
    assert (store.root/batch.raw_path).read_bytes()==bad
    assert len(store.query('SELECT * FROM records'))==7


def test_multi_sheet_parse_failure_rolls_back(store):
    buf = BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        frames()['orders'].to_excel(writer,sheet_name='orders',index=False)
        pd.DataFrame({'wrong':[1]}).to_excel(writer,sheet_name='products',index=False)
    assert store.ingest('bad.xlsx',buf.getvalue(),'workbook','demo')['status']=='failed'
    assert len(store.query('SELECT * FROM records'))==7


def test_missing_customer_keeps_revenue(store):
    frame = frames()['orders'].iloc[[0]].copy()
    frame['order_id']='NO_CUSTOMER'
    frame['customer_id']=None
    store.ingest('missing_customer.csv',csv(frame),'orders','demo')
    assert store.metrics('demo')['sales']==70


@pytest.mark.parametrize('field,value',[('unit_price','inf'),('quantity','1.5'),('order_date','bad'),('order_id',None),('order_status','unknown')])
def test_unusable_values_are_quarantined(store,field,value):
    frame = frames()['orders'].iloc[[0]].astype(object).copy()
    frame['order_id']='INVALID'
    frame[field]=value
    assert store.ingest('invalid.csv',csv(frame),'orders','demo')['status']=='imported'
    assert store.metrics('demo')['sales']==35


def test_orphan_resolved_by_later_order(store):
    refund = frames()['refunds'].copy()
    refund['refund_id']='R_NEW'
    refund['order_id']='LATE'
    store.ingest('refund.csv',csv(refund),'refunds','demo')
    issues = store.anomalies('demo')
    orphan = issues.query("code=='refund_orphan' and active==1").iloc[0]
    order = frames()['orders'].iloc[[0]].copy()
    order['order_id']='LATE'
    store.ingest('late.csv',csv(order),'orders','demo')
    assert store.anomalies('demo').set_index('id').loc[orphan.id].active==0
    assert store.metrics('demo')['refund_cost']==10


def test_cumulative_refund_over_order_isolated(store):
    refund = frames()['refunds'].copy()
    refund['refund_id']='R_OVER'
    refund['refund_amount']=31
    store.ingest('refund.csv',csv(refund),'refunds','demo')
    assert store.metrics('demo')['refund_cost']==0  # 5+31>35, both isolated


def test_immutable_evidence(store):
    with store.connect() as con:
        with pytest.raises(sqlite3.IntegrityError,match='immutable'):
            con.execute("UPDATE records SET raw_json='{}'")
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            con.execute('DELETE FROM operation_logs')


def test_concurrent_duplicate_ingestion(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:store.ingest('normal.xlsx',FIXTURE.read_bytes(),'workbook','business'),range(2)))
    assert sorted(r['status'] for r in results)==['duplicate','imported']
    assert store.metrics('business')['sales']==35


def test_unknown_ad_spend_not_zero(store):
    frame = frames()['ads'].copy()
    frame['campaign_id']='MISSING'
    frame['ad_spend']=None
    store.ingest('missing.csv',csv(frame),'ads','demo')
    assert store.metrics('demo')['recorded_ad_cost']==4
    assert store.metrics('demo')['partial']
    empty = Store(store.root/'empty').metrics('business')
    assert empty['recorded_ad_cost'] is None and empty['contribution'] is None


def test_v1_quality_parity_and_files_unchanged():
    paths = list((ROOT/'data/raw').glob('*'))+list((ROOT/'reports').rglob('*'))
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    tables = {n:pd.read_csv(ROOT/f'data/raw/{n}.csv',dtype='string') for n in SCHEMAS}
    _, issues = check(tables)
    actual = pd.DataFrame(issues).groupby(['table','issue']).size().to_dict()
    expected = pd.read_csv(ROOT/'data/processed/quality_issues.csv').groupby(['table','issue']).size().to_dict()
    assert actual==expected
    assert before=={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
