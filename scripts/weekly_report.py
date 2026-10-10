"""自动化经营周报：确定性指标 + AI证据包 + 可选AI草稿核验。

不自动发送、不依赖付费API。AI辅助需把证据包交给模型，并用--ai-draft核验返回JSON。
允许AI润色说明，指标只能用白名单键引用，报告中的数值由脚本填入，禁止AI编造数值。
"""
import argparse
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def generate(start,end,ai_draft=None):
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if (end-start).days!=6: raise ValueError('周报区间必须连续7天，含起止日')
    if start<pd.Timestamp('2026-08-08') or end>pd.Timestamp('2026-09-30'):
        raise ValueError('需要完整本周和前7天业务数据：起日>=2026-08-08，结束日<=2026-09-30')
    o=pd.read_csv(ROOT/'data/processed/profit_orders.csv')
    r=pd.read_csv(ROOT/'data/processed/profit_refunds.csv')
    a=pd.read_csv(ROOT/'data/processed/ads_clean.csv')
    o['day']=pd.to_datetime(o.order_date_standard);r['day']=pd.to_datetime(r.refund_date_standard);a['day']=pd.to_datetime(a.date_standard)
    metrics={}
    for label,lo,hi in [('current',start,end),('previous',start-pd.Timedelta(days=7),start-pd.Timedelta(days=1))]:
        oo=o.loc[o.day.between(lo,hi)];rr=r.loc[r.day.between(lo,hi)];aa=a.loc[a.day.between(lo,hi)]
        metrics[label]={'sales':round(oo.order_sales.sum(),2),'units':int(oo.quantity.sum()),'orders':int(oo.order_id.nunique()),'gross_profit':round(oo.gross_profit.sum(),2),'refunds':round(rr.refund_amount.sum(),2),'recorded_ads':round(aa.ad_spend.sum(min_count=1),2),'missing_ad_spend':int(aa.ad_spend.isna().sum()),'ad_record_count':len(aa),'expected_ad_record_count':7*36,'contribution':round(oo.before_refunds_ads.sum()-rr.refund_amount.sum()-aa.ad_spend.sum(min_count=1),2)}
    evidence={'project':'基于模拟数据的业务分析项目','start':str(start.date()),'end':str(end.date()),'scope':'成本已知有效订单；同范围批准有效退款按确认日；全部已记录广告费；不是净利润','metrics':metrics,'limitations':['订单价格数量异常暂排除','未知商品成本未填0','广告缺失未填0，固定活动每日模式仅作为缺行提示','变化是描述结果，不足以证明业务原因']}
    out=ROOT/'reports/weekly';out.mkdir(exist_ok=True)
    stem=f'{start.date()}_{end.date()}'
    (out/f'{stem}_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    keys=[f'{period}.{key}' for period,vals in metrics.items() for key in vals]
    prompt='''你是经营分析助手。只依据下列证据生成JSON：{"bullets":[{"metric_keys":["current.sales","previous.sales"],"comment":"不含数字的解释"}]}。只能引用允许的指标键，comment不得包含数字，不宣称因果或真实收益；明确是模拟项目和临时口径。可提出需要核查的方向。数值由程序渲染。\n允许键：'''+json.dumps(keys,ensure_ascii=False)+'\n证据：'+json.dumps(evidence,ensure_ascii=False,indent=2)
    (out/f'{stem}_ai_prompt.txt').write_text(prompt,encoding='utf-8')
    rows=['# 自动化经营周报\n','**基于模拟数据的业务分析项目。**\n',f'区间：{start.date()}—{end.date()}；比较前7天。\n','临时经营贡献口径；广告仅已记录费用，非财务净利润。\n','|指标|本周|前周|变化|','|---|---:|---:|---:|']
    for key in ['sales','units','orders','gross_profit','refunds','recorded_ads','contribution','missing_ad_spend','ad_record_count']:
        cur,pre=metrics['current'][key],metrics['previous'][key]
        rows.append(f'|{key}|{cur:,.2f}|{pre:,.2f}|{cur-pre:,.2f}|')
    validation={'ai_used':False,'status':'未调用外部模型；已生成提示词与证据包'}
    if ai_draft:
        draft=json.loads(Path(ai_draft).read_text(encoding='utf-8'))
        if set(draft)!={'bullets'} or not isinstance(draft['bullets'],list):raise ValueError('AI草稿JSON结构错误')
        rows.append('\n## AI辅助草稿（通过结构与指标引用核验，业务解释仍需人工复核）')
        for b in draft['bullets']:
            if set(b)!={'metric_keys','comment'} or not b['metric_keys'] or any(k not in keys for k in b['metric_keys']):raise ValueError('AI引用了未提供指标')
            if not isinstance(b['comment'],str) or any(x.isdigit() for x in b['comment']):raise ValueError('AI解释含数字，必须用证据键引用')
            rendered=[]
            for k in b['metric_keys']:
                period,metric=k.split('.');rendered.append(f'{k}={metrics[period][metric]:,.2f}')
            rows.append('- '+b['comment']+'（'+ '；'.join(rendered)+'）')
        draft_path=Path(ai_draft).resolve()
        try:
            public_source=draft_path.relative_to(ROOT).as_posix()
        except ValueError:
            public_source=draft_path.name
        validation={'ai_used':True,'source':public_source,'status':'通过指标白名单、数字渲染和JSON结构核验；因果与建议由人工复核'}
    rows.append('\n缺失费用和疑似漏报必须对账；不将未发生的建议写为实施成果。')
    (out/f'{stem}.md').write_text('\n'.join(rows),encoding='utf-8')
    (out/f'{stem}_ai_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start',default='2026-09-21');p.add_argument('--end',default='2026-09-27');p.add_argument('--ai-draft',type=Path)
    args=p.parse_args();generate(args.start,args.end,args.ai_draft);print('Weekly report saved.')
