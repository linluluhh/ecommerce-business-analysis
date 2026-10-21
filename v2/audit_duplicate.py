"""Reproduce duplicate imports in fresh stores; inspect the existing DB read-only."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import pandas as pd
from v2.demo import error_csv, workbook
from v2.rules import ROOT
from v2.service import Store

EVIDENCE = ROOT/'v2/evidence/duplicate-upload'
BASELINE = 'db4f973'


def encode(value):
    if isinstance(value,Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def readonly(path):
    con = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory = sqlite3.Row
    return con


def independent_aggregates(path, workspace='demo'):
    """SQL and Pandas independently select samples from immutable rows and flags."""
    cte = '''WITH valid AS (
      SELECT r.*,json_extract(raw_json,'$.order_id') oid,
      json_extract(raw_json,'$.order_status') ost,
      upper(trim(json_extract(raw_json,'$.sku'))) sku,
      CAST(json_extract(raw_json,'$.unit_cost') AS REAL) unit_cost,
      CAST(json_extract(raw_json,'$.quantity') AS REAL) qty,
      CAST(json_extract(raw_json,'$.unit_price') AS REAL) price,
      CAST(json_extract(raw_json,'$.discount') AS REAL) discount,
      CAST(json_extract(raw_json,'$.shipping_fee') AS REAL) shipping,
      CAST(json_extract(raw_json,'$.platform_fee') AS REAL) platform
      FROM records r WHERE workspace=? AND NOT EXISTS (
        SELECT 1 FROM anomalies a WHERE a.record_id=r.id AND active=1 AND scope='all'
        AND (hard=1 OR status!='驳回'))
    ), orders AS (SELECT *,qty*price-discount amount FROM valid WHERE table_name='orders' AND ost='completed'),
    known AS (SELECT o.*,p.unit_cost cost FROM orders o JOIN valid p ON p.table_name='products' AND p.sku=o.sku AND p.unit_cost>0
      WHERE NOT EXISTS (SELECT 1 FROM anomalies a WHERE a.record_id=o.id AND active=1 AND scope='profit' AND (hard=1 OR status!='驳回')))
    '''
    with readonly(path) as con:
        sql = dict(con.execute(cte+'''SELECT (SELECT COUNT(*) FROM orders) orders,
        (SELECT COALESCE(SUM(amount),0) FROM orders) sales,
        (SELECT COALESCE(SUM(amount),0) FROM known) known_sales,
        (SELECT COALESCE(SUM(qty*cost),0) FROM known) goods_cost,
        (SELECT COALESCE(SUM(shipping),0) FROM known) shipping_cost,
        (SELECT COALESCE(SUM(platform),0) FROM known) platform_cost,
        (SELECT COALESCE(SUM(CAST(json_extract(raw_json,'$.refund_amount') AS REAL)),0) FROM valid
         WHERE table_name='refunds' AND json_extract(raw_json,'$.refund_status')='approved' AND oid IN (SELECT oid FROM known)) refund_cost,
        (SELECT SUM(CAST(json_extract(raw_json,'$.ad_spend') AS REAL)) FROM valid WHERE table_name='ads') recorded_ad_cost
        ''',(workspace,)).fetchone())
        records = [dict(r) for r in con.execute('SELECT * FROM records WHERE workspace=?',(workspace,))]
        flags = pd.read_sql_query('SELECT a.* FROM anomalies a JOIN records r ON a.record_id=r.id WHERE r.workspace=? AND active=1',con,params=(workspace,))
    for key,value in list(sql.items()):
        if key!='orders' and value is not None:
            sql[key]=Decimal(str(value))
    sql['gross_profit']=sql['known_sales']-sql['goods_cost']
    sql['contribution']=(sql['gross_profit']-sql['shipping_cost']-sql['platform_cost']-sql['refund_cost']-sql['recorded_ad_cost']) if sql['recorded_ad_cost'] is not None else None
    blocking = flags[(flags.hard.eq(1)) | (flags.status.ne('驳回'))]
    blocked=set(blocking[blocking.scope.eq('all')].record_id)
    profit_blocked=set(blocking[blocking.scope.eq('profit')].record_id)
    data = {n: [] for n in ['orders','products','refunds','ads']}
    for r in records:
        if r['id'] not in blocked and r['table_name'] in data:
            data[r['table_name']].append({**json.loads(r['raw_json']),'record_id':r['id']})
    products={r['sku'].strip().upper():Decimal(r['unit_cost']) for r in data['products'] if Decimal(r['unit_cost'])>0}
    orders=pd.DataFrame([r for r in data['orders'] if r['order_status']=='completed'])
    totals={key:Decimal(0) for key in ['sales','known_sales','goods_cost','shipping_cost','platform_cost','refund_cost']}
    known_ids=set()
    if not orders.empty:
        orders['amount']=orders.apply(lambda r:Decimal(r.quantity)*Decimal(r.unit_price)-Decimal(r.discount),axis=1)
        totals['sales']=orders.amount.sum()
        known=orders[orders.record_id.map(lambda idx:idx not in profit_blocked) & orders.sku.str.strip().str.upper().isin(products)].copy()
        if not known.empty:
            known_ids=set(known.order_id)
            totals['known_sales']=known.amount.sum()
            totals['goods_cost']=known.apply(lambda r:Decimal(r.quantity)*products[r.sku.strip().upper()],axis=1).sum()
            totals['shipping_cost']=known.shipping_fee.map(Decimal).sum()
            totals['platform_cost']=known.platform_fee.map(Decimal).sum()
    totals['orders']=len(orders)
    totals['refund_cost']=sum((Decimal(r['refund_amount']) for r in data['refunds'] if r['refund_status']=='approved' and r['order_id'] in known_ids),Decimal(0))
    totals['recorded_ad_cost']=sum((Decimal(r['ad_spend']) for r in data['ads']),Decimal(0)) if data['ads'] else None
    totals['gross_profit']=totals['known_sales']-totals['goods_cost']
    totals['contribution']=(totals['gross_profit']-totals['shipping_cost']-totals['platform_cost']-totals['refund_cost']-totals['recorded_ad_cost']) if data['ads'] else None
    assert sql==totals, (sql,totals)
    return {'sql':sql,'pandas':totals}


def history_snapshot(path):
    with readonly(path) as con:
        return {table:[dict(r) for r in con.execute(f'SELECT * FROM {table} ORDER BY id')]
                for table in ['batches','records','anomalies','reviews','operation_logs']}


def run():
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    source_db=ROOT/'v2/runtime/monitor.sqlite'
    existing_before=history_snapshot(source_db) if source_db.exists() else None
    parent=Path(tempfile.mkdtemp(prefix='duplicate-regression-',dir=ROOT/'v2/runtime'))
    normal=(ROOT/'v2/demo_data/normal.xlsx').read_bytes()
    duplicate=(ROOT/'v2/demo_data/duplicate.xlsx').read_bytes()
    assert normal==duplicate
    store=Store(parent/'clean')
    first=store.ingest('normal.xlsx',normal,'workbook','demo')
    before=store.metrics('demo')
    repeated=[]
    for i in range(3):
        repeated.append(store.ingest('duplicate.xlsx',duplicate,'workbook','demo'))
        assert store.metrics('demo')==before
    clean_aggregates=independent_aggregates(store.db)
    # Re-run the committed, pre-change implementation in another empty store.
    baseline_source=subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}',
                                            'show',f'{BASELINE}:v2/service.py'],cwd=ROOT,encoding='utf-8')
    namespace={'__file__':str(ROOT/'v2/service.py'),'__name__':'v2_duplicate_baseline'}
    exec(compile(baseline_source,namespace['__file__'],'exec'),namespace)
    original_store=namespace['Store'](parent/'original-code')
    original_store.ingest('normal.xlsx',normal,'workbook','demo')
    original_before=original_store.metrics('demo')
    original_store.ingest('duplicate.xlsx',duplicate,'workbook','demo')
    original_after=original_store.metrics('demo')
    assert original_before==original_after
    assert all(before[key]==value for key,value in original_before.items())
    original_store.ingest('errors.csv',error_csv(),'orders','demo')
    original_mixed=original_store.metrics('demo')
    assert original_mixed['sales']==70 and original_mixed['monthly']['2026-09']['contribution']==10
    # XLSX ZIP metadata changes do not bypass row-level idempotency.
    regenerated=store.ingest('regenerated.xlsx',workbook(),'workbook','demo')
    assert regenerated['added']==0 and store.metrics('demo')==before
    contaminated=Store(parent/'with-errors')
    contaminated.ingest('normal.xlsx',normal,'workbook','demo')
    contaminated.ingest('errors.csv',error_csv(),'orders','demo')
    seventy=contaminated.metrics('demo')
    assert seventy['sales']==70 and seventy['monthly']['2026-09']['contribution']==10
    again=contaminated.ingest('duplicate.xlsx',duplicate,'workbook','demo')
    assert contaminated.metrics('demo')==seventy
    contaminated_aggregates=independent_aggregates(contaminated.db)
    # Recreate Store, discarding all Python objects: persistence survives a new session.
    assert Store(store.root).metrics('demo')==before
    existing_aggregates=independent_aggregates(source_db) if existing_before else None
    if existing_before:
        with readonly(source_db) as con:
            archived_batches=[{'id':r['id'],'filename':r['filename'],'status':r['status'],'added_count':r['added_count'],
                              'created_at':r['created_at'],'sha256':r['sha256'],
                              'raw_hash_matches':hashlib.sha256((source_db.parent/r['raw_path']).read_bytes()).hexdigest()==r['sha256']}
                             for r in con.execute('SELECT * FROM batches ORDER BY created_at')]
        assert history_snapshot(source_db)==existing_before
    else:
        archived_batches=[]
    result={'baseline_commit':BASELINE,'database_dir':str(parent),'fixture_sha256':hashlib.sha256(normal).hexdigest(),
            'fixtures_byte_identical':True,'first':first,'duplicates':repeated,'before':before,
            'after':store.metrics('demo'),'all_metrics_identical':True,'clean_independent_aggregates':clean_aggregates,
            'original_code_before':original_before,'original_code_after_duplicate':original_after,
            'original_code_with_errors':original_mixed,'original_code_duplicate_bug_reproduced':False,
            'regenerated':regenerated,'with_errors':seventy,'duplicate_after_errors':again,
            'contaminated_independent_aggregates':contaminated_aggregates,'existing_batches':archived_batches,
            'existing_independent_aggregates':existing_aggregates,'existing_database_untouched':True,
            'existing_history_sha256':hashlib.sha256(json.dumps(existing_before,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    (EVIDENCE/'investigation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=encode),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['database_dir','fixture_sha256','fixtures_byte_identical','all_metrics_identical','existing_database_untouched']},indent=2))


if __name__=='__main__':
    run()
