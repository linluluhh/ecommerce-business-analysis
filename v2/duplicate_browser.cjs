// Two-phase real browser regression: restart the Streamlit process between phases.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const phase=process.argv[2] || 'initial';
const root=path.dirname(__dirname);
const evidence=path.join(__dirname,'evidence','duplicate-upload');
const data=process.env.V2_DUPLICATE_DATA_DIR;
const url=process.env.V2_BASE_URL || 'http://127.0.0.1:8510';
assert(data,'V2_DUPLICATE_DATA_DIR must point to a separate temporary database');
fs.mkdirSync(evidence,{recursive:true});
const python=path.join(__dirname,'.venv','Scripts','python.exe');
function snapshot(){
  const code="import json,sys; from v2.service import Store; from v2.audit_duplicate import encode; print(json.dumps(Store(sys.argv[1]).metrics('demo'),sort_keys=True,default=encode))";
  return JSON.parse(execFileSync(python,['-c',code,data],{cwd:root,encoding:'utf8'}));
}
async function main(){
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1560,height:1700}});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  async function metric(value){
    const locator=page.locator('[data-testid="stMetricValue"]').nth(1);
    await locator.filter({hasText:value}).waitFor();
    assert.equal((await locator.innerText()).trim(),value);
  }
  async function screenshot(filename){
    await page.getByRole('heading',{name:'跨境电商智能经营监控与自动化预警',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,filename),fullPage:true,animations:'disabled'});
  }
  try{
    await page.goto(url);
    await page.getByRole('button',{name:'1 · 导入正常数据',exact:true}).waitFor({timeout:60000});
    if(phase==='initial'){
      await metric('尚未导入数据');
      await page.getByRole('button',{name:'1 · 导入正常数据',exact:true}).click();
      await page.getByText('导入完成：新增 7 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
      await metric('35.00 USD');
      const before=snapshot();
      assert.equal(before.monthly['2026-09'].sales,'35');
      assert.equal(before.monthly['2026-09'].contribution,'10');
      await screenshot('01-before-duplicate.png');
      for(let n=0;n<2;n++){
        await page.getByRole('button',{name:'2 · 重复上传',exact:true}).click();
        await page.getByText('识别到重复上传：新增 0 条记录，订单及金额保持不变。',{exact:true}).waitFor();
        await metric('35.00 USD');
        assert.deepEqual(snapshot(),before);
      }
      await screenshot('02-after-duplicate.png');
      await page.reload();
      await metric('35.00 USD');
      assert.deepEqual(snapshot(),before);
      await screenshot('03-after-refresh.png');
      assert.equal(await page.locator('[data-testid="stException"]').count(),0);
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(evidence,'browser-initial.json'),JSON.stringify({passed:true,data,url,before,after:snapshot(),page_refresh_identical:true,errors},null,2));
      console.log('PASS: normal, two repeated clicks, all metrics and browser refresh identical');
    }else{
      const baseline=JSON.parse(fs.readFileSync(path.join(evidence,'browser-initial.json'),'utf8'));
      assert.equal(path.resolve(baseline.data),path.resolve(data));
      await metric('35.00 USD');
      assert.deepEqual(snapshot(),baseline.before);
      await screenshot('04-after-process-restart.png');
      await page.getByRole('button',{name:'3 · 导入错误数据',exact:true}).click();
      await page.getByText('导入完成：新增 5 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
      await metric('70.00 USD');
      const mixed=snapshot();
      assert.equal(mixed.monthly['2026-09'].contribution,'10');
      assert.deepEqual(mixed.sales_records.map(r=>[r.order_id,r.sales,r.profit_included]),[
        ['DEMO001','35',true],['UNKNOWN_SKU','35',false]
      ]);
      await page.getByText('逐笔销售额来源（当前空间全部有效批次）',{exact:true}).click();
      await screenshot('05-seventy-lineage.png');
      await page.getByRole('button',{name:'2 · 重复上传',exact:true}).click();
      await page.getByText('识别到重复上传：新增 0 条记录，订单及金额保持不变。',{exact:true}).waitFor();
      await metric('70.00 USD');
      assert.deepEqual(snapshot(),mixed);
      await page.reload();
      await metric('70.00 USD');
      assert.deepEqual(snapshot(),mixed);
      assert.equal(await page.locator('[data-testid="stException"]').count(),0);
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(evidence,'browser-restart.json'),JSON.stringify({passed:true,data,url,process_restart_identical:true,after_restart:baseline.before,mixed,mixed_duplicate_identical:true,errors},null,2));
      console.log('PASS: process restart identical; 70 is DEMO001+UNKNOWN_SKU; mixed duplicate and refresh identical');
    }
  }catch(error){
    await screenshot('failure-'+phase+'.png');
    throw error;
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
