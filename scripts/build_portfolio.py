"""生成补充Notebook、静态图、README；保留学习者原Notebook不改写。"""
from pathlib import Path
import nbformat
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT=Path(__file__).resolve().parents[1]
T=ROOT/'reports/tables'


def notebook(name,sections):
    n=nbformat.v4.new_notebook()
    n.metadata['kernelspec']={'display_name':'Python 3','language':'python','name':'python3'}
    n.metadata['language_info']={'name':'python','version':'3.11'}
    n.cells=[]
    for text,code in sections:
        n.cells.append(nbformat.v4.new_markdown_cell(text))
        if code:n.cells.append(nbformat.v4.new_code_cell(code))
    nbformat.write(n,ROOT/'notebooks'/name)


def main():
    setup='''from pathlib import Path
import sys
import pandas as pd
ROOT = Path.cwd()
if not (ROOT / 'data/raw').exists():
    ROOT = ROOT.parent
assert (ROOT / 'data/raw/orders.csv').exists()
sys.path.insert(0, str(ROOT / 'scripts'))
pd.set_option('display.max_columns', 20)
'''
    notebook('01_data_cleaning_v1.ipynb',[
        ('# 六表质检与清洗V1\n**基于模拟数据的业务分析项目。** 原始学习Notebook保留于01_data_quality.ipynb。本Notebook是整理后的复现入口。\n输入六表raw，输出clean、quarantine和质量证据，不更改原始文件。',setup),
        ('## 运行确定性流水线\n为什么：避免手动单元格执行顺序造成口径漂移。`run()`输入固定六表，执行标准化、去重、异常检查、SQL与分析输出；返回汇总字典。raw哈希不一致则停止。详细函数和处理规则见脚本及docs/methodology.md。','from run_project_v1 import run\nsummary = run()'),
        ('## 粒度与重复复核\n`read_csv()`输入派生统计文件并输出DataFrame。订单单SKU粒度、全字段重复去重；退款不能按order_id去重，广告不能按日期×SKU去重。','profiles = pd.read_csv(ROOT / "reports/tables/table_profiles.csv")\nprofiles'),
        ('## 数据质量证据\n`groupby().size()`对问题类型计数；一个记录可能有多项问题，因此问题条目不等于坏数据行数。只标记，不据此自动填补未知值。','issues = pd.read_csv(ROOT / "data/processed/quality_issues.csv")\nissues.groupby(["table", "issue"]).size().rename("flagged_rows").reset_index()'),
        ('## 检查清洗订单及隔离样本\n输入clean订单，输出键、缺失与隔离记录数。clean含待核实记录，profit_orders才是临时利润样本。编号按文本读取。','orders = pd.read_csv(ROOT / "data/processed/orders_clean.csv", dtype={"order_id":str,"customer_id":str})\nassert len(orders) == 9952 and orders.order_id.is_unique\nprint("客户编号缺失", orders.customer_id.isna().sum())\nprint("待核实订单", orders.needs_review.sum())\npd.read_csv(ROOT / "data/processed/orders_quarantine.csv")[["order_id","quantity","unit_price","order_status"]]'),
        ('## 退款与广告待核实项\n退款只退商品实收；超额退款不封顶。广告缺失费用不填0，疑似漏报网格需要业务确认。','display(pd.read_csv(ROOT / "data/processed/refunds_quarantine.csv")[["refund_id","order_id","refund_amount","order_sales"]])\ndisplay(pd.read_csv(ROOT / "data/processed/ads_missing_expected_rows.csv"))'),
        ('## 清洗成果与限制\n六张clean CSV保留原始字段和新增标准字段；完整检查见reports/data_quality_report.md，未核实源系统错误仍保留。没有猜测修正异常价格、数量或未知采购成本。',None)
    ])
    notebook('02_business_analysis_v1.ipynb',[
        ('# 9月经营分析V1\n**基于模拟数据的业务分析项目。** 先运行01_data_cleaning_v1.ipynb或scripts/run_project_v1.py生成成果。本Notebook逐段展示收入→利润→维度→证据→建议。',setup+'\nT = ROOT / "reports/tables"'),
        ('## 销售额口径敏感性\n读取不同样本的月度销售额。raw含重复且存在异常，不能直接当最终收入。临时有效销售含未知成本商品；利润样本额外排除未知成本。','sensitivity = pd.read_csv(T / "sales_sensitivity.csv")\nsensitivity'),
        ('## 月度利润账\n`pct_change()`输入按月排序指标，输出环比。经营贡献利润扣商品、履约、佣金、批准确认退款及已记录广告；不含工资税费。','monthly = pd.read_csv(T / "monthly_profit.csv").set_index("month")\ndisplay(monthly.round(2))\nmonthly[["sales","gross_profit","contribution"]].pct_change().mul(100).round(2)'),
        ('## SQL独立复核\nSQLite连接派生数据库，SQL用CTE先聚合再关联费用避免多对多。输出与Pandas逐月金额核对，不依赖Notebook隐藏状态。','import sqlite3\nwith sqlite3.connect(ROOT / "data/processed/business_analysis.sqlite") as conn:\n    sql = (ROOT / "sql/01_monthly_profit.sql").read_text(encoding="utf-8")\n    sql_result = pd.read_sql_query(sql, conn).set_index("month")\nassert (sql_result.contribution - monthly.contribution).abs().max() < 0.000001\nsql_result.round(2)'),
        ('## 精确对账桥梁与毛利结构\n桥梁正数推动利润下降；毛利分解正数推动毛利增长。SKU内平均标价变化同时受国家渠道结构影响，不等同实际调价。','display(pd.read_csv(T / "profit_bridge.csv"))\ndisplay(pd.read_csv(T / "gross_profit_decomposition.csv"))'),
        ('## 平台和SKU定位\n两个维度解释同一利润，不能相加。退款按原订单归维度，按确认日期归期间。','display(pd.read_csv(T / "platform_changes.csv"))\ndisplay(pd.read_csv(T / "sku_changes.csv"))'),
        ('## 库存、优惠、广告及售后证据\n情景估算固定指定规模并假设参考期可比，不是独立因果贡献；ROAS用广告同一已知花费样本。退款按下单月统一12天窗口。','display(pd.read_csv(T / "scenarios.csv"))\ndisplay(pd.read_csv(T / "advertising_efficiency.csv"))\ncohorts = pd.read_csv(T / "refund_cohorts_12d.csv")\ncohorts.loc[cohorts.sku_standard == "SKU004"]'),
        ('## 国家与品类结构\n国家只比较销售和毛利，不随意分摊广告来制造国家净利润。','display(pd.read_csv(T / "country_changes.csv"))\ndisplay(pd.read_csv(T / "category_mix.csv"))'),
        ('## 图表与报告\n输入已核验汇总，显示静态图；完整离线交互图在dashboard/index.html。行动建议未实施，不声称实际收益。','from IPython.display import Image, display\ndisplay(Image(filename=str(ROOT / "dashboard/overview.png")))'),
        ('## 自动化与AI\n运行weekly_report.py生成7天经营周报、证据包和AI提示词。AI草稿仅引用白名单指标，程序渲染数字并验证；业务因果仍人工核查。\n完整报告：reports/september_business_report.md；口径：docs/methodology.md；求职材料：docs/resume_project_description.md。',None)
    ])
    # 标准绘图，优先系统中文字体；没找到时图表用英文保证可阅读。
    for name in ['Microsoft YaHei','SimHei','DengXian']:
        try:
            font_manager.findfont(name,fallback_to_default=False)
            plt.rcParams['font.sans-serif']=[name];break
        except ValueError:pass
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,2,figsize=(14,9),layout='constrained')
    m=pd.read_csv(T/'monthly_profit.csv');p=pd.read_csv(T/'platform_changes.csv');sku=pd.read_csv(T/'sku_changes.csv');ad=pd.read_csv(T/'advertising_efficiency.csv')
    axes[0,0].bar(m.month,m.contribution,color=['#64748b','#2563eb']);axes[0,0].set_title('Operating contribution (USD, provisional)')
    for x,y in zip(m.month,m.contribution):axes[0,0].text(x,y+700,f'{y:,.2f}',ha='center')
    axes[0,1].barh(p.platform_standard,-p.contribution_change,color='#dc2626');axes[0,1].set_title('Contribution decline by platform (USD)')
    v=sku.sort_values('contribution_change').head(6)
    axes[1,0].barh(v.sku_standard,-v.contribution_change,color='#dc2626');axes[1,0].set_title('Top SKU contribution declines (USD)')
    for platform,g in ad.groupby('platform_standard'):
        axes[1,1].plot(g.month,g.roas,marker='o',label=platform)
    axes[1,1].legend();axes[1,1].set_title('Attributed ROAS: known-spend records')
    for ax in axes.flat:ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('Synthetic business project | September 2026 | Raw data preserved',fontsize=17)
    fig.savefig(ROOT/'dashboard/overview.png',dpi=150);plt.close(fig)
    # README和招聘展示图由单一模板维护，避免重跑恢复旧文档。
    from prepare_github_portfolio import build_assets, render_readme
    build_assets()
    render_readme()


if __name__=='__main__':main()
