// Phase 2B acceptance. Requires an explicitly isolated Streamlit server and data root.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const data=process.env.V2_PHASE2_DATA_DIR;
const url=process.env.V2_BASE_URL;
assert(data && url,'Isolated data root and URL are required');
const output=process.env.V2_EVIDENCE_DIR || path.join(__dirname,'runtime','v205-phase2b','browser');
fs.mkdirSync(output,{recursive:true});
function metrics(filters={}) {
 const source="import json,sys; from v2.service import Store; from v2.metrics import MetricCenter; from v2.alerts import safe_json; print(safe_json(MetricCenter(Store(sys.argv[1])).calculate('demo',**json.loads(sys.argv[2]))))";
 return JSON.parse(execFileSync((process.env.V2_PYTHON || path.join(__dirname,'.venv','Scripts','python.exe')),['-X','utf8','-c',source,data,JSON.stringify(filters)],{cwd:path.dirname(__dirname),encoding:'utf8'}));
}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:1250}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 async function select(label,value){
  const combo=page.getByRole('combobox',{name:label,exact:true});
  await combo.focus();await combo.press('ArrowDown');
  await page.getByRole('option',{name:value,exact:true}).click();
  await page.waitForTimeout(1000);
 }
 async function shot(name,heading){
  await page.getByRole('heading',{name:heading,exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,name),animations:'disabled'});
 }
 try {
  await page.goto(url);
  await page.getByRole('tab',{name:'批次与日志',exact:true}).waitFor({timeout:60000});
  await page.getByText('经营分析',{exact:true}).click();
  await page.locator('[data-testid="stMetricValue"]').first().filter({hasText:'尚未导入数据'}).waitFor();
  await shot('00-empty.png','经营分析 · USD');
  await page.getByText('数据运营工作台',{exact:true}).click();
  await page.getByRole('tab',{name:'批次与日志',exact:true}).click();
  await page.getByRole('button',{name:'导入14天第二阶段模拟数据',exact:true}).click();
  await page.getByText('导入完成：新增 123 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
  const before=metrics();
  await page.getByText('经营分析',{exact:true}).click();
  await page.locator('[data-testid="stMetricValue"]').first().filter({hasText:'1364.00 USD'}).waitFor();
  const labels=await page.locator('[data-testid="stMetricLabel"]').allTextContents();
  assert.deepEqual(labels.map(x=>x.trim()),['折后销售额（USD）','有效订单数（笔）','商品毛利（USD）','暂估经营贡献利润（USD）','商品毛利率','广告归因ROAS（倍）','12天退款订单率','成本覆盖率','订单可用率','成本已知订单销售额（USD）','筛选适用待处理预警（条）']);
  await shot('01-summary.png','经营摘要');
  await shot('02-trend.png','趋势分析');
  assert.match(await page.locator('body').innerText(),/\d{4}-\d{2}-\d{2}销售额较\d{4}-\d{2}-\d{2}/);
  await shot('03-rankings.png','销售 Top SKU');
  await page.getByText('指标公式、纳入规则和数据血缘',{exact:true}).click();
  await shot('04-definitions.png','指标说明');
  await select('监控SKU','SKU001');
  await page.locator('[data-testid="stMetricValue"]').first().filter({hasText:'924.00 USD'}).waitFor();
  assert.match(await page.locator('body').innerText(),/SKU：SKU001/);
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出筛选后经营指标与血缘 JSON',exact:true}).click()]);
  const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.deepEqual(exported,metrics({...exported.filters,as_of:exported.as_of}));
  await select('国家/地区（广告不分摊）','US');
  await page.getByText('数据不足；当前筛选没有可计算的平台贡献利润，无法排名；国家筛选不分摊广告。',{exact:true}).waitFor();
  await select('国家/地区（广告不分摊）','全部');
  await page.setViewportSize({width:480,height:1100});
  await shot('05-mobile-summary.png','核心经营指标');
  const clipping=await page.locator('[data-testid="stMetricValue"]').evaluateAll(nodes=>nodes.some(n=>n.scrollWidth>n.clientWidth+2));
  assert.equal(clipping,false,'KPI values should not be clipped');
  assert.deepEqual(metrics(),before,'Viewing and filtering must leave metric results unchanged');
  assert.equal(await page.locator('[data-testid="stException"]').count(),0);
  assert.deepEqual(errors,[]);
  const result={passed:true,url,checks:['空库状态','KPI三层及独立待办','显式日期趋势摘要','排名与说明展示','筛选摘要','JSON导出与指标服务逐字段一致','国家贡献不分摊','480px数字不截断','浏览前后指标一致'],errors};
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 } catch(error) {
  await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  fs.writeFileSync(path.join(output,'failure.txt'),String(error)+'\n'+await page.locator('body').innerText());
  throw error;
 } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
