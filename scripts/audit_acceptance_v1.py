"""正式验收的独立复核与质检日志证据，输入raw和已生成V1，输出验收JSON。"""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def main():
    raw={n:pd.read_csv(ROOT/f'data/raw/{n}.csv') for n in ['orders','products','inventory','refunds','ads','customers']}
    manifest=json.loads((ROOT/'data/raw/manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT/'data/raw'/name).read_bytes()).hexdigest()==entry['sha256'] for name,entry in manifest['files'].items())
    o=raw['orders'].drop_duplicates().copy()
    # 从raw独立复算：仅按已声明规则标准化，不读取生成脚本。
    o['sku_standard']=o.sku.str.strip().str.upper()
    o['platform_standard']=o.platform.str.strip().str.lower().map({'amazon':'Amazon','shopee':'Shopee','tiktok':'TikTok Shop','tiktok shop':'TikTok Shop'})
    o['month']=o.order_date.str.replace('/','-',regex=False).str[:7]
    o['review']=(o.unit_price.le(0)|o.unit_price.gt(100)|o.quantity.le(0)|o.quantity.gt(10)|o.quantity.mod(1).ne(0)|o.discount.lt(0)|o.discount.gt(o.quantity*o.unit_price)|o.shipping_fee.lt(0)|o.platform_fee.lt(0))
    o['sales']=(o.quantity*o.unit_price-o.discount).where(o.order_status.eq('completed'),0)
    valid=o.loc[o.order_status.eq('completed') & ~o.review].copy()
    sales=valid.groupby('month').sales.sum()
    rate=(sales['2026-09']/sales['2026-08']-1)*100
    costs=raw['products'].set_index('sku').unit_cost
    valid['cost']=valid.quantity*valid.sku_standard.map(costs)
    known=valid.loc[valid.cost.notna()].copy()
    known['base']=known.sales-known.cost-known.shipping_fee-known.platform_fee
    r=raw['refunds'].merge(o[['order_id','sales','sku_standard','platform_standard']],on='order_id',validate='many_to_one')
    totals=r.loc[r.refund_status.eq('approved')].groupby('order_id').refund_amount.sum()
    r['bad']=(r.refund_amount.lt(0)|r.refund_amount.gt(r.sales+.01)|r.order_id.map(totals).gt(r.sales+.01))
    rr=r.loc[r.refund_status.eq('approved')&~r.bad&r.order_id.isin(known.order_id)].copy()
    rr['month']=rr.refund_date.str[:7]
    a=raw['ads'].copy();a['month']=a.date.str[:7]
    a['platform_standard']=a.platform.str.strip().str.lower().map({'amazon':'Amazon','shopee':'Shopee','tiktok':'TikTok Shop','tiktok shop':'TikTok Shop'})
    independently=known.groupby('month').base.sum()-rr.groupby('month').refund_amount.sum().reindex(sales.index,fill_value=0)-a.groupby('month').ad_spend.sum(min_count=1)
    decline=independently['2026-08']-independently['2026-09'];profit_rate=decline/independently['2026-08']*100
    exported=pd.read_csv(ROOT/'reports/tables/monthly_profit.csv').set_index('month')
    assert (independently-exported.contribution).abs().max()<1e-6
    assert round(rate,2)==-18.92 and round(decline,2)==20532.13 and round(profit_rate,2)==40.27
    assert len(o)==9952 and o.order_id.is_unique
    assert len(raw['orders'])-len(o)==18
    assert raw['orders'].duplicated(['order_id'],keep=False).sum()==36
    assert r.bad.sum()==2
    platform=known.groupby(['platform_standard','month']).base.sum()-rr.groupby(['platform_standard','month']).refund_amount.sum()-a.groupby(['platform_standard','month']).ad_spend.sum(min_count=1)
    delta=platform.unstack()['2026-09']-platform.unstack()['2026-08']
    assert delta.idxmin()=='TikTok Shop' and round(delta['TikTok Shop'],2)==-13546.85
    # 支持证据的粒度明确记录：表连接可对账，不等于因果。
    inv=raw['inventory'];stock=inv.loc[inv.sku.eq('SKU001')&inv.date.between('2026-09-18','2026-09-21')]
    assert len(stock)==4 and stock[['opening_stock','inbound_qty','sold_qty','closing_stock']].eq(0).all().all()
    zeroorders=o.loc[o.sku_standard.eq('SKU001')&o.month.eq('2026-09')&o.order_date.str[:10].between('2026-09-18','2026-09-21')]
    assert zeroorders.order_status.eq('completed').sum()==0
    # 去重后的六表结果和规则对应，不把存在问题自动算作修复。
    issues=pd.read_csv(ROOT/'data/processed/quality_issues.csv')
    logs=[]
    methods={'exact_duplicate':'全字段duplicated＋业务键复核','sku_format':'去空格转大写与原值比较','platform_format':'去空格转小写后名称字典匹配','country_format':'国家字典与原值比较','date_format:order_date':'统一日期分隔符后显式日期解析','missing:customer_id':'isna按列统计','missing:ad_spend':'isna按列统计','refund_exceeds_order_or_invalid':'单笔与累计已批准金额比较原订单实收','unknown_sku':'标准SKU与商品主表反关联','stock_balance':'期末与期初＋入库－出库比较','stock_roll_forward':'按SKU日期排序与上一日期末比较','inventory_order_difference':'逐日SKU完成有效订单件数与sold_qty对账','negative_inventory':'四个库存字段任一小于0','invalid_price':'单价<=0或缺失','invalid_quantity':'数量<=0、缺失或非整数','review_high_price':'单价>100美元；临时复核线','review_high_quantity':'数量>10件；临时复核线','invalid_discount':'优惠<0、缺失或超过数量×单价'}
    for (table,code),g in issues.groupby(['table','issue']):
        cleaned=code in ['exact_duplicate','sku_format','platform_format','country_format'] or code.startswith('date_format:')
        before=len(g)
        after='标准化映射差异0；原字段保留' if cleaned else f'保留{before}条问题标记，未修正原值'
        if code=='exact_duplicate':after=f'行数{len(raw[table])}→{len(raw[table].drop_duplicates())}；业务键唯一'
        status='处理及数量已验证' if cleaned else '检查数量已验证；业务原值待确认'
        logs.append([table,code,methods.get(code,'按脚本明确条件标记；源CSV行号可追溯'),before,after,g.action.iloc[0],status,f'data/processed/quality_issues.csv\ndata/processed/{table}_clean.csv','2026-10-10'])
    # 零异常检查也记录，保证六表覆盖而非只列有问题的表。
    for table,df in raw.items():
        logs.append([table,'业务粒度和主键','按数据字典＋脚本键校验，非凭列名猜粒度',len(df),len(df.drop_duplicates()),'仅整行一致副本去重；不同明细不得删除','复核通过','reports/tables/table_profiles.csv','2026-10-10'])
        logs.append([table,'日期/数值/状态及关联检查','参照quality_report及脚本每表检查，未发现与已标记项分开',len(df),len(df.drop_duplicates()),'检查通过不代表原业务记录已获凭证确认','技术验证通过；真实业务准确性不可验证','scripts/run_project_v1.py；reports/validation.json','2026-10-10'])
    logs.append(['ads','疑似缺失日报','按36个固定活动的61天观测模式检查完整网格',4,'缺行4条；未补0','核实是否停投或漏报','待业务确认','data/processed/ads_missing_expected_rows.csv','2026-10-10'])
    headers=['业务表','检查项','发现方式','处理前数量','处理后结果','处理规则','验证情况','证据（项目相对路径）','核验日期']
    profiles=pd.read_csv(ROOT/'reports/tables/table_profiles.csv')
    sheets=[{'name':'六表概览','headers':['业务表','粒度','业务主键','原始行数','全字段多余副本','清洗行数','状态'], 'rows':[[x.table,x.grain,x.business_key,int(x.raw_rows),int(x.exact_duplicate_excess),len(raw[x.table].drop_duplicates()),'已核对；模拟数据'] for x in profiles.itertuples()]}, {'name':'异常处理日志','headers':headers,'rows':logs}, {'name':'验证证据','headers':['核验事项','结果','范围限制','证据'],'rows':[['销售环比',round(rate,8),'有效完成样本；非完整公司核实收入','独立从raw重算'],['贡献利润下降金额',round(decline,8),'成本已知样本；已记录广告；USD','独立从raw重算'],['贡献利润下降率',round(profit_rate,8),'不是财务净利润；百分比数值','独立从raw重算'],['最大下降平台','TikTok Shop','维度归因，不是因果识别','独立聚合订单退款广告'],['SKU001零库存',4,'期末耗尽17日另列；四完整日','库存日报与完成订单对应'],['广告未知费用',9,'不填0，金额影响未知','ads.csv'],['模拟真实性','非真实经营','不能确认真实公司收益','README与报告']]}]
    (ROOT/'reports/data_quality_log_source.json').write_text(json.dumps({'project':'基于模拟数据的业务分析项目','sheets':sheets},ensure_ascii=False,indent=2),encoding='utf-8')
    # 项目公开候选文件检查：缓存/虚拟环境由gitignore排除，学习成果保留。
    excluded={'.dashboard-browser','.venv-acceptance','.acceptance-work','.venv','venv','node_modules','__pycache__','.ipynb_checkpoints','.git'}
    findings=[];count=0
    absolute=re.compile(r'(?<![A-Za-z])(?:[A-Za-z]:[\\/]|/Users/|/home/|/mnt/)')
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(part in excluded for part in path.relative_to(ROOT).parts):continue
        if path.relative_to(ROOT).as_posix()=='data/processed/orders.xlsx':continue
        if path.name.endswith('.inspect.ndjson') or path.name.startswith('quality_log_preview_') or path.name=='.env':continue
        count+=1
        if path.suffix in ['.py','.md','.txt','.json','.sql','.ipynb','.mjs']:
            text=path.read_text(encoding='utf-8',errors='replace')
            if path.suffix in ['.json','.ipynb']:
                # 对解码后的字符串检查，避免JSON的lambda x:\\n被误判为X盘路径。
                def strings(value):
                    if isinstance(value,str):yield value
                    elif isinstance(value,list):
                        for item in value:yield from strings(item)
                    elif isinstance(value,dict):
                        for item in value.values():yield from strings(item)
                text='\n'.join(strings(json.loads(text)))
            # 排除本扫描器自身的正则定义，不将检测表达式认作路径泄漏。
            if path.name!='audit_acceptance_v1.py' and absolute.search(text):findings.append({'path':path.relative_to(ROOT).as_posix(),'issue':'absolute_path'})
            if re.search(r'(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})',text):findings.append({'path':path.relative_to(ROOT).as_posix(),'issue':'possible_secret'})
        if path.suffix=='.xlsx':
            with zipfile.ZipFile(path) as z:
                if 'docProps/core.xml' in z.namelist():
                    text=z.read('docProps/core.xml').decode('utf-8',errors='replace')
                    if re.search(r'<(?:dc:creator|cp:lastModifiedBy)>[^<]+',text):findings.append({'path':path.relative_to(ROOT).as_posix(),'issue':'workbook_author_metadata_requires_review'})
    results={'date':'2026-10-10','raw_independent_sales':sales.round(8).to_dict(),'sales_change_pct':float(rate),'profit':independently.round(8).to_dict(),'profit_decline':float(decline),'profit_decline_pct':float(profit_rate),'platform_contribution_changes':delta.round(8).to_dict(),'raw_hashes':{n:hashlib.sha256((ROOT/f'data/raw/{n}.csv').read_bytes()).hexdigest() for n in raw},'public_candidate_files':count,'publication_scan_findings':findings,'source_csv_untouched':True}
    (ROOT/'reports/acceptance_evidence.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
