"""Small deterministic scenarios. Never reads or writes V1 business data."""
from io import BytesIO
from pathlib import Path
import pandas as pd
from v2.rules import SCHEMAS


def frames():
    values = {
        'orders': [
            ['DEMO001','2026-09-01','C001','SKU001','Amazon','US',2,20,5,3,'completed',2],
            ['DEMO002','2026-09-02','C001','SKU001','Amazon','US',1,20,0,2,'cancelled',1]],
        'products': [['SKU001','演示商品','演示品类',8,'S001','2026-01-01']],
        'customers': [['C001','US','2026-01-01','existing']],
        'inventory': [['2026-09-01','SKU001',10,0,2,8]],
        'refunds': [['R001','DEMO001','2026-10-01',5,'运输损坏','approved',0]],
        'ads': [['2026-09-01','Amazon','CAM001','SKU001',100,10,4,1,35]]}
    return {name: pd.DataFrame(values[name],columns=SCHEMAS[name]) for name in SCHEMAS}


def workbook():
    buf = BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        for name,frame in frames().items():
            frame.to_excel(writer,sheet_name=name,index=False)
    return buf.getvalue()


def error_csv():
    base = frames()['orders'].iloc[[0]].copy()
    records = []
    for key,field,value in [('BAD_PRICE','unit_price',-10),('HIGH_PRICE','unit_price',150),
                            ('UNKNOWN_SKU','sku','SKU999'),('BAD_DISCOUNT','discount',1000),
                            ('MISSING_FEE','shipping_fee',None)]:
        row = base.iloc[0].to_dict()
        row['order_id'] = key
        row[field] = value
        records.append(row)
    return pd.DataFrame(records,columns=SCHEMAS['orders']).to_csv(index=False).encode('utf-8-sig')


def generate(target):
    target = Path(target)
    target.mkdir(parents=True,exist_ok=True)
    normal = workbook()
    (target/'normal.xlsx').write_bytes(normal)
    (target/'duplicate.xlsx').write_bytes(normal)
    (target/'errors.csv').write_bytes(error_csv())
    for name,frame in frames().items():
        frame.to_csv(target/f'{name}.csv',index=False,encoding='utf-8-sig')


if __name__=='__main__':
    generate(Path(__file__).with_name('demo_data'))
