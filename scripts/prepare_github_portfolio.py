"""只整理V1展示，不改变计算口径。输入已验收汇总，输出README和真实数据PNG。"""
from pathlib import Path
import shutil
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT=Path(__file__).resolve().parents[1]
T=ROOT/'reports/tables'
IMAGES=ROOT/'assets/images'


def setup_font():
    """使用本机中文字体，仅渲染图像，不打包或分发字体文件。"""
    for name in ['Microsoft YaHei','Noto Sans CJK SC','Source Han Sans SC','SimHei','PingFang SC']:
        try:
            font_manager.findfont(name,fallback_to_default=False)
            plt.rcParams['font.sans-serif']=[name]
            plt.rcParams['axes.unicode_minus']=False
            return True
        except ValueError:pass
    return False


def finish(fig,name):
    fig.savefig(IMAGES/name,dpi=180,bbox_inches='tight',facecolor='white')
    plt.close(fig)


def build_assets():
    IMAGES.mkdir(parents=True,exist_ok=True)
    chinese=setup_font()
    sales=pd.read_csv(T/'monthly_sales.csv');profit=pd.read_csv(T/'monthly_profit.csv')
    fig,ax=plt.subplots(1,2,figsize=(12,4.9),layout='constrained')
    for a,vals,title in [(ax[0],sales.sales,'有效订单销售额 / USD'),(ax[1],profit.contribution,'临时经营贡献利润 / USD')]:
        a.bar(['2026-08','2026-09'],vals,color=['#64748b','#2563eb'],width=.58)
        a.set_title(title if chinese else ('Effective sales / USD' if a is ax[0] else 'Provisional contribution / USD'))
        a.set_ylim(0,max(vals)*1.22);a.grid(axis='y',alpha=.18);a.set_axisbelow(True)
        for x,v in zip(range(2),vals):a.text(x,v+max(vals)*.04,f'{v:,.2f}',ha='center',fontsize=11)
    fig.suptitle('销售额下降18.92%；贡献利润下降40.27%' if chinese else 'Sales -18.92%; provisional contribution -40.27%',fontsize=17)
    fig.supxlabel('模拟数据；销售与利润样本范围不同；不是财务净利润' if chinese else 'Synthetic data; sales and profit scopes differ; not net profit',fontsize=10)
    finish(fig,'monthly_sales_profit.png')

    platform=pd.read_csv(T/'platform_changes.csv').sort_values('contribution_change')
    fig,ax=plt.subplots(figsize=(10,4.8),layout='constrained')
    bars=ax.barh(platform.platform_standard,platform.contribution_change,color='#dc2626')
    ax.invert_yaxis();ax.set_xlim(platform.contribution_change.min()*1.22,0)
    ax.bar_label(bars,labels=[f'{v:,.2f}' for v in platform.contribution_change],padding=6,fontsize=11)
    ax.set_title('平台经营贡献利润变化：9月减8月 / USD' if chinese else 'Contribution change by platform: Sep minus Aug / USD',fontsize=16)
    ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
    fig.supxlabel('TK是最大平台下降来源；不同维度的贡献不能重复相加' if chinese else 'TK is the largest platform decline; do not sum overlapping dimensions',fontsize=10)
    finish(fig,'platform_contribution_change.png')

    bridge=pd.read_csv(T/'profit_bridge.csv')
    start=profit.loc[profit.month.eq('2026-08'),'contribution'].iloc[0]
    end=profit.loc[profit.month.eq('2026-09'),'contribution'].iloc[0]
    changes=-bridge.profit_decline_impact.to_numpy();running=start
    fig,ax=plt.subplots(figsize=(13,5.5),layout='constrained')
    ax.bar(0,start,color='#64748b')
    ax.text(0,start+1000,f'{start:,.2f}',ha='center',fontsize=10)
    for j,change in enumerate(changes,1):
        new=running+change;ax.bar(j,abs(change),bottom=min(running,new),color='#059669' if change>0 else '#dc2626')
        ax.plot([j-1+.4,j-.4],[running,running],color='#94a3b8',linestyle='--',linewidth=1)
        ax.text(j,max(running,new)+1100,f'{change:+,.2f}',ha='center',fontsize=9)
        running=new
    assert abs(running-end)<1e-6
    ax.bar(7,end,color='#2563eb');ax.text(7,end+1000,f'{end:,.2f}',ha='center',fontsize=10)
    labels=['8月贡献利润',*bridge.factor,'9月贡献利润'] if chinese else ['Aug contribution','Sales','Goods cost','Shipping','Commission','Refunds','Ads','Sep contribution']
    ax.set_xticks(range(8),labels,rotation=18,ha='right');ax.set_ylim(0,start*1.25)
    ax.set_title('经营贡献利润变化桥梁 / USD' if chinese else 'Operating contribution bridge / USD',fontsize=17)
    ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.supxlabel('会计变化精确对账：减少20,532.13 USD；不叠加缺货、折扣或CPC情景' if chinese else 'Exact accounting bridge: -20,532.13 USD; scenarios are not added again',fontsize=10)
    finish(fig,'profit_bridge.png')

    sku=pd.read_csv(T/'sku_changes.csv').sort_values('contribution_change').head(6)
    fig,ax=plt.subplots(figsize=(10,5.3),layout='constrained')
    bars=ax.barh(sku.sku_standard,sku.contribution_change,color='#dc2626');ax.invert_yaxis()
    ax.set_xlim(sku.contribution_change.min()*1.23,0);ax.bar_label(bars,labels=[f'{v:,.2f}' for v in sku.contribution_change],padding=6)
    ax.set_title('主要SKU经营贡献利润变化 / USD' if chinese else 'Top SKU contribution changes / USD',fontsize=16)
    ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
    finish(fig,'sku_contribution_change.png')

    ad=pd.read_csv(T/'advertising_efficiency.csv');cohort=pd.read_csv(T/'refund_cohorts_12d.csv');s4=cohort.loc[cohort.sku_standard.eq('SKU004')]
    fig,ax=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    for name,g in ad.groupby('platform_standard'):
        ax[0].plot(g.month,g.roas,marker='o',linewidth=2,label=name)
    ax[0].set_title('广告归因ROAS（已知花费样本）' if chinese else 'Attributed ROAS (known-spend sample)');ax[0].legend(fontsize=9);ax[0].grid(alpha=.15)
    bars=ax[1].bar(s4.month,s4.refund_rate_pct,color=['#64748b','#dc2626'],width=.58)
    ax[1].bar_label(bars,labels=[f'{v:.2f}%' for v in s4.refund_rate_pct],padding=5)
    ax[1].set_ylim(0,22);ax[1].set_ylabel('%');ax[1].set_title('SKU004下单后12天退款订单率' if chinese else 'SKU004 refunded orders within 12 days')
    fig.supxlabel('ROAS不是利润率；退款队列按下单月、统一观察窗口' if chinese else 'ROAS is not profit margin; refunds use order-month cohorts',fontsize=10)
    finish(fig,'ads_refund_metrics.png')
    # 浏览器截图由真实离线HTML渲染产生；不伪造在线站点。
    preview=ROOT/'dashboard/preview.png'
    if preview.exists():shutil.copy2(preview,IMAGES/'dashboard_preview.png')
    quality_preview=ROOT/'reports/quality_log_preview_1.png'
    if quality_preview.exists():shutil.copy2(quality_preview,IMAGES/'data_quality_overview.png')
    (ROOT/'reports/portfolio_visuals.json').write_text(json.dumps({'source':'reports/tables/*.csv; verified browser screenshot','chinese_font_available':chinese,'images':[p.name for p in IMAGES.glob('*.png')],'not_ai_generated':True},ensure_ascii=False,indent=2),encoding='utf-8')


def render_readme():
    """静态文档模板与已验收数值匹配；重跑构建不会恢复旧README。"""
    source=ROOT/'docs/readme_template.md'
    text=source.read_text(encoding='utf-8')
    (ROOT/'README.md').write_text(text,encoding='utf-8')


if __name__=='__main__':
    build_assets();render_readme()
