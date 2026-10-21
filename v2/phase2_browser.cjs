// Real-browser acceptance against an explicitly isolated local database.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const root=path.dirname(__dirname);
const output=process.env.V2_EVIDENCE_DIR || path.join(__dirname,'runtime','phase2-browser');fs.mkdirSync(output,{recursive:true});
const data=process.env.V2_PHASE2_DATA_DIR;assert(data,'isolated data directory is required');
const url=process.env.V2_BASE_URL || 'http://127.0.0.1:8512';
const phase=process.argv[2] || 'initial';
function state(){
 const py="import json,sys; from v2.service import Store; from v2.metrics import MetricCenter; from v2.alerts import safe_json; s=Store(sys.argv[1]); print(safe_json({'metrics':MetricCenter(s).calculate('demo',as_of='2026-10-10'),'alerts':s.query('SELECT * FROM alerts ORDER BY id').to_dict('records'),'rules':s.query('SELECT * FROM alert_rules ORDER BY id').to_dict('records'),'revisions':s.query('SELECT * FROM record_revisions ORDER BY id').to_dict('records'),'actions':s.query('SELECT * FROM alert_actions ORDER BY id').to_dict('records')}))";
 return JSON.parse(execFileSync((process.env.V2_PYTHON || path.join(__dirname,'.venv','Scripts','python.exe')),['-X','utf8','-c',py,data],{cwd:root,encoding:'utf8'}));
}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1700,height:1400}});
 const errors=[];page.on('pageerror',error=>errors.push(String(error)));
 const checks=[];
 async function nav(name){await page.getByText(name,{exact:true}).click();await page.waitForTimeout(900);}
 async function select(label,choice){
  const combo=page.getByRole('combobox',{name:label,exact:true});
  await combo.focus();await combo.press('ArrowDown');
  await page.getByRole('option',{name:choice,exact:true}).click();await page.waitForTimeout(900);
 }
 async function metric(index,amount){
  const loc=page.locator('[data-testid="stMetricValue"]').nth(index);
  await loc.filter({hasText:amount}).waitFor({timeout:60000});assert.equal((await loc.innerText()).trim(),amount);
 }
 async function shot(name){
  await page.getByRole('heading',{name:'跨境电商智能经营监控与自动化预警',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,name),fullPage:true,animations:'disabled'});
 }
 try{
  await page.goto(url);
  await page.getByRole('tab',{name:'批次与日志',exact:true}).waitFor({timeout:60000});
  if(phase==='restart'){
   const baseline=JSON.parse(fs.readFileSync(path.join(output,'browser-initial.json'),'utf8'));
   assert.deepEqual(state(),baseline.final_state);
   await nav('经营分析');await metric(0,'1384.00 USD');
   await nav('智能预警');
   assert.equal(await page.locator('[data-testid="stException"]').count(),0);
   checks.push('应用实际进程重启后：修订、规则版本、预警处理和全部指标持久化一致');
   await shot('07-after-restart.png');
   fs.writeFileSync(path.join(output,'browser-restart.json'),JSON.stringify({passed:true,url,data,checks},null,2));
   console.log(JSON.stringify({passed:true,checks}));return;
  }
  await page.getByRole('tab',{name:'批次与日志',exact:true}).click();
  await page.getByRole('button',{name:'导入14天第二阶段模拟数据',exact:true}).click();
  await page.getByText('导入完成：新增 123 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
  await metric(1,'1364.00 USD');
  const initial=state();assert.equal(initial.metrics.orders,71);
  await page.getByRole('tab',{name:'批次与日志',exact:true}).click();
  await page.getByRole('button',{name:'导入14天第二阶段模拟数据',exact:true}).click();
  await page.getByText('识别到重复上传：新增 0 条记录，订单及金额保持不变。',{exact:true}).waitFor();
  assert.deepEqual(state().metrics,initial.metrics);
  checks.push('真实UI导入14天模拟数据、重复导入：全部指标不变');
  await nav('经营分析');await metric(0,'1364.00 USD');await metric(9,'1344.00 USD');
  await shot('01-dashboard.png');
  await select('监控SKU','SKU001');await metric(0,'924.00 USD');
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出筛选后经营指标与血缘 JSON',exact:true}).click()]);
  const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.equal(exported.sales,'924');assert(exported.orders_detail.every(r=>r.sku==='SKU001'));
  assert.equal(exported.orders_detail.reduce((sum,r)=>sum+Number(r.sales),0),924);
  await shot('02-filtered-sku.png');checks.push('SKU筛选同时作用于指标、明细、趋势及JSON导出，销售924逐笔对账');
  await select('国家/地区（广告不分摊）','US');await metric(3,'数据不足');
  await select('国家/地区（广告不分摊）','全部');
  await select('监控SKU','全部');
  await nav('智能预警');
  await page.getByRole('button',{name:'运行规则检测',exact:true}).click();
  await page.getByText(/检测完成：触发/).waitFor({timeout:60000});
  const detected=state();assert(detected.alerts.length>0);
  await page.getByRole('button',{name:'运行规则检测',exact:true}).click();
  await page.getByText(/新增 0 条待办/).waitFor({timeout:60000});
  assert.equal(state().alerts.length,detected.alerts.length);
  await select('经营预警处理结论','已解决');
  await page.getByRole('textbox',{name:'经营预警处理说明（必填）',exact:true}).fill('已核对模拟售后凭证，本周期已处理。');
  await page.getByRole('button',{name:'保存预警处理',exact:true}).click();
  await page.getByText('预警处理已保存，状态日志已追加。',{exact:true}).waitFor();
  assert.equal(state().actions.length,1);
  await shot('03-alert-workbench.png');checks.push('规则检测重复运行无重复待办；已解决状态与说明审计留存');
  await nav('规则配置');
  await page.getByRole('spinbutton',{name:'规则阈值（比例用小数）',exact:true}).fill('50');
  await page.getByRole('textbox',{name:'规则修改说明（必填）',exact:true}).fill('模拟场景调整安全库存；不作为行业阈值。');
  await page.getByRole('button',{name:'保存规则版本',exact:true}).click();
  await page.getByText('规则新版本已保存，历史快照保留。',{exact:true}).waitFor();
  const configured=state();assert.equal(configured.rules[0].version,2);assert.equal(configured.rules[0].threshold,50);
  assert(configured.alerts.filter(r=>r.rule_id===configured.rules[0].id).every(r=>r.threshold===40));
  await shot('04-rule-config.png');checks.push('修改规则阈值保留旧预警40阈值快照，新规则版本2阈值50');
  await nav('数据修订');
  await page.getByRole('combobox',{name:'修订原始记录',exact:true}).focus();
  await page.getByRole('combobox',{name:'修订原始记录',exact:true}).press('ArrowDown');
  await page.getByRole('combobox',{name:'修订原始记录',exact:true}).fill('SYNTH-BAD');
  await page.getByRole('option').filter({hasText:'SYNTH-BAD'}).click();await page.waitForTimeout(900);
  await select('允许修订字段','unit_price');
  await page.getByRole('textbox',{name:'建议新值（文本，空值用勾选）',exact:true}).fill('20');
  await page.getByRole('textbox',{name:'修订原因（必填）',exact:true}).fill('模拟单价误录负数，依据凭证修订。');
  await page.getByRole('textbox',{name:'证据引用（凭证编号或本地文件路径，必填）',exact:true}).fill('Synthetic-平台凭证-001');
  await page.getByRole('button',{name:'提交修订申请',exact:true}).click();
  await page.getByText(/已申请，审批前指标不变/).waitFor();
  const pending=state();assert.equal(pending.revisions[0].status,'待审核');assert.deepEqual(pending.metrics,initial.metrics);
  await shot('05-revision-pending.png');
  await page.getByRole('textbox',{name:'修订审核说明（必填）',exact:true}).fill('已复核模拟凭证，批准新有效版本，原值留存。');
  await page.getByRole('button',{name:'保存修订审批',exact:true}).click();
  await page.getByText(/修订审批已保存/).waitFor({timeout:60000});
  const approved=state();assert.equal(approved.revisions[0].status,'已批准');assert.equal(approved.metrics.sales,'1384');
  assert.equal(approved.metrics.orders,72);
  assert.equal(approved.metrics.orders_detail.filter(r=>r.order_id==='SYNTH-BAD').length,1);
  await shot('06-revision-approved.png');checks.push('修订未审批时指标不变，批准后新增20收入且原始记录只参与一个有效版本');
  await nav('经营分析');await metric(0,'1384.00 USD');
  await page.reload();await page.getByRole('tab',{name:'批次与日志',exact:true}).waitFor();
  await nav('经营分析');await metric(0,'1384.00 USD');
  assert.equal(await page.locator('[data-testid="stException"]').count(),0);
  const final=state();assert.deepEqual(final,approved);
  checks.push('浏览器刷新后修订、规则配置、预警审核及指标保持一致');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'browser-initial.json'),JSON.stringify({passed:true,url,data,checks,initial_metrics:initial.metrics,final_state:final,errors},null,2));
  console.log(JSON.stringify({passed:true,checks},null,2));
 }catch(error){
  console.error('Original verification error:',error);
  await shot('failure.png').catch(()=>{});
  const body=await page.locator('body').innerText({timeout:2000}).catch(()=>'page unavailable');
  fs.writeFileSync(path.join(output,'failure.txt'),String(error)+'\n'+body);throw error;
 }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
