// Developer-only real browser verification. Runtime needs no Node or Playwright.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.V2_BASE_URL || 'http://127.0.0.1:8503';
const evidence = path.join(__dirname, 'evidence');
fs.mkdirSync(evidence, { recursive: true });
const results = [];
async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1560, height: 1500 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  async function metric(index, value) {
    await page.locator('[data-testid="stMetricValue"]').nth(index).filter({ hasText: value }).waitFor({timeout:30000});
    assert.equal((await page.locator('[data-testid="stMetricValue"]').nth(index).innerText()).trim(), value);
  }
  async function select(label, value) {
    const box = page.getByRole('combobox', { name: label, exact: true });
    await box.click();
    await page.getByRole('option', { name: value, exact: true }).click();
    await page.waitForTimeout(800);
  }
  async function shot(name) {
    await page.getByRole('heading',{name:'跨境电商智能经营监控与自动化预警',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(evidence,name), fullPage: true, animations: 'disabled' });
  }
  try {
    await page.goto(base);
    await page.getByRole('button',{name:'1 · 导入正常数据',exact:true}).waitFor({timeout:60000});
    await metric(0,'0');
    await page.getByRole('button',{name:'1 · 导入正常数据',exact:true}).click();
    await page.getByText('导入完成：新增 7 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
    await metric(1,'35.00 USD');
    await metric(2,'19.00 USD');
    results.push('normal: orders=1, sales=35, gross=19');
    await shot('01-normal.png');

    await page.getByRole('button',{name:'2 · 重复上传',exact:true}).click();
    await page.getByText('识别到重复上传：新增 0 条记录，订单及金额保持不变。',{exact:true}).waitFor();
    await metric(1,'35.00 USD');
    results.push('duplicate bytes: no amount changes');
    await shot('02-duplicate.png');

    await page.getByRole('button',{name:'3 · 导入错误数据',exact:true}).click();
    await page.getByText('导入完成：新增 5 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
    await metric(1,'70.00 USD');
    await metric(3,'4');
    await page.getByRole('tab',{name:'质量检查',exact:true}).click();
    await page.getByRole('button',{name:'导出质量检查证据',exact:true}).waitFor();
    await shot('03-quality.png');
    results.push('errors: sales=70, four whole-record quarantines, one unknown-cost scope');

    await page.getByRole('tab',{name:'异常审核',exact:true}).click();
    await page.getByRole('combobox',{name:'选择异常',exact:true}).click();
    await page.getByRole('option').filter({hasText:'review_high_price'}).click();
    await page.waitForTimeout(800); // allow the Streamlit server rerun to finish
    await select('审核结论','驳回');
    await page.getByRole('textbox',{name:'处理说明（必填）',exact:true}).fill('已核对原始订单凭证，150美元为真实价格，驳回软规则误报。');
    await page.getByRole('button',{name:'保存审核',exact:true}).click();
    await metric(1,'365.00 USD');
    results.push('soft rejection: valid sales increase to 365');
    await shot('04-review.png');

    await page.getByRole('combobox',{name:'选择异常',exact:true}).click();
    await page.getByRole('option').filter({hasText:'invalid_price'}).click();
    await select('审核结论','确认');
    await page.getByRole('textbox',{name:'处理说明（必填）',exact:true}).fill('负价格异常已确认，继续隔离等待凭证修订。');
    await page.getByRole('button',{name:'保存审核',exact:true}).click();
    await page.getByText('审核已保存，处理说明和操作日志已留存。',{exact:true}).waitFor();
    await metric(1,'365.00 USD');
    results.push('hard confirmation: invalid price stays isolated');

    await page.getByRole('tab',{name:'批次与日志',exact:true}).click();
    await page.getByRole('button',{name:'下载原文件',exact:true}).waitFor();
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button',{name:'下载原文件',exact:true}).click()
    ]);
    const downloaded = await download.path();
    assert(fs.statSync(downloaded).size > 0);
    await shot('05-ledger.png');
    results.push('original evidence download and review/import logs visible');

    await page.getByText('业务数据',{exact:true}).click();
    await metric(0,'0');
    await metric(1,'尚未导入数据');
    await page.getByRole('tab',{name:'数据导入',exact:true}).click();
    await select('业务表类型','workbook');
    await page.locator('input[type=file]').setInputFiles(path.join(__dirname,'demo_data/normal.xlsx'));
    await page.getByText('normal.xlsx',{exact:true}).waitFor();
    await page.waitForTimeout(800);
    await page.getByRole('button',{name:'导入上传文件',exact:true}).click();
    await page.getByText('导入完成：新增 7 条；跳过 0 条相同业务记录。',{exact:true}).waitFor();
    await metric(1,'35.00 USD');
    results.push('actual Excel upload: new business space starts empty then sales=35');

    await select('业务表类型','orders');
    await page.locator('input[type=file]').setInputFiles(path.join(__dirname,'demo_data/orders.csv'));
    await page.getByText('orders.csv',{exact:true}).waitFor();
    await page.waitForTimeout(800);
    await page.getByRole('button',{name:'导入上传文件',exact:true}).click();
    await page.getByText('导入完成：新增 0 条；跳过 2 条相同业务记录。',{exact:true}).waitFor();
    await metric(1,'35.00 USD');
    results.push('actual CSV upload overlapping Excel: added=0, duplicates=2');
    await shot('06-upload.png');

    await page.reload();
    await page.getByText('业务数据',{exact:true}).click();
    await metric(1,'35.00 USD');
    assert.equal(await page.locator('[data-testid="stException"]').count(),0);
    assert.deepEqual(errors,[]);
    results.push('browser reload: SQLite state persists; no application/browser exceptions');
    fs.writeFileSync(path.join(evidence,'browser-results.json'),JSON.stringify({base,passed:true,checks:results,errors},null,2));
    console.log(JSON.stringify({passed:true,checks:results},null,2));
  } catch(error) {
    await shot('failure.png');
    fs.writeFileSync(path.join(evidence,'browser-failure.txt'),String(error)+'\n'+await page.locator('body').innerText());
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode=1; });
