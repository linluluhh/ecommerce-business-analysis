"""Isolated Synthetic daily ingestion, idempotency and rule monitoring evidence."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
import pandas as pd
from v2.synthetic_phase2 import frames
from v2.service import Store
from v2.metrics import MetricCenter
from v2.alerts import AlertEngine,safe_json
from v2.revisions import Revisions


def run():
    root=Path(__file__).resolve().parent
    runtime=root/'runtime';runtime.mkdir(exist_ok=True)
    store=Store(tempfile.mkdtemp(prefix='phase2-14day-',dir=runtime))
    data=frames();daily=[]
    for day in pd.date_range('2026-09-01','2026-09-14'):
        parts={}
        for name,frame in data.items():
            col={'orders':'order_date','inventory':'date','ads':'date','refunds':'refund_date'}.get(name)
            parts[name]=frame[frame[col].eq(str(day.date()))] if col else frame
        buf=BytesIO()
        with pd.ExcelWriter(buf,engine='openpyxl') as writer:
            for name,frame in parts.items():frame.to_excel(writer,sheet_name=name,index=False)
        first=store.ingest('Synthetic-'+str(day.date())+'.xlsx',buf.getvalue(),'workbook','demo')
        assert first['status']=='imported',first
        before=MetricCenter(store).calculate('demo',as_of='2026-10-10')
        duplicate=store.ingest('重复-'+str(day.date())+'.xlsx',buf.getvalue(),'workbook','demo')
        assert duplicate['status']=='duplicate'
        assert MetricCenter(Store(store.root)).calculate('demo',as_of='2026-10-10')==before
        detection=AlertEngine(store).run('demo','2026-10-10')
        assert AlertEngine(store).run('demo','2026-10-10')['new']==0
        daily.append({'date':str(day.date()),'added':first['added'],'sales':before['sales'],
                      'known_cost_sales':before['known_cost_sales'],'orders':before['orders'],
                      'alerts_new':detection['new'],'alerts_triggered':detection['triggered'],
                      'unknown_orders':before['unknown_orders'],'same_file_idempotent':True,'reopen_idempotent':True})
    # Refunds after the last order day are separate confirmation-ledger deliveries.
    late=data['refunds'][data['refunds'].refund_date.gt('2026-09-14')]
    if not late.empty:assert store.ingest('Synthetic-late-refunds.csv',late.to_csv(index=False).encode('utf-8-sig'),'refunds','demo')['status']=='imported'
    current=MetricCenter(store).calculate('demo','2026-09-08','2026-09-14',as_of='2026-10-10')
    assert current['sales']==524 and current['gross_profit']==196 and current['refund_cost']==50 and current['contribution']==-36
    record=store.query("SELECT id FROM records WHERE raw_json LIKE '%SYNTH-BAD%'").iloc[0].id
    workflow=Revisions(store)
    original=MetricCenter(store).calculate('demo',as_of='2026-10-10')
    revision=workflow.request('demo',int(record),{'unit_price':20},'模拟录入修正','Synthetic凭证-001','模拟申请人')
    assert MetricCenter(store).calculate('demo',as_of='2026-10-10')==original
    workflow.decide('demo',revision,'已批准','模拟审核员','已核对模拟凭证')
    updated=MetricCenter(Store(store.root)).calculate('demo',as_of='2026-10-10')
    assert updated['sales']==original['sales']+20
    detection=AlertEngine(store).run('demo','2026-10-10')
    with store.connect() as con:
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        assert integrity=='ok' and not con.execute('PRAGMA foreign_key_check').fetchall()
    evidence=root/'evidence/phase2';evidence.mkdir(parents=True,exist_ok=True)
    summary={'data_label':'Synthetic / 模拟数据，非真实企业','database_dir':str(store.root),
             'days':daily,'days_count':len(daily),'current_before_revision':current,
             'approved_revision_id':revision,'sales_before_revision':original['sales'],
             'sales_after_revision':updated['sales'],'unapproved_revision_unchanged':True,
             'detection_after_revision':detection,'database_integrity':integrity,
             'all_duplicate_imports_unchanged':True}
    (evidence/'synthetic-14day-results.json').write_text(safe_json(summary),encoding='utf-8')
    print(safe_json({k:v for k,v in summary.items() if k not in ('days','current_before_revision','detection_after_revision')}))


if __name__=='__main__':run()
