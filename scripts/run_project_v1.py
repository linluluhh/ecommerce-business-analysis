"""模拟业务项目V1：raw只读，清洗、质检、SQL、分析与交付一键复现。

运行：python scripts/run_project_v1.py
输入六表，输出processed、报告数据、SQLite与Dashboard。
未知值保留，异常隔离而非猜测修正。所有关键计算均采用相同期间与样本。
"""
from pathlib import Path
import hashlib
import json
import sqlite3
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
OUT = ROOT / 'data/processed'
RESULT = ROOT / 'reports/tables'
PLATFORMS = {'tiktok': 'TikTok Shop', 'tiktok shop': 'TikTok Shop', 'amazon': 'Amazon', 'shopee': 'Shopee'}
COUNTRIES = {'us': 'US', 'usa': 'US', 'gb': 'GB', 'united kingdom': 'GB', 'de': 'DE', 'germany': 'DE', 'sg': 'SG', 'singapore': 'SG', 'my': 'MY', 'malaysia': 'MY', 'ph': 'PH', 'philippines': 'PH'}
GRAINS = {
    'orders': (['order_id'], '一笔单SKU订单；根据数据字典及重复行全字段复核，非多商品订单明细'),
    'products': (['sku'], '一行一个商品SKU，成本两个月固定'),
    'inventory': (['date', 'sku'], '日期×SKU，共享库存日报'),
    'refunds': (['refund_id'], '一笔售后申请；order_id非主键，可有多笔退款'),
    'ads': (['date', 'platform', 'campaign_id', 'sku'], '日期×平台×活动×SKU广告日报；conversions是订单数'),
    'customers': (['customer_id'], '一个注册客户；新老客标签相对8月1日固定')}


def save(df, path):
    """输入数据表；以UTF-8 BOM输出CSV，编号保持文本。"""
    df.to_csv(path, index=False, encoding='utf-8-sig', float_format='%.8f')


def markdown(df):
    """生成不依赖tabulate的Markdown表。"""
    df = df.copy().fillna('未知')
    return '| ' + ' | '.join(map(str, df.columns)) + ' |\n|' + '|'.join(['---'] * len(df.columns)) + '|\n' + '\n'.join('| ' + ' | '.join(f'{v:,.2f}' if isinstance(v, (float, np.floating)) else str(v) for v in row) + ' |' for row in df.itertuples(index=False, name=None))


