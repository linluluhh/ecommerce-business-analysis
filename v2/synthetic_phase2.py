"""Synthetic / 模拟数据: fourteen consecutive days, two comparable 7-day windows."""
from io import BytesIO
from pathlib import Path
import pandas as pd
from v2.rules import SCHEMAS


def frames():
    data={name:[] for name in SCHEMAS}
    data['products']=[['SKU001','模拟商品一','模拟类目',8,'SYNTH','2026-01-01'],
                      ['SKU002','模拟商品二','模拟类目',14,'SYNTH','2026-01-01']]
    data['customers']=[['C_SYNTH','US','2026-01-01','existing']]
    stock={'SKU001':70,'SKU002':35}
    refund_targets=[]
    for number,day in enumerate(pd.date_range('2026-09-01','2026-09-14'),start=1):
        date=str(day.date());counts={'SKU001':5 if number<=7 else 2,'SKU002':1 if number<=7 else 2}
        for sku,count in counts.items():
            price=16 if number>7 and sku=='SKU001' else 20
            for j in range(count):
                oid=f'SYNTH-{number:02}-{sku}-{j}'
                data['orders'].append([oid,date,'C_SYNTH',sku,'Amazon','US',1,price,0,1,'completed',1])
                if sku=='SKU001' and j==0 and number in (2,8,9,10,11,12):refund_targets.append((oid,day))
            data['inventory'].append([date,sku,stock[sku],0,count,stock[sku]-count]);stock[sku]-=count
        data['ads'].append([date,'Amazon','SYNTH-CAM','SKU001',100,10,10 if number<=7 else 18,1,90 if number<=7 else 10])
    for n,(oid,day) in enumerate(refund_targets):
        data['refunds'].append([f'SYNTH-R{n}',oid,str((day+pd.Timedelta(days=2)).date()),10,'模拟运输损坏','approved',0])
    data['orders'] += [
        ['SYNTH-UNKNOWN','2026-09-14','C_SYNTH','SKU999','Amazon','US',1,20,0,1,'completed',1],
        ['SYNTH-BAD','2026-09-14','C_SYNTH','SKU001','Amazon','US',1,-10,0,1,'completed',1]]
    return {name:pd.DataFrame(data[name],columns=SCHEMAS[name]) for name in SCHEMAS}


def workbook():
    buf=BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        for name,frame in frames().items():frame.to_excel(writer,sheet_name=name,index=False)
    return buf.getvalue()


if __name__=='__main__':
    target=Path(__file__).with_name('demo_data')/'phase2_synthetic.xlsx'
    target.write_bytes(workbook())
    print('Synthetic / 模拟数据:',target)
