"""Versioned explainable business rules, deduplicated tasks and append-only actions."""
from datetime import timedelta
from decimal import Decimal
import json
import math
import pandas as pd
from v2.metrics import MetricCenter,today
from v2.service import dump,now

DEFAULTS={
 'stock_low':('安全库存不足',40,7,'高',1),
 'stock_cover':('库存覆盖天数不足',14,7,'高',3),
 'stock_trend':('销量增加但库存下降',.2,7,'中',3),
 'sales_drop':('有效销售额下降',.2,7,'高',3),
 'margin_drop':('已知样本毛利率下降',.05,7,'高',3),
 'contribution_drop':('暂估贡献利润下降',.2,7,'高',3),
 'unknown_cost_up':('成本未知订单占比上升',.05,7,'高',3),
 'roas_low':('广告归因ROAS偏低',2,7,'中',3),
 'ad_spend_up':('广告费上升但归因收入下降',.2,7,'中',3),
 'roas_drop':('广告归因效率下降',.2,7,'中',3),
 'refund_rate_high':('12天退款订单率偏高',.1,7,'高',3),
 'refund_sku':('SKU退款异常集中',.2,7,'高',3),
 'refund_platform_up':('平台退款订单率上升',.05,7,'中',3)}

FORMULAS={
 'stock_low':'最近有效快照 closing_stock < 安全库存',
 'stock_cover':'库存覆盖天数=closing_stock/(观察窗口有效完成销量/窗口天数)',
 'stock_trend':'销量增幅=(本期销量−上期销量)/上期销量；同期库存下降',
 'sales_drop':'下降率=(上期有效销售额−本期有效销售额)/上期有效销售额',
 'margin_drop':'毛利率下降百分点=上期已知样本毛利率−本期已知样本毛利率',
 'contribution_drop':'下降率=(上期暂估贡献−本期暂估贡献)/上期暂估贡献',
 'unknown_cost_up':'占比增幅=本期成本未知订单占比−上期占比',
 'roas_low':'同样本广告归因收入/广告花费 < 阈值',
 'ad_spend_up':'广告费用增幅≥阈值，且同样本广告归因收入下降',
 'roas_drop':'ROAS下降率=(上期ROAS−本期ROAS)/上期ROAS',
 'refund_rate_high':'下单后12天内有效批准退款的不同订单数/成熟已知成本订单数',
 'refund_sku':'按SKU计算12天退款订单率，不按退款金额混算',
 'refund_platform_up':'平台12天退款订单率：本期−上期（百分点）'}


def safe_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=lambda x:str(x))


