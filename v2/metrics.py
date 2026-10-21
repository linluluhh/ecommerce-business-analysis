"""One metric service for legacy cards, filtered dashboards, exports and alerts."""
from datetime import datetime,timedelta
from decimal import Decimal
import json
from zoneinfo import ZoneInfo
import pandas as pd

ZERO=Decimal(0)
DEFINITIONS={
 'orders':('有效订单数','有效 completed 订单去重数','单 SKU 订单，排除整行隔离'),
 'sales':('折后销售额','Σ(quantity×unit_price−整单discount)','有效 completed，含未知成本收入'),
 'known_cost_sales':('成本已知订单销售额','利润样本订单折后收入之和','商品成本有效且已知'),
 'gross_profit':('商品毛利','成本已知销售额−商品成本','不扣物流、佣金、退款、广告'),
 'gross_margin':('商品毛利率','商品毛利/成本已知销售额','相同已知成本样本，比例非百分数'),
 'recorded_ad_cost':('已记录广告费用','Σ有效 ad_spend','未知费用不补0；不证明账本完整'),
 'refund_cost':('退款金额','有效 approved 退款金额之和','已知成本订单范围，按退款确认日'),
 'refund_rate':('12天退款订单率','12天内批准退款的不同订单/成熟有效成本已知订单','按下单队列；金额退款率另列，不能混用'),
 'contribution':('暂估经营贡献利润','毛利−物流−佣金−确认退款−已记录广告','已知成本样本及观测费用；非净利润'),
 'data_completeness':('数据完整率（订单可用）','有效完成订单/可定位期间的原始 completed 订单','记录可用比例，不等于已收齐业务账本'),
 'cost_coverage':('成本覆盖率','成本已知订单销售额/有效销售额','按收入覆盖；订单覆盖率另列'),
 'unknown_orders':('成本未知订单数','有效完成订单数−已知成本样本数','收入保留，利润未知'),
 'unknown_sales':('成本未知订单收入','有效收入中未进入已知成本样本的收入之和','不将未知成本填0'),
 'goods_cost':('已知商品成本','Σ已知样本quantity×unit_cost','同毛利订单样本'),
 'shipping_cost':('已知样本物流费用','Σ利润样本shipping_fee','完成订单，退款不返还费用'),
 'platform_cost':('已知样本平台佣金','Σ利润样本platform_fee','完成订单，取消不确认费用'),
 'roas':('广告归因ROAS','同样本 attributed_revenue/ad_spend','广告归因收入不得再加到订单收入')}


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def total(rows,key):
    return sum((r[key] for r in rows),ZERO)


def in_scope(row,start=None,end=None,platform=None,sku=None,country=None,status=None):
    return (not start or row['date']>=str(start)) and (not end or row['date']<=str(end)) and \
        (not platform or row.get('platform')==platform) and (not sku or row.get('sku')==sku) and \
        (not country or row.get('country')==country) and (not status or row.get('status')==status)


