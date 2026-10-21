// Quality acceptance: preserve Phase A workflows and optionally verify Phase B reports.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const data=process.env.V2_QUALITY_DATA_DIR, url=process.env.V2_BASE_URL;
assert(data && url,'Explicit isolated data root and URL required');

const reportMode=process.env.V2_QUALITY_REPORT_ACCEPTANCE==='1';
const output=process.env.V2_QUALITY_EVIDENCE_DIR || path.join(__dirname,'runtime',reportMode?'v21-quality-b':'v21-quality-a','browser');
fs.mkdirSync(output,{recursive:true});
function state(){
 const py="import sys; from v2.service import Store; from v2.metrics import MetricCenter; from v2.alerts import safe_json; s=Store(sys.argv[1]); print(safe_json({'metrics':MetricCenter(s).calculate('demo'),'issues':s.anomalies('demo').to_dict('records'),'records':s.query('SELECT * FROM records ORDER BY id').to_dict('records'),'workflow':{t:s.query('SELECT * FROM '+t+' ORDER BY id').to_dict('records') for t in ('reviews','record_revisions','revision_reviews','alerts','alert_detections','alert_actions','operation_logs')}}))";
 return JSON.parse(execFileSync((process.env.V2_PYTHON || path.join(__dirname,'.venv','Scripts','python.exe')),['-X','utf8','-c',py,data],{cwd:path.dirname(__dirname),encoding:'utf8'}));
}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1200}});
 const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
 async function tab(name){
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:60000});
  const target=page.getByRole('tab',{name,exact:true});
  await target.click();
  await page.waitForTimeout(500);
  if(await target.getAttribute('aria-selected')!=='true') await target.click();
 }
 async function metric(label,value){
  const box=page.locator('[data-testid="stMetric"]').filter({has:page.getByText(label,{exact:true})});
  await box.locator('[data-testid="stMetricValue"]').filter({hasText:String(value)}).waitFor({timeout:30000});
  assert.equal((await box.locator('[data-testid="stMetricValue"]').innerText()).trim(),String(value));
 }
 async function select(label,value){
  const combo=page.getByRole('combobox',{name:label,exact:true});
  await combo.focus();await combo.press('ArrowDown');
  await page.getByRole('option',{name:value,exact:true}).click();await page.waitForTimeout(900);
 }
 async function shot(name,heading){
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:60000});
  await page.waitForTimeout(500);
  await page.getByRole('heading',{name:heading,exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,name),animations:'disabled'});
 }
 try{
  await page.goto(url);
  await page.getByText('业务数据',{exact:true}).click();
  await page.waitForTimeout(1200);
  await tab('质量检查');
  await metric('受影响记录数','尚未导入数据');
  await shot('00-empty.png','质量检查结果与隔离证据');
  await page.getByText('模拟演示',{exact:true}).click();
  await page.waitForTimeout(1200);
  await tab('数据导入');
  await page.getByRole('button',{name:'1 · 导入正常数据',exact:true}).click();
  await page.getByText(/导入完成：新增|识别到重复上传/).waitFor();
  await page.getByRole('button',{name:'3 · 导入错误数据',exact:true}).click();
  await page.waitForTimeout(1200);
  const before=state();
  const active=before.issues.filter(r=>r.active===1);
  assert(active.length>0);
  await tab('质量检查');
  await metric('有效异常条数',active.length);
  await metric('受影响记录数',new Set(active.map(r=>r.record_id)).size);
  await shot('01-summary.png','当前质量摘要');
  await shot('02-impact.png','业务影响摘要');
  await select('质量来源批次',active[0].batch_id);
  await metric('有效异常条数',active.filter(r=>r.batch_id===active[0].batch_id).length);
  await select('质量来源批次','全部');
  await select('质量异常分类','主数据与关联');
  const related=active.filter(r=>['unknown_sku','unknown_customer','refund_orphan'].includes(r.code));
  await metric('有效异常条数',related.length);
  await metric('受影响记录数',new Set(related.map(r=>r.record_id)).size);
  await page.getByText('包含已失效异常',{exact:true}).click();
  assert(await page.getByRole('checkbox',{name:'包含已失效异常',exact:true}).isChecked());
  await metric('有效异常条数',related.length);
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出质量检查证据',exact:true}).click()]);
  const csv=fs.readFileSync(await download.path(),'utf8');
  fs.writeFileSync(path.join(output,'filtered-evidence.csv'),csv);
  assert(csv.includes('unknown_sku'));assert(!csv.includes('invalid_price'));
  if(reportMode){
   await page.getByText(/建议下一步：.*数据修订/).waitFor();
   await shot('03a-guidance.png','问题明细与处理引导');
   const [reportDownload]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'下载数据质量报告（HTML）',exact:true}).click()]);
   const html=fs.readFileSync(await reportDownload.path(),'utf8');
   assert(html.includes('unknown_sku') && !html.includes('invalid_price'));
   assert(html.includes('Asia/Shanghai') && html.includes('模拟演示'));
   fs.writeFileSync(path.join(output,'sample-quality-report.html'),html);
   const reportPage=await browser.newPage({viewport:{width:1600,height:1200}});
   await reportPage.goto(pathToFileURL(path.join(output,'sample-quality-report.html')).href);
   assert.equal(await reportPage.locator('script').count(),0);
   assert.equal(await reportPage.locator('h1').innerText(),'数据质量报告 · V2.1');
   const summary=reportPage.locator('table').nth(1);
   const values=await summary.locator('tbody td').allTextContents();
   assert.equal(values[0],String(related.length));
   assert.equal(values[1],String(new Set(related.map(r=>r.record_id)).size));
   await reportPage.screenshot({path:path.join(output,'03b-offline-report.png'),fullPage:true});
   await reportPage.close();
  }
  await shot('03-filter.png','当前质量摘要');
  await select('质量审核状态','确认');
  await metric('有效异常条数',0);
  await page.getByText('当前范围无匹配数据；当前筛选没有有效异常，不表示整个空间没有问题。',{exact:true}).waitFor();
  await select('质量审核状态','全部');
  await page.setViewportSize({width:480,height:1100});
  await shot('04-mobile.png','当前质量摘要');
  assert.deepEqual(state(),before,'Read-only quality viewing must preserve records, metrics and findings');
  // Restore wide viewport so the sidebar is available for workspace isolation check.
  await page.setViewportSize({width:1600,height:1200});
  if(reportMode){
   await tab('异常审核');
   await page.getByRole('heading',{name:'异常审核工作台',exact:true}).waitFor();
   await page.getByText('数据修订',{exact:true}).click();
   const combo=page.getByRole('combobox',{name:'修订原始记录',exact:true});
   await combo.waitFor();await combo.focus();await combo.press('ArrowDown');
   const target=related.find(r=>r.code==='unknown_sku');
   await page.getByRole('option').filter({hasText:'#'+target.record_id+' ·'}).click();
   await page.getByRole('button',{name:'提交修订申请',exact:true}).waitFor();
   assert.deepEqual(state(),before,'Guidance/navigation must not submit reviews or revisions');
   await page.getByText('数据运营工作台',{exact:true}).click();
   await page.waitForTimeout(1200);
  }
  await tab('质量检查');
  await select('质量异常分类','全部');
  if(await page.getByRole('checkbox',{name:'包含已失效异常',exact:true}).isChecked())
   await page.getByText('包含已失效异常',{exact:true}).click();
  const bad=active.find(r=>r.code==='invalid_price');
  assert(bad,'Synthetic fixture must include a hard price error');
  await tab('异常审核');
  let combo=page.getByRole('combobox',{name:'选择异常',exact:true});
  await combo.focus();await combo.press('ArrowDown');
  await page.getByRole('option').filter({hasText:'#'+bad.id+' ·'}).click();
  await select('审核结论','驳回');
  await page.getByRole('textbox',{name:'处理说明（必填）',exact:true}).fill('Synthetic硬规则驳回边界核验');
  await page.getByRole('button',{name:'保存审核',exact:true}).click();
  await page.waitForTimeout(1200);
  const reviewed=state();
  assert.equal(reviewed.issues.find(r=>r.id===bad.id).status,'驳回');
  assert.deepEqual(reviewed.metrics,before.metrics,'Hard error rejection must not release revenue');
  await tab('质量检查');
  await metric('直接阻断记录数',new Set(active.filter(r=>r.scope!=='none').map(r=>r.record_id)).size);
  await shot('05-reviewed.png','当前质量摘要');
  await page.getByText('数据修订',{exact:true}).click();
  combo=page.getByRole('combobox',{name:'修订原始记录',exact:true});
  await combo.focus();await combo.press('ArrowDown');
  await page.getByRole('option').filter({hasText:'#'+bad.record_id+' ·'}).click();
  await select('允许修订字段','unit_price');
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:60000});
  await page.waitForTimeout(1500);
  await page.getByRole('textbox',{name:'建议新值（文本，空值用勾选）',exact:true}).fill('20');
  await page.getByRole('textbox',{name:'修订原因（必填）',exact:true}).fill('Synthetic负单价修订');
  await page.getByRole('textbox',{name:'证据引用（凭证编号或本地文件路径，必填）',exact:true}).fill('Synthetic-PhaseA-001');
  await page.getByRole('textbox',{name:'证据引用（凭证编号或本地文件路径，必填）',exact:true}).press('Tab');
  assert.equal(await page.getByRole('textbox',{name:'建议新值（文本，空值用勾选）',exact:true}).inputValue(),'20');
  await page.getByRole('button',{name:'提交修订申请',exact:true}).click();
  await page.getByText(/已申请，审批前指标不变/).waitFor();
  assert.deepEqual(state().metrics,before.metrics);
  await page.getByRole('textbox',{name:'修订审核说明（必填）',exact:true}).fill('Synthetic凭证复核通过');
  await page.getByRole('button',{name:'保存修订审批',exact:true}).click();
  await page.getByText(/修订审批已保存/).waitFor();
  const approved=state();
  assert.equal(approved.issues.find(r=>r.id===bad.id).active,0);
  assert.deepEqual(approved.records,before.records,'Raw records remain immutable');
  assert.equal(Number(approved.metrics.sales),Number(before.metrics.sales)+35);
  await page.getByText('数据运营工作台',{exact:true}).click();
  await tab('质量检查');
  const remaining=approved.issues.filter(r=>r.active===1);
  await metric('有效异常条数',remaining.length);
  if(!await page.getByRole('checkbox',{name:'包含已失效异常',exact:true}).isChecked())
   await page.getByText('包含已失效异常',{exact:true}).click();
  await metric('有效异常条数',remaining.length);
  // Streamlit canvas tables expose cell text through an accessibility grid.
  await page.getByText('历史已失效',{exact:false}).first().waitFor({state:'attached'});
  await shot('06-revision-history.png','当前质量摘要');
  fs.writeFileSync(path.join(output,'workflow-states.json'),JSON.stringify({before,reviewed,approved},null,2));
  await page.getByText('业务数据',{exact:true}).click();
  await page.waitForTimeout(1200);
  await tab('质量检查');
  await metric('受影响记录数','尚未导入数据');
  assert.equal(await page.locator('[data-testid="stException"]').count(),0);
  assert.deepEqual(errors,[]);
  const result={passed:true,checks:['空库','异常与去重记录计数','分类和业务影响展示','批次与分类筛选和证据导出','历史开关不改变当前摘要','无匹配状态','480px截图','空间隔离','查看前后记录/异常/指标一致','硬规则驳回仍阻断','修订审批前指标不变','审批后失效异常仅历史保留，收入按既有口径增加35，原始记录不变'],errors};
  if(reportMode)result.checks.push('筛选HTML报告与页面数量一致','下载HTML本地离线打开','处理引导导航不自动提交，审核/修订/预警/日志及指标不变');
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 }catch(e){await page.screenshot({path:path.join(output,'failure.png')});fs.writeFileSync(path.join(output,'failure.txt'),String(e)+'\n'+await page.locator('body').innerText());throw e;}
 finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