class AlertEngine:
    def __init__(self,store):
        self.store=store

    def rules(self,workspace):
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for kind,(name,threshold,window,severity,minimum) in DEFAULTS.items():
                cur=con.execute('INSERT OR IGNORE INTO alert_rules(workspace,name,kind,enabled,threshold,window_days,severity,min_sample,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                                (workspace,name,kind,1,threshold,window,severity,minimum,now()))
                if cur.rowcount:
                    rule=dict(con.execute('SELECT * FROM alert_rules WHERE id=?',(cur.lastrowid,)).fetchone())
                    con.execute('INSERT INTO alert_rule_versions VALUES(?,?,?,?,?,?)',(rule['id'],1,dump(rule),'演示配置','初始演示阈值，不是行业标准',now()))
            return [dict(r) for r in con.execute('SELECT * FROM alert_rules WHERE workspace=? ORDER BY id',(workspace,))]

    def configure(self,workspace,rule_id,expected_version,actor,note,**changes):
        allowed={'name','enabled','threshold','window_days','severity','min_sample'}
        if not changes or not set(changes)<=allowed or not actor.strip() or not note.strip():
            raise ValueError('配置字段、操作员与修改说明必填')
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            old=con.execute('SELECT * FROM alert_rules WHERE id=? AND workspace=?',(rule_id,workspace)).fetchone()
            if not old or old['version']!=expected_version:raise ValueError('规则已修改或不属于当前空间，请刷新')
            data={**dict(old),**changes,'version':old['version']+1,'updated_at':now()}
            if not str(data['name']).strip() or not math.isfinite(float(data['threshold'])) or float(data['threshold'])<0:
                raise ValueError('名称不能为空；阈值必须为有限非负数')
            if data['kind'] not in ('stock_low','stock_cover','roas_low') and data['threshold']>1:
                raise ValueError('比例/百分点阈值范围为0至1，例如20%填写0.2')
            if int(data['window_days'])!=data['window_days'] or not 1<=data['window_days']<=90 or int(data['min_sample'])!=data['min_sample'] or data['min_sample']<1:
                raise ValueError('观察窗口1至90整数天、最小样本至少1')
            if data['severity'] not in ('高','中','低') or data['enabled'] not in (0,1):raise ValueError('严重程度或启停值无效')
            con.execute('UPDATE alert_rules SET name=?,enabled=?,threshold=?,window_days=?,severity=?,min_sample=?,version=?,updated_at=? WHERE id=?',
                        tuple(data[k] for k in ('name','enabled','threshold','window_days','severity','min_sample','version','updated_at','id')))
            con.execute('INSERT INTO alert_rule_versions VALUES(?,?,?,?,?,?)',(rule_id,data['version'],dump(data),actor,note,now()))
            self.store.log(con,workspace,'rule_config',rule_id,actor,{'before':dict(old),'after':data,'note':note})
            return data

    def run(self,workspace,as_of=None,actor='本地规则引擎'):
        as_of=as_of or today()
        as_of=pd.Timestamp(as_of).date()
        center=MetricCenter(self.store);facts=center.facts(workspace)
        observed={r['date'] for r in facts['candidates'] if r['table']=='orders' and r['date'] and r['date']<str(as_of)}
        inventory_dates={r['date'] for r in facts['inventory'] if r['date']<str(as_of)}
        report={'triggered':0,'new':0,'skipped':[],'as_of':str(as_of)}
        rules=self.rules(workspace)
        if not observed and not inventory_dates:
            report['skipped'].append('没有已结束的订单观测日或有效库存快照，不能计算周期');return report
        end=pd.Timestamp(max(observed | inventory_dates)).date()
        platforms=sorted({r['platform'] for r in facts['orders'] if r['platform']})
        skus=sorted({r['sku'] for r in facts['orders']} | {r['sku'] for r in facts['inventory']})
        objects=[('公司',{})]+[(f'平台:{p}',{'platform':p}) for p in platforms]+[(f'SKU:{s}',{'sku':s}) for s in skus]
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for rule in rules:
                if not rule['enabled']:continue
                available=inventory_dates if rule['kind'].startswith('stock_') else observed
                if not available:
                    report['skipped'].append(rule['name']+'：必要的订单日/库存快照不足');continue
                end=pd.Timestamp(max(available)).date()
                days=rule['window_days'];start=end-timedelta(days=days-1)
                prev_end=start-timedelta(days=1);prev_start=prev_end-timedelta(days=days-1)
                period={'start':str(start),'end':str(end),'previous_start':str(prev_start),'previous_end':str(prev_end)}
                selected_objects=[(name,filt) for name,filt in objects
                                  if (rule['kind']!='refund_sku' or name.startswith('SKU:'))
                                  and (rule['kind']!='refund_platform_up' or name.startswith('平台:'))
                                  and (not rule['kind'].startswith('stock_') or name.startswith('SKU:'))]
                # Keep task status historical; mark this exact run's old signals as no longer detected.
                con.execute('UPDATE alerts SET current_triggered=0 WHERE workspace=? AND rule_id=? AND rule_version=? AND period_start=? AND period_end=?',
                            (workspace,rule['id'],rule['version'],str(start),str(end)))
                for object_key,filt in selected_objects:
                    current=center.calculate(workspace,start,end,as_of=as_of,**filt)
                    previous=center.calculate(workspace,prev_start,prev_end,as_of=as_of,**filt)
                    value,reason,extra=self.evaluate(rule,current,previous,center,workspace,period,filt,observed)
                    if value is None:
                        if reason=='未达到阈值':
                            con.execute("UPDATE alerts SET current_triggered=0 WHERE workspace=? AND rule_id=? AND rule_version=? AND object_key=? AND status IN ('待处理','处理中')",(workspace,rule['id'],rule['version'],object_key))
                        report['skipped'].append(f"{rule['name']} / {object_key}：{reason}");continue
                    evidence={'what':reason,'object':object_key,'period':period,'as_of':str(as_of),
                              'formula':FORMULAS[rule['kind']],'current':self.evidence_metrics(current),
                              'previous':self.evidence_metrics(previous),'data_sources':
                              sorted({r['batch_id'] for r in current['orders_detail']+current['ads_detail']+current['refunds_detail']}),
                              'order_record_ids':[r['record_id'] for r in current['orders_detail']],
                              'source_versions':[{'record_id':r['record_id'],'batch_id':r['batch_id'],'revision_ids':r['revision_ids']}
                                                 for r in current['orders_detail']+current['ads_detail']+current['refunds_detail']],
                              'limits':current['limits'],'extra':extra,
                              'possible_causes':['促销、商品结构、平台流量或费用变化可能相关，需凭证核实；不是确定因果'],
                              'checklist':['核对源批次和隔离记录','核查活动日历/成本/广告账单/售后凭证','对比相同窗口和覆盖范围']}
                    for order in current['orders_detail']:
                        if order['cost_source']:
                            src=order['cost_source']
                            if src['batch_id'] not in evidence['data_sources']:evidence['data_sources'].append(src['batch_id'])
                            version={k:src[k] for k in ('record_id','batch_id','revision_ids')}
                            if version not in evidence['source_versions']:evidence['source_versions'].append(version)
                    if extra.get('snapshot'):
                        src=extra['snapshot']
                        if src['batch_id'] not in evidence['data_sources']:evidence['data_sources'].append(src['batch_id'])
                        evidence['source_versions'].append({k:src[k] for k in ('record_id','batch_id','revision_ids')})
                    encoded=safe_json(evidence);stamp=now()
                    key=(workspace,rule['id'],rule['version'],object_key)
                    item=con.execute('SELECT a.id FROM alerts a WHERE a.workspace=? AND a.rule_id=? AND a.rule_version=? AND a.object_key=? AND ((a.period_start=? AND a.period_end=?) OR EXISTS(SELECT 1 FROM alert_detections d WHERE d.alert_id=a.id AND json_extract(d.evidence_json,\'$.period.start\')=? AND json_extract(d.evidence_json,\'$.period.end\')=?)) ORDER BY a.id LIMIT 1',
                                     key+(str(start),str(end),str(start),str(end))).fetchone()
                    if not item:
                        item=con.execute("SELECT id FROM alerts WHERE workspace=? AND rule_id=? AND rule_version=? AND object_key=? AND status IN ('待处理','处理中') ORDER BY id LIMIT 1",key).fetchone()
                    added=0
                    if item:
                        con.execute('UPDATE alerts SET last_detected=?,detected_count=detected_count+1,current_triggered=1,metric_value=?,evidence_json=? WHERE id=?',(stamp,float(value),encoded,item['id']))
                    else:
                        cur=con.execute('INSERT INTO alerts(workspace,rule_id,rule_version,rule_snapshot,object_key,period_start,period_end,severity,metric_value,threshold,evidence_json,first_detected,last_detected) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                        (workspace,rule['id'],rule['version'],dump(rule),object_key,str(start),str(end),rule['severity'],float(value),rule['threshold'],encoded,stamp,stamp))
                        item={'id':cur.lastrowid};added=1
                    con.execute('INSERT INTO alert_detections(alert_id,metric_value,evidence_json,created_at) VALUES(?,?,?,?)',(item['id'],float(value),encoded,stamp))
                    report['triggered']+=1;report['new']+=added
            self.store.log(con,workspace,'alert_detection',str(end),actor,report)
        return report

    @staticmethod
    def evidence_metrics(data):
        return {k:v for k,v in data.items() if not k.endswith('_detail')}

    def evaluate(self,rule,current,previous,center,workspace,period,filt,observed):
        kind=rule['kind'];threshold=Decimal(str(rule['threshold']));minimum=rule['min_sample']
        dates=set(str(d.date()) for d in pd.date_range(period['start'],period['end']))
        previous_dates=set(str(d.date()) for d in pd.date_range(period['previous_start'],period['previous_end']))
        if kind.startswith('stock_'):
            sku=filt['sku'];snapshots=[r for r in center.facts(workspace)['inventory'] if r['sku']==sku and r['date']<=period['end']]
            if not snapshots:return None,'缺少可用库存快照',{}
            latest=max(snapshots,key=lambda r:r['date']);stock=latest['closing_stock']
            extra={'snapshot':latest,'in_transit':'未提供，不推测','sales_window':period}
            if latest['date']!=period['end']:return None,'库存快照过期，不按历史库存触发当前预警',extra
            if kind=='stock_low':
                if sum(period['start']<=r['date']<=period['end'] for r in snapshots)<minimum:
                    return None,'库存快照样本不足',extra
                return (stock,'观测周期末有效库存低于演示安全库存',extra) if stock<threshold else (None,'未达到阈值',extra)
            if not dates<=observed or current['orders']<minimum:return None,'销量日记录不连续或样本不足，覆盖天数不可计算',extra
            units=sum((r['quantity'] for r in current['orders_detail']),Decimal(0))
            if units<=0:return None,'观察窗口销量为0，不能估计覆盖天数',extra
            cover=stock/(units/rule['window_days']);extra['coverage_days']=cover
            if kind=='stock_cover':return (cover,'预计库存覆盖天数不足',extra) if cover<threshold else (None,'未达到阈值',extra)
            prev_units=sum((r['quantity'] for r in previous['orders_detail']),Decimal(0))
            prev_stock=[r for r in snapshots if r['date']==period['previous_end']]
            if not previous_dates<=observed or previous['orders']<minimum or prev_units<=0 or not prev_stock:return None,'基期销量或库存快照不足',extra
            growth=(units-prev_units)/prev_units;extra['previous_stock']=prev_stock[0]['closing_stock']
            return (growth,'销量增加且库存下降',extra) if growth>=threshold and stock<prev_stock[0]['closing_stock'] else (None,'未达到阈值',extra)
        if current['orders']<minimum:return None,'有效订单样本不足',{}
        if not dates<=observed:return None,'观察周期缺少订单日记录，不能假定缺日为0',{}
        if kind in ('refund_rate_high','refund_sku'):
            if current['refund_rate'] is None or current['mature_orders']<minimum:return None,'12天退款观察未成熟、账本缺失或样本不足',{}
            return (current['refund_rate'],'成熟订单的12天退款订单率达到阈值',{}) if current['refund_rate']>=threshold else (None,'未达到阈值',{})
        if kind=='roas_low':
            if current['roas'] is None or len(current['ads_detail'])<minimum:return None,'ROAS不可计算，归因收入/费用缺失或广告样本不足',{}
            return (current['roas'],'广告归因ROAS低于阈值',{}) if current['roas']<threshold else (None,'未达到阈值',{})
        if not previous_dates<=observed or previous['orders']<minimum:return None,'上一同长度周期记录不连续或样本不足',{}
        if kind=='refund_platform_up' and min(current['mature_orders'],previous['mature_orders'])<minimum:
            return None,'成熟退款队列样本不足',{}
        if kind in ('ad_spend_up','roas_drop') and min(len(current['ads_detail']),len(previous['ads_detail']))<minimum:
            return None,'广告有效记录样本不足',{}
        if kind=='sales_drop':key='sales'
        elif kind=='margin_drop':key='gross_margin'
        elif kind=='contribution_drop':key='contribution'
        elif kind=='unknown_cost_up':key='unknown_share'
        elif kind=='refund_platform_up':key='refund_rate'
        else:key='roas'
        a,b=current.get(key),previous.get(key)
        if a is None or b is None:return None,'必要指标数据不足，不能进行普通环比',{}
        if kind in ('margin_drop','contribution_drop'):
            # Cost/quality coverage cannot be silently changed between samples.
            if current['cost_coverage']!=previous['cost_coverage'] or current['data_completeness']!=previous['data_completeness'] or current['missing_ads'] or previous['missing_ads'] or current['missing_refunds'] or previous['missing_refunds']:
                return None,'成本/质检覆盖范围变化或费用缺失，先核查完整性；不判断利润改善或恶化',{}
        if kind=='margin_drop':value=b-a
        elif kind in ('unknown_cost_up','refund_platform_up'):value=a-b
        elif kind=='ad_spend_up':
            base=previous['recorded_ad_cost'];spend=current['recorded_ad_cost']
            if not base or spend is None:return None,'基期广告费为0或缺失，增幅不可计算',{}
            value=(spend-base)/base
            if current['attributed_revenue']>=previous['attributed_revenue']:return None,'广告归因收入未下降',{}
        else:
            if b<=0:return None,'基期为0或负值，普通下降百分比不可比',{}
            value=(b-a)/b
        return (value,'同长度完整观测周期指标达到规则阈值',{}) if value>=threshold else (None,'未达到阈值',{})

    def action(self,workspace,alert_id,status,note,actor,expected_version):
        if status not in ('待处理','处理中','已解决','已忽略') or not note.strip() or not actor.strip():raise ValueError('状态、处理说明和操作员必填')
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            old=con.execute('SELECT * FROM alerts WHERE id=? AND workspace=?',(alert_id,workspace)).fetchone()
            if not old or old['state_version']!=expected_version:raise ValueError('预警跨空间或已被处理，请刷新')
            con.execute('UPDATE alerts SET status=?,state_version=state_version+1 WHERE id=?',(status,alert_id))
            con.execute('INSERT INTO alert_actions(alert_id,from_status,to_status,note,actor,created_at) VALUES(?,?,?,?,?,?)',(alert_id,old['status'],status,note,actor,now()))
            self.store.log(con,workspace,'alert_action',alert_id,actor,{'from':old['status'],'to':status,'note':note})
