// C1 acceptance against an explicit isolated Synthetic database and local server.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const reportMode=process.env.V2_DAILY_REPORT_ACCEPTANCE==='1';
const data=process.env.V2_DAILY_DATA_DIR, url=process.env.V2_BASE_URL, python=process.env.V2_PYTHON;
assert(data && url && python,'Explicit isolated data directory, server and Python are required');
const output=path.join(__dirname,'runtime',reportMode?'v21-daily-c2':'v21-daily-c1','browser');
fs.mkdirSync(output,{recursive:true});
function read(day='2026-09-14',horizon='2026-10-21'){
 const code=`import sys
from v2.service import Store
from v2.daily_report import build_daily_report,KPIS
from v2.daily_report_ui import formatted
from v2.daily_report_export import public_view
from v2.alerts import safe_json
s=Store(sys.argv[1]);r=build_daily_report(s,'demo',sys.argv[2],sys.argv[3])
v=public_view(r,'模拟演示');v.pop('generated_at')
tables=('records','anomalies','reviews','record_revisions','revision_reviews','alerts','alert_detections','alert_actions','alert_rules','alert_rule_versions','operation_logs')
print(safe_json({'export':v,'values':{label:formatted(key,r['current'][key],r['states'][key]['state']) for key,label,_ in KPIS},'comparisons':[v['text'] for v in r['comparisons'].values()],'database':{t:s.query('SELECT * FROM '+t+' ORDER BY rowid').to_dict('records') for t in tables}}))`;
 return JSON.parse(execFileSync(python,['-B','-X','utf8','-c',code,data,day,horizon],{cwd:path.dirname(__dirname),encoding:'utf8'}));
}
function seedHistory(){
 const code=`import sys
from v2.service import Store
from v2.alerts import AlertEngine
s=Store(sys.argv[1]);e=AlertEngine(s)
e.run('demo',as_of='2026-10-21');e.run('demo',as_of='2026-10-21')
r=next(r for r in e.rules('demo') if r['kind']=='stock_low')
e.configure('demo',r['id'],r['version'],'Synthetic-test','历史版本验收',threshold=45)
e.run('demo',as_of='2026-10-21')
a=s.query('SELECT * FROM alerts ORDER BY id').iloc[0]
e.action('demo',int(a.id),'已解决','Synthetic已处理','test',int(a.state_version))
print('Synthetic historical detections and versions ready')`;
 execFileSync(python,['-B','-X','utf8','-c',code,data],{cwd:path.dirname(__dirname),encoding:'utf8'});
}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 async function idle(){await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:60000});await page.waitForTimeout(700);}
 async function nav(name){await page.getByText(name,{exact:true}).click();await idle();}
 async function metric(label,value){
  const box=page.locator('[data-testid="stMetric"]').filter({has:page.getByText(label,{exact:true})});
  assert.equal((await box.locator('[data-testid="stMetricValue"]').innerText()).trim(),value);
 }
 async function comparisons(texts){
  for(const text of new Set(texts)){
   const matches=page.getByText(text,{exact:true});await matches.first().waitFor();
   assert.equal(await matches.count(),texts.filter(value=>value===text).length);
  }
 }
 async function setDate(label,value){
  const widget=page.locator('[data-testid="stDateInput"]').filter({has:page.getByText(label,{exact:true})});
  for(const [part,target] of ['year','month','day'].map((part,index)=>[part,Number(value.split('-')[index])])){
   const segment=widget.locator(`[role="spinbutton"][data-type="${part}"]`);
   await segment.click();
   for(let attempt=0;Number(await segment.getAttribute('aria-valuenow'))!==target;attempt++){
    assert(attempt<40,'Date segment failed to converge');
    await segment.press(Number(await segment.getAttribute('aria-valuenow'))<target?'ArrowUp':'ArrowDown');
   }
  }
  await page.getByRole('heading',{name:'经营日报 · USD',exact:true}).click();await idle();
  const marker=label==='经营日期 D'?`报告经营日：${value}`:`两日共同退款观察截止日：${value}`;
  await page.getByText(marker,{exact:false}).waitFor({timeout:30000});
 }
 async function shot(file,heading='经营日报 · USD'){
  await page.getByRole('heading',{name:heading,exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,file),animations:'disabled'});
 }
 try{
  await page.goto(url);await idle();
  await nav('业务数据');
  await nav('经营日报');
  await metric('折后销售额','尚未导入数据');
  await shot('00-empty.png');
  await nav('模拟演示');
  await nav('数据运营工作台');
  await page.getByRole('tab',{name:'批次与日志',exact:true}).click();
  await page.getByRole('button',{name:'导入14天第二阶段模拟数据',exact:true}).click();await idle();
  if(reportMode)seedHistory();
  const before=read();
  await nav('经营日报');
  for(const [label,value] of Object.entries(before.values))await metric(label,value);
  await comparisons(before.comparisons);
  assert.equal(await page.locator('[data-testid="stMetric"]').count(),6);
  await shot('01-default.png');
  await shot('02-limits.png','样本与数据限制');
  if(reportMode){
   await page.getByRole('heading',{name:'观测期截至D日的历史预警证据',exact:true}).scrollIntoViewIfNeeded();
   const entries=before.export.history.entries;
   assert(entries.length>0 && entries.some(e=>e.status==='已解决'));
   assert(entries.some(e=>e.version===1) && entries.some(e=>e.version===2));
   for(const entry of entries)await page.getByText(`证据 #${entry.detection_id} · ${entry.name} · ${entry.object}`,{exact:true}).waitFor();
   await page.screenshot({path:path.join(output,'09-history.png')});
   await page.getByRole('heading',{name:'运营关注与核查建议',exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(output,'10-guidance.png')});
   const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'下载 HTML 日报',exact:true}).click()]);
   const file=path.join(output,'sample-daily-report.html');await download.saveAs(file);
   const html=fs.readFileSync(file,'utf8');assert(!html.includes(data));
   const context=await browser.newContext({offline:true,viewport:{width:1366,height:1000}});
   const offline=await context.newPage();
   await offline.goto(pathToFileURL(file).href);
   assert.equal(await offline.locator('script,link,img,iframe').count(),0);
   const rows=offline.locator('#daily-kpis tbody tr');
   assert.equal(await rows.count(),6);
   for(let i=0;i<6;i++)assert.deepEqual(await rows.nth(i).locator('td').allTextContents(),['指标','D日','D−1日','比较','D日说明','D−1日说明'].map(key=>before.export.kpis[i][key]));
   assert.equal(await offline.locator('details').count(),entries.length);
   for(const item of before.export.guidance)await offline.getByRole('heading',{name:item.title,exact:true}).first().waitFor();
   await offline.screenshot({path:path.join(output,'11-offline-report.png')});
   await offline.locator('details').first().locator('summary').click();
   await offline.locator('details').first().scrollIntoViewIfNeeded();
   await offline.screenshot({path:path.join(output,'12-offline-evidence.png')});
   await context.close();
   assert.deepEqual(read(),before,'Download and offline opening must preserve all stored workflows');
  }

  await setDate('退款观察截止日 H','2026-09-14');
  await metric('12天退款订单率','数据不足');
  await page.getByText(/D日：订单队列尚未观察满12天/).waitFor();
  await shot('03-immature.png');
  await setDate('经营日期 D','2026-09-08');
  await setDate('退款观察截止日 H','2026-10-21');
  const changed=read('2026-09-08');
  for(const [label,value] of Object.entries(changed.values))await metric(label,value);
  await comparisons(changed.comparisons);
  await shot('04-comparison.png');
  await setDate('经营日期 D','2026-09-01');
  await page.getByText(/不可比较：D日.*D−1日当前范围无匹配数据/).first().waitFor();
  await shot('05-missing-previous.png');
  if(reportMode)await page.getByText('暂无截至该日的已保存触发证据，不能据此认定无异常。',{exact:true}).waitFor();
  await setDate('经营日期 D','2026-08-20');
  await metric('折后销售额','当前范围无匹配数据');
  await shot('06-no-match.png');
  await setDate('经营日期 D','2026-09-14');
  await page.setViewportSize({width:480,height:1100});await idle();
  await shot('07-mobile.png','当日表现与前一日比较');
  const dimensions=await page.locator('.st-key-daily_kpis [data-testid="stMetricValue"]').evaluateAll(nodes=>nodes.map(n=>({width:n.clientWidth,scroll:n.scrollWidth,left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right})));
  assert(dimensions.every(d=>d.width>0 && d.scroll<=d.width+2 && d.left>=0 && d.right<=480),'KPI values must fit the mobile viewport');
  await page.getByText(before.comparisons[5],{exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'08-mobile-comparison.png')});
  await page.setViewportSize({width:1366,height:1000});await idle();
  await nav('业务数据');await metric('折后销售额','尚未导入数据');
  await nav('模拟演示');await metric('折后销售额',before.values['折后销售额']);
  await nav('经营分析');
  await page.getByRole('heading',{name:'经营分析 · USD',exact:true}).waitFor();
  await page.locator('[data-testid="stMetric"]').nth(10).waitFor();
  assert.equal(await page.locator('[data-testid="stMetric"]').count(),11);
  await nav('数据运营工作台');
  await page.getByRole('tab',{name:'质量检查',exact:true}).click();
  await page.getByRole('heading',{name:'质量检查结果与隔离证据',exact:true}).waitFor();
  await nav('经营日报');
  assert.equal(await page.locator('[data-testid="stException"]').count(),0);
  assert.deepEqual(errors,[]);
  const after=read();assert.deepEqual(after,before,'Daily viewing/navigation must not change metrics or stored workflows');
  fs.writeFileSync(path.join(output,'state-before-after.json'),JSON.stringify({before,after},null,2));
  const result={passed:true,checks:['日报入口','六项指标与统一服务一致','D与D−1比较','日期与H筛选','退款未成熟','缺少前日与无匹配','空库与空间隔离','1366px与480px可读','既有经营分析与质量导航','审核/修订/预警/日志与指标只读不变'],errors};
  if(reportMode)result.checks.push('历史证据窗口与版本','已解决不冒充历史状态','确定性核查建议','HTML下载与六项KPI及比较逐项对账','断网本地HTML打开','导出前后数据库及指标一致');
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }catch(error){await page.screenshot({path:path.join(output,'failure.png')});fs.writeFileSync(path.join(output,'failure.txt'),String(error)+'\n'+await page.locator('body').innerText());throw error;}
 finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
