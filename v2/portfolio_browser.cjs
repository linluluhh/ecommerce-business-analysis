// Public entry acceptance: real UI writes in A must not affect browser context B.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const url=process.env.V2_BASE_URL;
assert(url && /^http:\/\/127\.0\.0\.1:/.test(url),'Explicit loopback public-demo server required');
const out=path.join(__dirname,'runtime','deploy-validation','browser');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ca=await browser.newContext({viewport:{width:1366,height:1000}}),cb=await browser.newContext({viewport:{width:1366,height:1000}});
 const a=await ca.newPage(),b=await cb.newPage(),errors=[],checks=[];
 for(const p of [a,b]){p.on('pageerror',e=>errors.push(String(e)));p.setDefaultTimeout(60000);}
 async function idle(p){await p.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden'});await p.waitForTimeout(500);assert.equal(await p.locator('[data-testid="stException"]').count(),0);}
 async function nav(p,name){await p.getByText(name,{exact:true}).click();await idle(p);}
 async function first(p,value){await p.waitForFunction(v=>document.querySelector('[data-testid=stMetricValue]')?.textContent.trim()===v,value,{timeout:60000});assert.equal((await p.getByTestId('stMetricValue').first().innerText()).trim(),value);}
 async function select(p,label,value){const c=p.getByRole('combobox',{name:label,exact:true});await c.click();await p.getByRole('option',{name:value,exact:true}).click();await idle(p);}
 async function download(p,label,file){const event=p.waitForEvent('download');await p.getByText(label,{exact:true}).click();const d=await event;await d.saveAs(path.join(out,file));return fs.readFileSync(path.join(out,file),'utf8');}
 try{
  await Promise.all([a.goto(url),b.goto(url)]);
  await Promise.all([a.getByText('经营分析 · USD',{exact:true}).waitFor(),b.getByText('经营分析 · USD',{exact:true}).waitFor()]);
  await idle(a);await idle(b);await first(a,'1364.00 USD');await first(b,'1364.00 USD');
  await a.screenshot({path:path.join(out,'01-dashboard.png')});checks.push('两个独立浏览器会话冷启动均为1364 USD');
  await nav(a,'数据运营工作台');assert.equal(await a.locator('input[type=file]').count(),0);
  await a.getByRole('tab',{name:'质量检查',exact:true}).click();await idle(a);
  const quality=await download(a,'下载数据质量报告（HTML）','quality.html');assert(quality.includes('Synthetic'));checks.push('公开模式无上传控件，质量报告可下载');
  await nav(a,'数据修订');
  const record=a.getByRole('combobox',{name:'修订原始记录',exact:true});await record.focus();await record.press('ArrowDown');await record.fill('SYNTH-BAD');await a.getByRole('option').filter({hasText:'SYNTH-BAD'}).click();await idle(a);
  await select(a,'允许修订字段','unit_price');
  await a.getByRole('textbox',{name:'建议新值（文本，空值用勾选）',exact:true}).fill('20');
  await a.getByRole('textbox',{name:'修订原因（必填）',exact:true}).fill('公开模拟会话A修订验证');
  await a.getByRole('textbox',{name:'证据引用（凭证编号或本地文件路径，必填）',exact:true}).fill('SYNTH-DEMO-A');
  await a.getByRole('button',{name:'提交修订申请',exact:true}).click();await a.getByText(/已申请，审批前指标不变/).waitFor();await idle(a);
  await a.getByRole('textbox',{name:'修订审核说明（必填）',exact:true}).fill('模拟批准，仅本会话');
  await a.getByRole('button',{name:'保存修订审批',exact:true}).click();await a.getByText(/修订审批已保存/).waitFor();await idle(a);
  await nav(a,'经营分析');await first(a,'1384.00 USD');
  await nav(b,'经营日报');await first(b,'92.00 USD');await nav(b,'经营分析');await first(b,'1364.00 USD');
  checks.push('A实际UI批准修订后1384 USD，B仍1364 USD且日报92 USD');
  await nav(a,'经营日报');await first(a,'112.00 USD');await a.getByText('观测期截至D日的历史预警证据',{exact:true}).waitFor();
  const html=await download(a,'下载 HTML 日报','daily.html');assert(html.includes('112.00 USD'));assert(html.includes('历史'));assert(!/[A-Z]:\\|DESKTOP-|Users\\/.test(html));
  await first(a,'112.00 USD');await a.screenshot({path:path.join(out,'02-daily.png')});checks.push('日报含真实历史留存、限制与建议，下载前后页面数字一致');
  const offline=await browser.newContext({offline:true});const file=await offline.newPage();await file.goto(pathToFileURL(path.join(out,'daily.html')).href);assert((await file.locator('#daily-kpis').innerText()).includes('112.00 USD'));assert.equal(await file.locator('script,link,img,iframe').count(),0);await file.screenshot({path:path.join(out,'03-offline.png')});await file.goto(pathToFileURL(path.join(out,'quality.html')).href);assert((await file.locator('body').innerText()).includes('质量'));await offline.close();checks.push('两类HTML真实断网打开，无外部资源');
  await a.getByRole('button',{name:'重置我的演示',exact:true}).click();await a.waitForFunction(()=>['92.00 USD','1364.00 USD'].includes(document.querySelector('[data-testid=stMetricValue]')?.textContent.trim()),null,{timeout:60000});await idle(a);await nav(a,'经营分析');await first(a,'1364.00 USD');await first(b,'1364.00 USD');checks.push('A重置回到初始种子，B不受影响');
  await nav(a,'智能预警');await a.getByText('智能规则预警与处理工作台',{exact:true}).waitFor();
  await nav(a,'经营日报');await a.setViewportSize({width:480,height:900});await a.waitForTimeout(1200);await a.getByText('当日表现与前一日比较',{exact:true}).scrollIntoViewIfNeeded();await a.screenshot({path:path.join(out,'04-mobile.png')});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({passed:true,checks,errors},null,2));console.log(JSON.stringify({passed:true,checks,errors},null,2));
 }catch(e){await a.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({passed:false,checks,errors,error:String(e)},null,2));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