def run():
    for d in [OUT, RESULT, ROOT/'dashboard', ROOT/'sql', ROOT/'docs']:
        d.mkdir(parents=True, exist_ok=True)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW.glob('*.csv')}
    manifest = json.loads((RAW/'manifest.json').read_text(encoding='utf-8'))
    assert all(hashes[n] == v['sha256'] for n, v in manifest['files'].items()), 'raw与最初清单不一致，停止'
    tables = {n: pd.read_csv(RAW/f'{n}.csv', dtype={k: 'string' for k in ['order_id', 'customer_id', 'sku', 'refund_id', 'campaign_id']}, encoding='utf-8-sig') for n in GRAINS}
    original = {n: t.copy() for n,t in tables.items()}
    issues, profiles = [], []

    def flag(name, mask, code, action, severity='review'):
        frame = tables[name]
        for idx in frame.index[mask.fillna(False)]:
            issues.append({'table': name, 'source_csv_row': int(idx)+2, 'key': '|'.join(str(frame.loc[idx,k]) for k in GRAINS[name][0]), 'issue': code, 'action': action, 'severity': severity})

    for name, frame in tables.items():
        keys, grain = GRAINS[name]
        profiles.append({'table': name, 'grain': grain, 'business_key': '+'.join(keys), 'raw_rows': len(frame), 'columns': len(frame.columns), 'exact_duplicate_excess': int(frame.duplicated().sum()), 'duplicate_key_rows': int(frame.duplicated(keys, keep=False).sum()), 'missing_cells': int(frame.isna().sum().sum())})
        for col in frame:
            flag(name, frame[col].isna(), f'missing:{col}', '保留未知，按字段用途处理')
        flag(name, frame.duplicated(keep='first'), 'exact_duplicate', '仅移除全字段一致的多余副本', 'cleaned')
        tables[name] = frame.drop_duplicates().copy()
        frame = tables[name]
        if 'sku' in frame:
            std = frame['sku'].str.strip().str.upper()
            flag(name, frame['sku'].ne(std), 'sku_format', '保留原字段并新增sku_standard', 'cleaned')
            frame['sku_standard'] = std
        for col, mapping in [('platform', PLATFORMS), ('country', COUNTRIES)]:
            if col in frame:
                std = frame[col].astype('string').str.strip().str.lower().map(mapping)
                flag(name, frame[col].ne(std), f'{col}_format', '新增标准列，保留原字段', 'cleaned')
                flag(name, std.isna(), f'{col}_unmapped', '未知类别需核实')
                frame[col+'_standard'] = std
        dates = [c for c in ['order_date', 'date', 'refund_date', 'register_date', 'launch_date'] if c in frame]
        for col in dates:
            normalized = frame[col].astype('string').str.strip().str.replace('/', '-', regex=False)
            parsed = pd.to_datetime(normalized, format='%Y-%m-%d', errors='coerce')
            flag(name, frame[col].astype('string').ne(normalized), f'date_format:{col}', '统一分隔符，保留原值', 'cleaned')
            flag(name, parsed.isna(), f'date_invalid:{col}', '无法定位期间，待核实')
            frame[col+'_standard'] = parsed
        non_numeric = set(keys + dates + ['order_id','customer_id','sku','refund_id','campaign_id','product_name','category','supplier','platform','country','order_status','refund_reason','refund_status','customer_type'])
        for col in original[name].columns:
            if col in non_numeric: continue
            numeric = pd.to_numeric(frame[col], errors='coerce')
            flag(name, frame[col].notna() & numeric.isna(), f'type_invalid:{col}', '数值解析失败，不猜测填补')
            frame[col] = numeric
        stdkeys = [k+'_standard' if k in ['sku','platform','date'] else k for k in keys]
        assert not frame.duplicated(stdkeys).any(), f'{name}仍有冲突主键，需人工处理'

    o,p,i,r,a,c = [tables[n] for n in GRAINS]
    assert original['orders'].duplicated().sum() == 18
    assert original['orders'].duplicated(['order_id'],keep=False).sum() == 36
    assert o['order_id'].is_unique and len(o)==9952
    for name in ['orders','inventory','ads']:
        flag(name, ~tables[name]['sku_standard'].isin(p['sku_standard']), 'unknown_sku', '订单保留收入、成本未知；不能将成本填0')
    flag('orders', o['customer_id'].notna() & ~o['customer_id'].isin(c['customer_id']), 'unknown_customer', '保留订单，客户身份待核实')
    flag('orders', ~o['order_status'].isin(['completed','cancelled']), 'unknown_status', '不确认收入，待核实')
    o['invalid_price'] = o['unit_price'].le(0) | o['unit_price'].isna()
    o['invalid_quantity'] = o['quantity'].le(0) | o['quantity'].isna() | o['quantity'].mod(1).ne(0)
    o['review_high_price'] = o['unit_price'].gt(100)
    o['review_high_quantity'] = o['quantity'].gt(10)
    o['invalid_discount'] = o['discount'].lt(0) | o['discount'].gt(o['quantity']*o['unit_price']) | o['discount'].isna()
    o['invalid_fee'] = o[['shipping_fee','platform_fee']].lt(0).any(axis=1) | o[['shipping_fee','platform_fee']].isna().any(axis=1)
    reviewcols=['invalid_price','invalid_quantity','review_high_price','review_high_quantity','invalid_discount','invalid_fee']
    for col in reviewcols: flag('orders',o[col],col,'不改原值，保留并隔离；100美元、10件仅临时复核线')
    o['needs_review']=o[reviewcols].any(axis=1)
    o['order_sales']=(o['quantity']*o['unit_price']-o['discount']).where(o['order_status'].eq('completed'),0)
    o['month']=o['order_date_standard'].dt.strftime('%Y-%m')
    customer_dates=c.set_index('customer_id')['register_date_standard']
    flag('orders', o['order_date_standard'].lt(o['customer_id'].map(customer_dates)), 'order_before_registration','核实日期或客户关联')
    flag('products',p['unit_cost'].le(0)|p['unit_cost'].isna(),'invalid_unit_cost','成本不可靠，不能用于利润')
    launch_dates=p.set_index('sku_standard')['launch_date_standard']
    flag('orders',o['order_date_standard'].lt(o['sku_standard'].map(launch_dates)),'order_before_launch','上架日期或商品关联矛盾待核实')
    expected_type=np.where(c['register_date_standard'].ge(pd.Timestamp('2026-08-01')),'new','existing')
    flag('customers',c['customer_type'].ne(expected_type),'customer_type_conflict','固定注册标签核查')

    # 库存会计平衡、跨日承接、与有效订单逐日对账；只标记，不用推导值覆盖原值。
    i.sort_values(['sku_standard','date_standard'],inplace=True)
    flag('inventory',i[['opening_stock','inbound_qty','sold_qty','closing_stock']].lt(0).any(axis=1),'negative_inventory','该日库存待核实')
    flag('inventory',i['closing_stock'].ne(i['opening_stock']+i['inbound_qty']-i['sold_qty']),'stock_balance','保留原值，不能自动改成推导值')
    prev=i.groupby('sku_standard')['closing_stock'].shift()
    flag('inventory',prev.notna() & i['opening_stock'].ne(prev),'stock_roll_forward','跨日承接差异待核实')
    sales_sample=o.loc[o['order_status'].eq('completed') & ~o['needs_review']].copy()
    sold=sales_sample.groupby(['sku_standard','order_date_standard'])['quantity'].sum()
    i['valid_order_units']=[sold.get((row.sku_standard,row.date_standard),0) for row in i.itertuples()]
    flag('inventory',i['sold_qty'].ne(i['valid_order_units']),'inventory_order_difference','有效订单样本排除了异常及未知SKU；差异不必然是库存错误')
    flag('inventory',i[['opening_stock','inbound_qty','sold_qty','closing_stock']].mod(1).ne(0).any(axis=1),'fractional_units','库存件数应为整数')

    # 退款累计核验与时间/状态关系。
    joined=r.merge(o[['order_id','order_sales','order_status','order_date_standard','sku_standard','platform_standard','needs_review']],on='order_id',how='left',validate='many_to_one')
    for col in joined.columns:
        if col not in r: r[col]=joined.set_index('refund_id')[col].reindex(r['refund_id']).values
    flag('refunds',r['order_sales'].isna(),'refund_orphan','不能关联原订单')
    assert r['order_sales'].notna().all(), '退款关联失败，不能继续利润汇总'
    flag('refunds',~r['refund_status'].isin(['approved','pending','rejected']),'refund_status_invalid','状态待核实')
    flag('refunds',r['order_status'].ne('completed'),'refund_cancelled_order','取消订单退款关系待核实')
    flag('refunds',r['refund_date_standard'].lt(r['order_date_standard']),'refund_before_order','日期矛盾待核实')
    totals=r.loc[r['refund_status'].eq('approved')].groupby('order_id')['refund_amount'].sum()
    r['approved_refund_total']=r['order_id'].map(totals)
    r['amount_needs_review']=r['refund_amount'].lt(0)|r['refund_amount'].isna()|r['refund_amount'].gt(r['order_sales']+.01)|r['approved_refund_total'].gt(r['order_sales']+.01)
    flag('refunds',r['amount_needs_review'],'refund_exceeds_order_or_invalid','退款只退商品实收；隔离金额异常，不擅自封顶')
    flag('refunds',r['restocked_qty'].ne(0),'unexpected_restock','本项目不恢复可售库存')
    r['refund_month']=r['refund_date_standard'].dt.strftime('%Y-%m')
    r['days_to_refund']=(r['refund_date_standard']-r['order_date_standard']).dt.days

    a['month']=a['date_standard'].dt.strftime('%Y-%m')
    flag('ads',a[['impressions','clicks','ad_spend','conversions','attributed_revenue']].lt(0).any(axis=1),'negative_ad_metric','不用于效率汇总，待核实')
    flag('ads',a['clicks'].gt(a['impressions'])|a['conversions'].gt(a['clicks']),'ad_funnel_invalid','漏斗计数关系不合理')
    flag('ads',a[['impressions','clicks','conversions']].mod(1).ne(0).any(axis=1),'fractional_ad_count','计数应为整数')
    daily=sales_sample.groupby(['order_date_standard','platform_standard','sku_standard']).agg(orders=('order_id','nunique'),sales=('order_sales','sum'))
    a['valid_completed_orders']=[daily['orders'].get((x.date_standard,x.platform_standard,x.sku_standard),0) for x in a.itertuples()]
    a['valid_order_sales']=[daily['sales'].get((x.date_standard,x.platform_standard,x.sku_standard),0) for x in a.itertuples()]
    flag('ads',a['conversions'].gt(a['valid_completed_orders']),'ad_conversion_order_difference','样本隔离可能导致差异；同日归因需核实')
    flag('ads',a['attributed_revenue'].gt(a['valid_order_sales']+.01),'ad_revenue_order_difference','广告归因收入不得额外加到订单收入；核实样本差异')
    # 依现有固定活动观测到的每日模式检查缺行，不将缺行补成0。
    missing_ad=[]
    for (platform,campaign,sku),grp in a.groupby(['platform_standard','campaign_id','sku_standard']):
        for day in pd.date_range('2026-08-01','2026-09-30').difference(grp['date_standard']):
            missing_ad.append({'date':str(day.date()),'platform':platform,'campaign_id':campaign,'sku':sku,'basis':'观测固定活动每日模式；需确认是否停投或漏报'})
    missing_ads=pd.DataFrame(missing_ad)
    save(missing_ads,OUT/'ads_missing_expected_rows.csv')
    issue_frame=pd.DataFrame(issues)
    save(issue_frame,OUT/'quality_issues.csv')
    save(pd.DataFrame(profiles),RESULT/'table_profiles.csv')
    save(o.loc[o['needs_review']],OUT/'orders_quarantine.csv')
    save(r.loc[r['amount_needs_review']],OUT/'refunds_quarantine.csv')
    for name,frame in tables.items(): save(frame,OUT/f'{name}_clean.csv')

    # 利润：成本已知、有效完成订单 + 相同订单范围当月确认有效退款 - 全部已记录广告费。
    fact=sales_sample.merge(p[['sku_standard','unit_cost','category','product_name']],on='sku_standard',how='left',validate='many_to_one')
    fact['goods_cost']=fact['quantity']*fact['unit_cost']
    fact['gross_sales']=fact['quantity']*fact['unit_price']
    fact['gross_profit']=fact['order_sales']-fact['goods_cost']
    fact['before_refunds_ads']=fact['gross_profit']-fact['shipping_fee']-fact['platform_fee']
    known=fact.loc[fact['unit_cost'].gt(0)].copy()
    validr=r.loc[r['refund_status'].eq('approved') & ~r['amount_needs_review'] & r['order_id'].isin(known['order_id'])].copy()
    save(fact,OUT/'order_facts.csv')
    save(known,OUT/'profit_orders.csv')
    save(validr,OUT/'profit_refunds.csv')

    def grouped(keys):
        m=known.groupby(keys).agg(sales=('order_sales','sum'),goods_cost=('goods_cost','sum'),gross_profit=('gross_profit','sum'),shipping_cost=('shipping_fee','sum'),platform_cost=('platform_fee','sum'),before_refunds_ads=('before_refunds_ads','sum'),units=('quantity','sum'),completed_orders=('order_id','nunique'))
        rkeys=[('refund_month' if k=='month' else k) for k in keys]
        rm=validr.groupby(rkeys)['refund_amount'].sum()
        rm.index.names=m.index.names
        am=a.groupby(keys)['ad_spend'].sum(min_count=1)
        m['refund_cost']=rm.reindex(m.index,fill_value=0)
        m['recorded_ad_cost']=am.reindex(m.index)
        m['contribution']=m['before_refunds_ads']-m['refund_cost']-m['recorded_ad_cost']
        m['gross_margin_pct']=m['gross_profit']/m['sales']*100
        return m
    monthly=grouped(['month'])
    platform=grouped(['platform_standard','month'])
    sku=grouped(['sku_standard','month'])
    # SKU成本样本无法覆盖未知SKU，但所有已记录广告必须保留到公司总额。
    unknown_ads=a.loc[~a['sku_standard'].isin(known['sku_standard'])].groupby('month')['ad_spend'].sum()
    assert unknown_ads.sum()==0, '需要新增未知SKU广告残差组'
    for frame,name in [(monthly,'monthly_profit'),(platform,'platform_profit'),(sku,'sku_profit')]:save(frame.reset_index(),RESULT/f'{name}.csv')
    sales_month=sales_sample.groupby('month').agg(sales=('order_sales','sum'),units=('quantity','sum'),orders=('order_id','nunique'))
    sales_month['revenue_per_unit']=sales_month['sales']/sales_month['units']
    sales_month['calendar_days']=[31,30]
    sales_month['sales_per_day']=sales_month['sales']/sales_month['calendar_days']
    sales_month['units_per_day']=sales_month['units']/sales_month['calendar_days']
    save(sales_month.reset_index(),RESULT/'monthly_sales.csv')
    country=known.groupby(['country_standard','month']).agg(sales=('order_sales','sum'),gross_profit=('gross_profit','sum'),units=('quantity','sum'))
    save(country.reset_index(),RESULT/'country_performance.csv')
    mix=known.groupby(['category','month']).agg(sales=('order_sales','sum'),units=('quantity','sum'),gross_profit=('gross_profit','sum'))
    mix['sales_share_pct']=mix['sales']/mix.index.get_level_values('month').map(known.groupby('month')['order_sales'].sum())*100
    save(mix.reset_index(),RESULT/'category_mix.csv')
    adknown=a.loc[a['ad_spend'].notna()]
    admetrics=adknown.groupby(['platform_standard','month']).agg(spend=('ad_spend','sum'),clicks=('clicks','sum'),revenue=('attributed_revenue','sum'),conversions=('conversions','sum'))
    admetrics['cpc']=admetrics['spend']/admetrics['clicks'].replace(0,np.nan)
    admetrics['roas']=admetrics['revenue']/admetrics['spend'].replace(0,np.nan)
    save(admetrics.reset_index(),RESULT/'advertising_efficiency.csv')
    dd=sales_sample.assign(gross_sales=sales_sample['quantity']*sales_sample['unit_price']).groupby(['platform_standard','month']).agg(gross_sales=('gross_sales','sum'),discounts=('discount','sum'))
    dd['discount_rate_pct']=dd['discounts']/dd['gross_sales']*100
    save(dd.reset_index(),RESULT/'platform_discounts.csv')
    refundids=validr.loc[validr['days_to_refund'].between(0,12),'order_id'].unique()
    cohort=known.assign(refunded=known['order_id'].isin(refundids)).groupby(['sku_standard','month']).agg(orders=('order_id','nunique'),refunded_orders=('refunded','sum'))
    cohort['refund_rate_pct']=cohort['refunded_orders']/cohort['orders']*100
    save(cohort.reset_index(),RESULT/'refund_cohorts_12d.csv')
    reason=validr.loc[validr['days_to_refund'].between(0,12)].assign(order_month=lambda x:x['order_date_standard'].dt.strftime('%Y-%m')).groupby(['sku_standard','order_month','refund_reason']).agg(orders=('order_id','nunique'),amount=('refund_amount','sum'))
    save(reason.reset_index(),RESULT/'refund_reasons.csv')

    aug,sep=monthly.loc['2026-08'],monthly.loc['2026-09']
    bridge=pd.Series({'销售额减少':aug.sales-sep.sales,'商品成本变化':sep.goods_cost-aug.goods_cost,'物流费变化':sep.shipping_cost-aug.shipping_cost,'平台佣金变化':sep.platform_cost-aug.platform_cost,'退款增加':sep.refund_cost-aug.refund_cost,'已记录广告费增加':sep.recorded_ad_cost-aug.recorded_ad_cost})
    decline=aug.contribution-sep.contribution
    assert abs(bridge.sum()-decline)<1e-7
    save(bridge.rename('profit_decline_impact').rename_axis('factor').reset_index(),RESULT/'profit_bridge.csv')
    for dim,frame,name in [('platform_standard',platform,'platform_changes'),('sku_standard',sku,'sku_changes'),('country_standard',country,'country_changes')]:
        w=frame.unstack('month');changes=pd.DataFrame(index=w.index)
        for metric in ['sales','gross_profit','contribution']:
            if metric in frame:changes[metric+'_change']=w[(metric,'2026-09')]-w[(metric,'2026-08')]
        if 'contribution_change' in changes:assert abs(changes['contribution_change'].sum()+decline)<1e-7
        save(changes.sort_values('sales_change').reset_index(),RESULT/f'{name}.csv')

    # 商品毛利精确分解：先数量/结构、后售价、后优惠；顺序固定，不当作因果识别。
    unit=known.groupby(['sku_standard','month']).agg(q=('quantity','sum'),list_sales=('gross_sales','sum'),discount=('discount','sum'),cost=('goods_cost','sum'))
    unit['price']=unit['list_sales']/unit['q'];unit['cost_per_unit']=unit['cost']/unit['q']
    u8=unit.xs('2026-08',level='month');u9=unit.xs('2026-09',level='month')
    assert u8.index.equals(u9.index)
    total8,total9=u8.q.sum(),u9.q.sum();s8=u8.q/total8;s9=u9.q/total9
    gross_decomp=pd.Series({'总销量变化':((total9-total8)*s8*(u8.price-u8.cost_per_unit)).sum(),'SKU销量结构变化':(total9*(s9-s8)*(u8.price-u8.cost_per_unit)).sum(),'SKU内标价/国家渠道结构变化':(u9.q*(u9.price-u8.price)).sum(),'单位采购成本变化':(-u9.q*(u9.cost_per_unit-u8.cost_per_unit)).sum(),'优惠总额变化':-(u9.discount-u8.discount).sum()})
    assert abs(gross_decomp.sum()-(sep.gross_profit-aug.gross_profit))<1e-7
    save(gross_decomp.rename('gross_profit_change').rename_axis('factor').reset_index(),RESULT/'gross_profit_decomposition.csv')
    # 缺货估算与TK费用情景，不与桥梁相加。
    stock=i.loc[i['sku_standard'].eq('SKU001')]
    ref=stock.loc[stock['date'].between('2026-09-10','2026-09-16')|stock['date'].between('2026-09-23','2026-09-29')]
    reforders=known.loc[known['sku_standard'].eq('SKU001') & known['order_date_standard'].isin(ref['date_standard'])]
    assert ref.sold_qty.sum()==reforders.quantity.sum()==502
    zero=stock.loc[stock['date'].between('2026-09-18','2026-09-21')]
    assert len(zero)==4 and zero[['opening_stock','inbound_qty','closing_stock']].eq(0).all().all()
    stockunits=ref.sold_qty.mean()*4;stockeffect=stockunits*reforders.order_sales.sum()/reforders.quantity.sum()
    d8,d9=dd.loc[('TikTok Shop','2026-08')],dd.loc[('TikTok Shop','2026-09')]
    discount_effect=d9.discounts-d9.gross_sales*d8.discounts/d8.gross_sales
    ad8,ad9=admetrics.loc[('TikTok Shop','2026-08')],admetrics.loc[('TikTok Shop','2026-09')]
    cpc_effect=ad9.spend-ad9.clicks*ad8.cpc
    save(pd.DataFrame([{'scenario':'SKU001四日零库存潜在销售额','amount':stockeffect,'assumption':'需求和平均实收与附近14个有货日相近；不含17日；非实际损失'},{'scenario':'TK优惠加深固定9月销售结构','amount':discount_effect,'assumption':'固定9月销量及标价，沿用8月优惠率；非可追回利润'},{'scenario':'TK点击变贵固定9月点击数','amount':cpc_effect,'assumption':'沿用8月平均CPC，包含广告组合变化；非可直接节省额'}]),RESULT/'scenarios.csv')
    sensitivity=pd.DataFrame({'month':sales_month.index,'raw_sales':[original['orders'].assign(s=(original['orders'].quantity*original['orders'].unit_price-original['orders'].discount).where(original['orders'].order_status.eq('completed'),0)).loc[original['orders'].order_date.str.replace('/','-',regex=False).str[:7].eq(m),'s'].sum() for m in sales_month.index],'deduplicated_with_flags':o.groupby('month').order_sales.sum().reindex(sales_month.index).values,'temporary_valid_sales':sales_month.sales.values,'known_cost_sales':monthly.sales.values})
    save(sensitivity,RESULT/'sales_sensitivity.csv')
    save(fact.loc[fact['unit_cost'].isna()].groupby('month').agg(orders=('order_id','nunique'),sales=('order_sales','sum')).reset_index(),RESULT/'unknown_cost_scope.csv')

    # SQLite保存业务表和利润事实；SQL独立计算并与Pandas逐项对账。
    db=OUT/'business_analysis.sqlite'
    with sqlite3.connect(db) as conn:
        for name,frame in tables.items():frame.to_sql(name,conn,if_exists='replace',index=False)
        known.to_sql('profit_orders',conn,if_exists='replace',index=False)
        validr.to_sql('profit_refunds',conn,if_exists='replace',index=False)
        for file in sorted((ROOT/'sql').glob('*.sql')):
            sql=file.read_text(encoding='utf-8')
            result=pd.read_sql_query(sql,conn)
            save(result,RESULT/(file.stem+'_sql.csv'))
            if file.stem=='01_monthly_profit':
                for row in result.itertuples():
                    for metric in ['sales','goods_cost','refund_cost','recorded_ad_cost','contribution']:
                        assert abs(getattr(row,metric)-monthly.loc[row.month,metric])<1e-6,f'SQL mismatch: {metric}'
    summary={'data_type':'基于模拟数据的业务分析项目','scope':'临时有效且成本已知订单；相同订单的有效批准退款按确认月；全部已记录广告','monthly':monthly.reset_index().round(8).to_dict('records'),'decline':round(decline,2),'decline_pct':round(decline/aug.contribution*100,2),'stockout_scenario':round(stockeffect,2),'extra_discount_scenario':round(discount_effect,2),'extra_cpc_scenario':round(cpc_effect,2),'raw_hashes':hashes,'quality_issue_count':len(issues),'missing_ad_spend':int(a.ad_spend.isna().sum()),'missing_expected_ad_rows':len(missing_ads)}
    (RESULT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    build_reports(summary,monthly,platform,sku,country,bridge,gross_decomp,cohort,issue_frame,profiles,missing_ads)
    build_dashboard(summary,platform,sku,bridge,admetrics,stock,cohort,country)
    assert all(hashlib.sha256((RAW/n).read_bytes()).hexdigest()==h for n,h in hashes.items()),'raw被意外改动'
    checks={'raw_unchanged':True,'duplicate_resolution':'18条全字段重复；去重后9952且订单键唯一','profit_bridge_reconciled':True,'platform_profit_reconciled':True,'sku_profit_reconciled':True,'gross_profit_decomposition_reconciled':True,'sql_pandas_reconciled':True,'stock_reference_orders_inventory_reconciled':True}
    (ROOT/'reports/validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))
    return summary


def build_reports(s,m,platform,sku,country,bridge,decomp,cohort,issues,profiles,missing_ads):
    quality='# 数据质量检查报告V1\n\n**基于模拟数据的业务分析项目。** raw六张CSV与初始SHA-256清单一致，未修改。\n\n## 粒度和主键\n'+markdown(pd.DataFrame(profiles))+'\n\n## 处理原则\n订单是单SKU业务订单，不把订单编号重复自动当成脏数据。复核18组编号重复涉及36行，所有多余副本全字段一致；按全字段去重删除18行，剩余9952行且order_id唯一。客户主表有7条全字段重复，去重后4800客户。退款编号唯一，订单编号允许重复；广告按日期×平台×活动×SKU核验，无需按日期×SKU粗暴去重。\n\n标准化新增列，原始字段保留。金额/数量异常保留在clean并另存quarantine；缺失客户不删除收入。SKU999未知成本不填0。超额退款不直接封顶。广告缺失不补0。库存平衡异常不自动反推修正。未知状态不确认收入。临时复核线：单价>100美元、数量>10件，并非行业通用规则。\n\n## 问题汇总\n'+markdown(issues.groupby(['table','issue']).size().rename('flagged_rows').reset_index())+f'\n\n广告缺失花费{s["missing_ad_spend"]}条；按现有固定活动每日模式发现{len(missing_ads)}条疑似漏报，需确认是否停投，不将推断当事实。详细证据见data/processed/quality_issues.csv和ads_missing_expected_rows.csv。库存与有效订单差异可能来自隔离异常及未知SKU，不直接认定库存错误。\n\n## 范围与待核实\n清洗并不代表真实性全部确认。采购成本仅有静态主表，缺少财务总账、平台补贴承担方、取消原因、活动日历、退款凭证、广告完整账单和库存小时级记录。需业务复核异常价格、数量、未知SKU、库存负数以及超额退款后，才能形成正式全公司利润。\n'
    (ROOT/'reports/data_quality_report.md').write_text(quality,encoding='utf-8')
    pc=platform['contribution'].unstack();pc['change']=pc['2026-09']-pc['2026-08']
    sc=sku['contribution'].unstack();sc['change']=sc['2026-09']-sc['2026-08']
    report=f'''# 2026年9月经营异常分析报告V1

**基于模拟数据的业务分析项目。非真实公司工作经历，不代表真实商业收益。**

## 经营会议结论
在临时有效、成本已知的订单样本中，经营贡献利润由{m.loc['2026-08','contribution']:,.2f}降至{m.loc['2026-09','contribution']:,.2f}美元，减少{s['decline']:,.2f}美元，降幅{s['decline_pct']:.2f}%。此指标扣除商品、履约、佣金、当月确认退款和已记录广告费用，不包含工资、租金、税费等，不能称财务净利润。

销售口径复核：原始含重复记录降幅约30.36%，去重仍含异常约30.39%，暂时排除价格数量异常约18.92%。已知成本利润样本又排除3笔未知SKU订单（收入123.49美元），不能把不同样本的销售差额混用。数据问题显著放大原始降幅，但临时有效样本仍表现下滑。

## 月度利润表（USD）
{markdown(m.reset_index())}

## 可精确对账的利润变化
下面正数推动利润下降、负数抵消下降，合计与利润差额一致。
{markdown(bridge.rename('下降影响').rename_axis('项目').reset_index())}

## 平台与SKU定位
平台贡献利润变化（9月减8月）如下，分平台广告费用直接归属、不按销售额分摊。退款通过原订单的平台归属，但按退款确认月扣除。
{markdown(pc.reset_index())}

SKU贡献利润变化（广告按活动SKU直接归属）如下：
{markdown(sc.sort_values('change').reset_index())}

## 销量、价格和商品结构
商品毛利变化采用固定顺序分解：总件数、SKU件数结构、SKU内平均折前价格、采购单价、优惠总额。以下是会计归因，顺序影响分量；SKU内价格同时受国家及渠道结构影响，不能全部称调价。
{markdown(decomp.rename('毛利变化').rename_axis('因素').reset_index())}

国家维度提供订单销售和商品毛利，不把无法精确归国的广告费随意分摊成国家利润；详细数据见tables/country_changes.csv。品类结构见tables/category_mix.csv。

## 已有证据及情景估算
1. **SKU001库存不足**：9月17日期初10件售罄；18—21日期初、入库、期末均为0，同期完成订单为0，22日入库700件后恢复销售。参考9月10—16日和23—29日，两窗各251件，订单和库存均合计502件。四天潜在少售约143.4件，潜在销售额约{s['stockout_scenario']:,.2f}美元。依赖附近有货日需求和实收稳定假设，不含17日部分缺货，取消原因缺失，不能认定所有取消都由缺货造成。
2. **TK优惠加深**：优惠率3.91%→11.99%；固定9月销量和标价，沿用8月优惠率，额外优惠约{s['extra_discount_scenario']:,.2f}美元。缺少补贴承担方，不能确认商家实际承担全部优惠；促销改变需求，不代表直接可追回利润。
3. **TK广告效率下降**：已知花费样本点击14804→14304，CPC约0.34→0.63美元，ROAS4.87→2.30；固定9月点击数，平均CPC变化对应额外费用约{s['extra_cpc_scenario']:,.2f}美元。实际TK广告费环比增加3918.16美元，两者不可相加。CPC变化也可能含活动结构变化。
4. **SKU004售后增加**：统一下单后12天确认窗口，退款订单率3.31%→17.40%；9月订单批准退款71笔，其中运输损坏23、与描述不符18、质量问题17、不再需要13。9月确认退款58笔与9月下单退款71笔是不同口径。原因标签是调查线索，不能证明供应商或物流的因果责任。

上述情景不能相加为利润损失；它们与销售/费用桥梁及彼此之间可能重叠，最终可精确对账的是利润表六项变化。经营原因的独立因果贡献不能仅凭现有观察数据完全识别。

## 下一步业务行动
|优先级|建议负责人|行动|跟踪指标与验证|
|---|---|---|---|
|P0|数据运营＋财务|核实价格数量、超额退款、SKU999及缺失广告账单；保留修正依据|未解决异常数、收入成本覆盖率、费用对账差额|
|P0|采购＋运营|核查SKU001供应周期、库存预警，暂以覆盖天数监控并建立补货责任人|日库存、连续零库存天数、补货到货偏差；安全库存需实际交期后确定|
|P1|广告运营|按活动和SKU复核TK点击成本与转化；测试预算调整而非全量停投|同口径CPC、ROAS、订单贡献额；设业务审批后的试验预算|
|P1|商品运营|核实优惠承担方，按SKU毛利测算折扣底线，开展对照试验|优惠率、折后贡献率、销量；不能只看销售额|
|P1|售后＋仓储|抽查SKU004运输损坏凭证、包装批次和商品描述|统一12天窗口退款率、损坏率、原因分布；根据证据联系供应商|

以上均为建议，未实施，不声称产生收入或利润收益。

## 方法和限制
订单期2026-08-01至09-30，售后观察截止10-12。8月31天、9月30天，月总量包含天数差异，日均可辅助比较。原始数据有质量问题，当前结果是临时样本估算，缺失广告费用可能低估费用。只有两个月，没有季节性/活动控制及随机试验，不使用相关性冒充因果。报告结论仅来自CSV，不读取生成脚本的预设作为经营证据。
'''
    (ROOT/'reports/september_business_report.md').write_text(report,encoding='utf-8')
    countries=country.sales.unstack();countries['change']=countries['2026-09']-countries['2026-08']
    top_platform=pc['change'].idxmin();top_sku=sc['change'].idxmin()
    appendix=f'''\n## 排查优先级的数字依据\n贡献利润下降最大的平台为{top_platform}，减少{-pc.loc[top_platform,'change']:,.2f}美元，约占当前公司样本净下降的{-pc.loc[top_platform,'change']/s['decline']*100:.2f}%。SKU贡献下降最大为{top_sku}，减少{-sc.loc[top_sku,'change']:,.2f}美元；SKU004贡献减少{-sc.loc['SKU004','change']:,.2f}美元。平台和SKU是同一利润的不同维度，不能相加。\n\n国家销售额变化（9月减8月）：\n{markdown(countries.sort_values('change').reset_index())}\n\n有效销售样本的日均销售额从167440.02/31≈5401.29美元降至135765.53/30≈4525.52美元，日均下降约16.21%；日均件数从5948/31≈191.87降至5115/30=170.50，下降约11.14%。天数差异解释部分月度降幅，但日均也下降。\n'''
    (ROOT/'reports/september_business_report.md').write_text(report+appendix,encoding='utf-8')


def build_dashboard(s,platform,sku,bridge,admetrics,stock,cohort,country):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig=make_subplots(rows=3,cols=2,subplot_titles=['经营贡献利润（临时样本）','利润下降桥梁：正数推动下降','平台贡献利润变化','SKU贡献利润变化','SKU001每日期末库存','广告归因ROAS（已知花费样本）'],vertical_spacing=.10,horizontal_spacing=.14)
    fig.add_trace(go.Bar(x=[x['month'] for x in s['monthly']],y=[x['contribution'] for x in s['monthly']],name='贡献利润',marker_color=['#64748b','#2563eb']),row=1,col=1)
    fig.add_trace(go.Bar(x=bridge.index,y=bridge.values,name='下降影响',marker_color=['#dc2626' if v>0 else '#059669' for v in bridge]),row=1,col=2)
    for frame,label,row,col in [(platform,'平台',2,1),(sku,'SKU',2,2)]:
        w=frame.contribution.unstack();delta=(w['2026-09']-w['2026-08']).sort_values()
        fig.add_trace(go.Bar(x=delta.index,y=delta.values,name=label+'利润变化',marker_color=['#dc2626' if v<0 else '#059669' for v in delta]),row=row,col=col)
    sepstock=stock.loc[stock.date.str.startswith('2026-09')]
    fig.add_trace(go.Scatter(x=sepstock.date,y=sepstock.closing_stock,name='SKU001期末库存',mode='lines+markers',line_color='#2563eb'),row=3,col=1)
    for platform_name in admetrics.index.get_level_values(0).unique():
        g=admetrics.loc[platform_name]
        fig.add_trace(go.Bar(x=g.index,y=g.roas,name=platform_name),row=3,col=2)
    fig.update_layout(height=1150,template='plotly_white',font=dict(family='Microsoft YaHei, Arial',size=13),margin=dict(l=75,r=65,t=65,b=70),barmode='group',legend=dict(orientation='h',y=-.08))
    fig.update_xaxes(tickangle=-25,row=1,col=2)
    fig.update_xaxes(type='category',row=1,col=1)
    fig.update_xaxes(type='category',row=3,col=2)
    charts=fig.to_html(full_html=False,include_plotlyjs=True)
    ms=pd.read_csv(RESULT/'monthly_sales.csv').set_index('month')
    sales_decline=(1-ms.loc['2026-09','sales']/ms.loc['2026-08','sales'])*100
    cards=''.join(f'<div class="card"><span>{label}</span><strong>{value}</strong></div>' for label,value in [('9月贡献利润',f'${s["monthly"][1]["contribution"]:,.2f}'),('利润环比下降',f'{s["decline_pct"]:.2f}%'),('有效样本销售额下降',f'{sales_decline:.2f}%'),('广告花费缺失',f'{s["missing_ad_spend"]} 条')])
    tables=''
    for title,frame in [('平台月度利润',platform.reset_index()),('SKU004统一12天退款窗口',cohort.loc['SKU004'].reset_index()),('国家销售与毛利（不分摊广告）',country.reset_index())]:
        tables+=f'<details><summary>{title}</summary><div class="table">{frame.round(2).to_html(index=False,border=0)}</div></details>'
    html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>跨境电商经营诊断V1</title><style>body{{font-family:Microsoft YaHei,Arial;background:#f1f5f9;color:#0f172a;margin:0}}main{{max-width:1320px;margin:auto;padding:32px}}h1{{font-size:28px}}p{{line-height:1.8}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}.card{{background:white;border-radius:12px;padding:22px}}.card span{{display:block;color:#475569}}.card strong{{display:block;font-size:28px;margin-top:12px}}.notice{{background:#fff7ed;border-left:5px solid #ea580c;padding:14px;margin:24px 0}}.plots,details{{background:white;border-radius:12px;padding:18px;margin-top:18px}}summary{{cursor:pointer;font-weight:bold}}.table{{overflow:auto}}td,th{{padding:10px;text-align:right;white-space:nowrap}}@media(max-width:700px){{main{{padding:14px}}.cards{{grid-template-columns:1fr 1fr}}}}</style><main><h1>跨境电商经营分析 · 2026年9月</h1><p>基于模拟数据的业务分析项目 · V1 · 原始数据只读 · 金额USD</p><div class="cards">{cards}</div><div class="notice">临时口径：有效且成本已知订单、相同订单有效批准退款按确认月、全部已记录广告费。异常订单未猜测修正；不是财务净利润。点击图例筛选，悬停查看值，可缩放及导出图片。情景估算不能与会计桥梁重复相加。</div><div class="plots">{charts}</div>{tables}<p>完整口径和行动建议：<a href="../reports/september_business_report.md">经营报告</a>。图表来自scripts/run_project_v1.py，离线可打开，无外部网络依赖。</p></main></html>'''
    (ROOT/'dashboard/index.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    run()