class MetricCenter:
    def __init__(self,store):
        self.store=store
        self._snapshots={}

    def facts(self,workspace):
        if workspace in self._snapshots:
            return self._snapshots[workspace]
        with self.store.connect() as con:
            con.execute('BEGIN')
            clean,diagnostics=self.store.evaluate(con,workspace)
            rows=self.store.records(con,workspace)
            saved={ (a['record_id'],a['code']):dict(a) for a in con.execute('SELECT a.* FROM anomalies a JOIN records r ON a.record_id=r.id WHERE r.workspace=?',(workspace,)) }
            names={r['id']:r['filename'] for r in con.execute('SELECT id,filename FROM batches WHERE workspace=?',(workspace,))}
        # Re-evaluate effective revisions; old resolved flags cannot poison new values.
        from v2.rules import policy,v1
        blocked,profit_blocked=set(),set()
        active=[]
        for issue in diagnostics:
            scope,hard,_=policy(issue['issue'],issue['table'])
            state=saved.get((issue['record_id'],issue['issue']),{}).get('status','待核实')
            active.append((issue['record_id'],scope,state))
            if scope!='none' and (hard or state!='驳回'):
                (blocked if scope=='all' else profit_blocked).add(issue['record_id'])
        raw={r['id']:json.loads(r['raw_json']) for r in rows}
        sources={r['id']:r for r in rows}
        dec=lambda v:Decimal(str(v))
        products={r.sku_standard:dec(raw[idx]['unit_cost']) for idx,r in clean['products'].iterrows() if idx not in blocked}
        product_ids={r.sku_standard:idx for idx,r in clean['products'].iterrows() if idx not in blocked}
        def source(idx):
            r=sources[idx]
            return {'record_id':idx,'batch_id':r['batch_id'],'source_file':names[r['batch_id']],
                    'source_row':r['source_row'],'revision_ids':r.get('revision_ids',[])}
        orders=[]
        for idx,r in clean['orders'].iterrows():
            if idx in blocked:continue
            row=raw[idx];completed=r.order_status=='completed'
            known=completed and idx not in profit_blocked and r.sku_standard in products
            amount=dec(row['quantity'])*dec(row['unit_price'])-dec(row['discount']) if completed else ZERO
            cost=dec(row['quantity'])*products[r.sku_standard] if known else None
            orders.append({**source(idx),'order_id':r.order_id,'date':str(r.order_date_standard.date()),'month':r.month,
                           'sku':r.sku_standard,'platform':r.platform_standard,'country':r.country_standard,
                           'status':r.order_status,'quantity':dec(row['quantity']),'sales':amount,'known':known,
                           'cost_source':source(product_ids[r.sku_standard]) if known else None,
                           'goods_cost':cost,'gross_profit':amount-cost if known else None,
                           'shipping_cost':dec(row['shipping_fee']) if known else None,
                           'platform_cost':dec(row['platform_fee']) if known else None})
        known_orders={r['order_id']:r for r in orders if r['known']}
        refunds=[]
        for idx,r in clean['refunds'].iterrows():
            if idx in blocked or r.refund_status!='approved' or r.order_id not in known_orders:continue
            order=known_orders[r.order_id]
            refunds.append({**source(idx),'order_id':r.order_id,'date':str(r.refund_date_standard.date()),
                            'order_date':order['date'],'month':r.refund_month,'sku':order['sku'],
                            'platform':order['platform'],'country':order['country'],
                            'refund_cost':dec(raw[idx]['refund_amount'])})
        ads=[]
        for idx,r in clean['ads'].iterrows():
            if idx in blocked:continue
            ads.append({**source(idx),'date':str(r.date_standard.date()),'month':r.month,'sku':r.sku_standard,
                        'platform':r.platform_standard,'recorded_ad_cost':dec(raw[idx]['ad_spend']),
                        'attributed_revenue':dec(raw[idx]['attributed_revenue'])})
        inventory=[]
        for idx,r in clean['inventory'].iterrows():
            if idx not in blocked:
                inventory.append({**source(idx),'date':str(r.date_standard.date()),'sku':r.sku_standard,
                                  'closing_stock':dec(raw[idx]['closing_stock'])})
        candidates=[]
        for rec in rows:
            value=raw[rec['id']]
            datecol={'orders':'order_date','refunds':'refund_date','ads':'date','inventory':'date'}.get(rec['table_name'])
            if not datecol:continue
            date=pd.to_datetime(str(value[datecol]).replace('/','-'),format='%Y-%m-%d',errors='coerce')
            candidates.append({**source(rec['id']),'table':rec['table_name'],
                               'date':str(date.date()) if not pd.isna(date) else '',
                               'status':value.get('order_status'),'sku':str(value.get('sku','')).strip().upper(),
                               'platform':self.store.key_value('platform',value.get('platform')),
                               'country':v1.COUNTRIES.get(str(value.get('country','')).strip().lower()),
                               'raw':value,'blocked':rec['id'] in blocked})
        result={'orders':orders,'refunds':refunds,'ads':ads,'inventory':inventory,'candidates':candidates,
                'blocked':blocked,'profit_blocked':profit_blocked,'active':active}
        self._snapshots[workspace]=result
        return result

    def calculate(self,workspace,start=None,end=None,platform=None,sku=None,country=None,status=None,as_of=None):
        if start and end and str(start)>str(end):raise ValueError('开始日期不能晚于结束日期')
        as_of=as_of or today()
        snap=self.facts(workspace)
        filters=dict(start=start,end=end,platform=platform,sku=sku,country=country,status=status)
        observed=[r for r in snap['candidates'] if r['table']=='orders' and r['date'] and in_scope(r,**filters)]
        selected=[r for r in snap['orders'] if in_scope(r,**filters)]
        orders=[r for r in selected if r['status']=='completed']
        known=[r for r in orders if r['known']]
        unknown=[r for r in orders if not r['known']]
        expenses=dict(start=start,end=end,platform=platform,sku=sku,country=country)
        refunds=[r for r in snap['refunds'] if in_scope(r,**expenses)] if status!='cancelled' else []
        # Shared ads cannot be allocated to country or cancelled orders.
        ads=[r for r in snap['ads'] if in_scope(r,start,end,platform,sku)] if not country and status!='cancelled' else []
        ad_raw=[r for r in snap['candidates'] if r['table']=='ads' and r['date'] and in_scope(r,start,end,platform,sku)]
        missing_ads=sum(r['blocked'] for r in ad_raw)
        sales=total(orders,'sales') if selected else None
        known_sales=total(known,'sales') if known else None
        gross=total(known,'gross_profit') if known else None
        ad_cost=total(ads,'recorded_ad_cost') if ads else None
        ad_revenue=total(ads,'attributed_revenue') if ads else None
        before=(gross-total(known,'shipping_cost')-total(known,'platform_cost')) if known else None
        refund_raw=[r for r in snap['candidates'] if r['table']=='refunds']
        refund_isolated=sum(r['blocked'] and in_scope(r,start,end) for r in refund_raw if r['date'])
        refund_usable=any(not r['blocked'] for r in refund_raw)
        refund_cost=total(refunds,'refund_cost') if refund_usable else None
        contribution=before-refund_cost-ad_cost if before is not None and refund_cost is not None and ad_cost is not None else None
        horizon=str(as_of)
        mature=[r for r in known if (pd.Timestamp(horizon)-pd.Timestamp(r['date'])).days>=12]
        mature_dates={r['order_id']:r['date'] for r in mature}
        isolated_cohort_refunds=sum(r['blocked'] and r['raw'].get('order_id') in mature_dates and
            (not r['date'] or (r['date']<=horizon and 0<=(pd.Timestamp(r['date'])-pd.Timestamp(mature_dates[r['raw']['order_id']])).days<=12))
            for r in refund_raw)
        refunded={r['order_id'] for r in snap['refunds'] if r['date']<=horizon and 0<=(pd.Timestamp(r['date'])-pd.Timestamp(r['order_date'])).days<=12}
        # An absent refund ledger cannot prove zero refunds.
        refund_rate=Decimal(sum(r['order_id'] in refunded for r in mature))/len(mature) if mature and refund_usable and not isolated_cohort_refunds else None
        costs_known_count=len(known)
        raw_completed=[r for r in observed if r['status']=='completed']
        completeness=Decimal(len(orders))/len(raw_completed) if raw_completed else None
        limits=['USD；单SKU订单；静态采购成本；不含工资/税费/汇兑；已记录费用不等于完整账本']
        undated=sum(not r['date'] for r in snap['candidates'])
        if undated:limits.append(f'当前空间另有无法定位日期记录 {undated} 条，不能分配到当前日期筛选或当作0')
        if unknown:limits.append('成本未知订单收入保留，所有利润及毛利率仅覆盖成本已知样本')
        if missing_ads:limits.append(f'广告隔离/缺失费用记录 {missing_ads} 条，贡献仅为观测部分样本')
        if not ads:limits.append('缺少可用广告费用/归因收入；ROAS 或贡献无法计算')
        if not refund_raw:limits.append('未提供退款账本，退款金额/退款率/贡献数据不足')
        if refund_isolated:limits.append(f'确认期间隔离退款 {refund_isolated} 条，退款率与利润预警不作为完整样本判断')
        if isolated_cohort_refunds:limits.append(f'12天订单队列中有隔离退款 {isolated_cohort_refunds} 条，退款率不可计算')
        if country:limits.append('广告无法精确归属国家，不分摊广告，国家贡献无法计算')
        if len(mature)<len(known):limits.append('退款率排除尚未观察满12天的订单')
        data={
            'orders':len(orders),'sales':sales,'known_cost_sales':known_sales,'gross_profit':gross,
            'gross_margin':gross/known_sales if known_sales and gross is not None else None,
            'goods_cost':total(known,'goods_cost') if known else None,
            'shipping_cost':total(known,'shipping_cost') if known else None,
            'platform_cost':total(known,'platform_cost') if known else None,
            'recorded_ad_cost':ad_cost,'attributed_revenue':ad_revenue,
            'roas':ad_revenue/ad_cost if ad_cost and ad_revenue is not None and not missing_ads else None,
            'refund_cost':refund_cost,'refund_rate':refund_rate,'mature_orders':len(mature),
            'contribution':contribution,'data_completeness':completeness,
            'cost_coverage':known_sales/sales if sales and known_sales is not None else (ZERO if sales else None),
            'profit_orders':costs_known_count,'unknown_orders':len(unknown),'unknown_sales':total(unknown,'sales'),
            'unknown_share':Decimal(len(unknown))/len(orders) if orders else None,
            'partial':bool(unknown or missing_ads or not ads or not refund_raw or any(r['blocked'] for r in observed)),
            'missing_ads':missing_ads,'missing_refunds':refund_isolated,'missing_cohort_refunds':isolated_cohort_refunds,
            'limits':limits,'filters':{k:str(v) if v is not None else None for k,v in filters.items()},
            'as_of':horizon,'orders_detail':orders,'refunds_detail':refunds,'ads_detail':ads}
        return data

    def trend(self,workspace,start,end,**filters):
        return [{'date':str(day.date()),**{k:v for k,v in self.calculate(workspace,str(day.date()),str(day.date()),**filters).items()
                 if k in ('orders','sales','known_cost_sales','gross_profit','contribution','refund_cost')}}
                for day in pd.date_range(start,end)]

    def legacy(self,workspace):
        """Phase-1 compatible contract using exactly the same eligible facts."""
        snap=self.facts(workspace)
        orders=[r for r in snap['orders'] if r['status']=='completed']
        known=[r for r in orders if r['known']]
        monthly={}
        def bucket(month):
            return monthly.setdefault(month,{k:ZERO for k in ('sales','known_cost_sales','before_refunds_ads','refund_cost','recorded_ad_cost')})
        for r in orders:
            b=bucket(r['month']);b['sales']+=r['sales']
            if r['known']:
                b['known_cost_sales']+=r['sales'];b['before_refunds_ads']+=r['gross_profit']-r['shipping_cost']-r['platform_cost']
        for r in snap['refunds']:bucket(r['month'])['refund_cost']+=r['refund_cost']
        for r in snap['ads']:bucket(r['month'])['recorded_ad_cost']+=r['recorded_ad_cost']
        for b in monthly.values():b['contribution']=b['before_refunds_ads']-b['refund_cost']-b['recorded_ad_cost']
        ads=total(snap['ads'],'recorded_ad_cost') if snap['ads'] else None
        refunds=total(snap['refunds'],'refund_cost')
        gross=total(known,'gross_profit')
        shipping=total(known,'shipping_cost');platform=total(known,'platform_cost')
        lineage=[{k:r[k] for k in ('record_id','order_id','month','sku','sales','batch_id','source_file','source_row')}
                 | {'profit_included':r['known']} for r in orders]
        return {'sales':total(orders,'sales'),'gross_profit':gross,'refund_cost':refunds,'recorded_ad_cost':ads,
                'goods_cost':total(known,'goods_cost'),'shipping_cost':shipping,'platform_cost':platform,
                'contribution':gross-shipping-platform-refunds-ads if ads is not None else None,
                'orders':len(orders),'profit_orders':len(known),'isolated_records':len(snap['blocked']),
                'profit_isolated':len(orders)-len(known),
                'unreviewed':sum(status=='待核实' and scope!='none' for _,scope,status in snap['active']),
                'monthly':monthly,'partial':bool(snap['blocked'] or snap['profit_blocked'] or not snap['ads']),
                'sales_records':lineage}
