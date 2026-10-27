// Only the public Synthetic demo is allowed. Never point this at a business database.
// Usage: node capture_demo.cjs <output-directory>
// Optional PLAYWRIGHT_MODULE resolves an existing Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const URL = 'https://ecommerce-business-analysis-izcmrhydxddnasxqdbdxxr.streamlit.app/';
const out = path.resolve(process.argv[2] || 'portfolio-capture');
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const root = await context.newPage();
  root.setDefaultTimeout(45000);
  let page = root;
  const events = [], shots = [];
  root.on('pageerror', e => events.push({ type: 'pageerror', message: String(e) }));
  root.on('requestfailed', r => events.push({ type: 'requestfailed', url: r.url(), failure: r.failure() }));
  const wait = async () => {
    await root.waitForTimeout(1800);
    await page.locator('[data-testid=stStatusWidget]').waitFor({ state: 'hidden', timeout: 60000 }).catch(() => {});
    await root.waitForTimeout(1200);
    assert.equal(await page.locator('[data-testid=stException]').count(), 0, 'Streamlit exception');
  };
  const nav = async name => { await page.getByText(name, { exact: true }).click(); await wait(); };
  const select = async (label, option, search = false) => {
    const box = page.getByRole('combobox', { name: label, exact: true });
    await box.click();
    if (search) await box.fill(option);
    const item = search ? page.getByRole('option').filter({ hasText: option }) : page.getByRole('option', { name: option, exact: true });
    await item.first().click(); await wait();
  };
  const at = async locator => {
    await locator.scrollIntoViewIfNeeded();
    // Center an actual DOM element by scrolling only; never modify page values or styling.
    await locator.evaluate(el => el.scrollIntoView({ block: 'center' }));
    await root.waitForTimeout(700);
  };
  const snap = async (id, focus, expected = []) => {
    await wait();
    if (focus) await at(focus);
    const text = await page.locator('body').textContent();
    for (const value of expected) assert(text.includes(value), `${id}: missing ${value}`);
    await root.screenshot({ path: path.join(out, `${id}.png`) });
    fs.writeFileSync(path.join(out, `${id}.txt`), text);
    const record = { id, url: root.url(), capturedAt: new Date().toISOString(), expected };
    shots.push(record);
    fs.writeFileSync(path.join(out, 'capture-manifest.json'), JSON.stringify({ url: URL, synthetic: true, shots, events }, null, 2));
    console.log(`Captured ${id}`);
  };
  const download = async (label, file) => {
    const pending = root.waitForEvent('download');
    await page.getByText(label, { exact: true }).click();
    await (await pending).saveAs(path.join(out, file));
  };
  const dateDay = async (label, day) => {
    const field = page.getByRole('spinbutton', { name: `day, ${label}`, exact: true });
    await field.fill(String(day)); await field.press('Tab'); await root.keyboard.press('Escape'); await wait();
  };
  try {
    await root.goto(URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
    for (let i = 0; i < 45; i++) {
      page = root.frames().find(f => f.url().startsWith(URL + '~/')) || root;
      if (await page.getByText('经营分析 · USD', { exact: true }).count()) break;
      await root.waitForTimeout(2000);
    }
    await page.getByText('经营分析 · USD', { exact: true }).waitFor({ timeout: 90000 });
    await wait();
    assert((await page.locator('body').textContent()).includes('公开 Synthetic 演示'), 'Only public Synthetic mode is authorized');
    await snap('01-home', page.getByText('跨境电商智能经营监控与自动化预警', { exact: true }), ['1364.00 USD']);
    await snap('02-baseline', page.getByText('核心经营指标', { exact: true }), ['658.00 USD', '262.00 USD']);

    await nav('数据运营工作台');
    await snap('03-workbench', page.getByTestId('stMetric').first(), ['待核实异常', '1364.00 USD']);
    await page.getByRole('tab', { name: '质量检查', exact: true }).click();
    await snap('04-quality-summary', page.getByText('当前质量摘要', { exact: true }));
    await select('查看质量问题及处理建议', '单价缺失', true);
    await page.getByText('所选问题的原始值与技术证据', { exact: true }).click();
    await snap('05-negative-price', page.getByText('所选问题的原始值与技术证据', { exact: true }), ['SYNTH-BAD', 'invalid_price', '-10']);
    await snap('06-price-rule', page.getByText('所选问题的原始值与技术证据', { exact: true }).locator('..'), ['invalid_price']);
    await select('查看质量问题及处理建议', '优惠缺失', true);
    await snap('07-discount-rule', page.getByText('所选问题的原始值与技术证据', { exact: true }), ['invalid_discount']);
    await select('查看质量问题及处理建议', '标准 SKU', true);
    await snap('08-unknown-cost', page.getByText('所选问题的原始值与技术证据', { exact: true }), ['SYNTH-UNKNOWN', 'SKU999']);
    await download('下载数据质量报告（HTML）', 'quality-before.html');

    await nav('经营分析');
    await select('监控SKU', 'SKU001');
    await snap('09-sku001', page.getByText('核心经营指标', { exact: true }), ['924.00 USD', '532.00 USD']);
    await select('监控SKU', 'SKU002');
    await snap('10-sku002', page.getByText('核心经营指标', { exact: true }), ['420.00 USD', '126.00 USD', '数据不足']);
    await select('监控SKU', '全部');

    await nav('经营日报');
    await dateDay('退款观察截止日 H', 21);
    await snap('11-daily-before', page.getByText('当日表现与前一日比较', { exact: true }), ['两日共同退款观察截止日：2026-10-21', '92.00 USD']);
    await download('下载 HTML 日报', 'daily-before.html');

    await nav('智能预警');
    await dateDay('检测参考日', 21);
    await page.getByRole('button', { name: '运行规则检测', exact: true }).click();
    await snap('12-alert-run', page.getByText('智能规则预警与处理工作台', { exact: true }), ['检测完成：触发 22 项', '15.48个百分点']);
    await snap('13-alert-evidence', page.getByRole('combobox', { name: '选择经营预警', exact: true }), ['平台12天退款订单率']);
    await select('经营预警处理结论', '处理中');
    await page.getByRole('textbox', { name: '经营预警处理说明（必填）', exact: true }).fill('Synthetic 演示：核对退款批准凭证、成熟订单队列及商品和物流原因；尚未确认根因。');
    await page.getByRole('button', { name: '保存预警处理', exact: true }).click();
    await snap('14-alert-handled', page.getByRole('combobox', { name: '经营预警处理结论', exact: true }), ['处理中', '预警处理已保存']);

    await nav('数据修订');
    await select('修订原始记录', 'SYNTH-BAD', true);
    await select('允许修订字段', 'unit_price');
    await page.getByRole('textbox', { name: '建议新值（文本，空值用勾选）', exact: true }).fill('20');
    await page.getByRole('textbox', { name: '修订原因（必填）', exact: true }).fill('Synthetic 演示：负价订单按模拟凭证申请改为20 USD，不代表真实交易。');
    await page.getByRole('textbox', { name: '证据引用（凭证编号或本地文件路径，必填）', exact: true }).fill('SYNTH-PORTFOLIO-PRICE20');
    await snap('15-revision-form', page.getByText('当前字段值：', { exact: false }).first(), ['-10']);
    await page.getByRole('button', { name: '提交修订申请', exact: true }).click();
    await snap('16-revision-submitted', page.getByText('带凭证的数据修订与版本审批', { exact: true }), ['审批前指标不变']);
    await page.getByRole('textbox', { name: '修订审核说明（必填）', exact: true }).fill('仅模拟审批：核对记录及模拟凭证，同意单价20 USD；批准后重新质检，继续核对关联库存。');
    await snap('17-approval-form', page.getByRole('textbox', { name: '修订审核说明（必填）', exact: true }));
    await page.getByRole('button', { name: '保存修订审批', exact: true }).click();
    await wait();
    await page.getByText('原值、新值、凭证及审批历史', { exact: true }).click();
    await snap('18-revision-approved', page.getByText('原值、新值、凭证及审批历史', { exact: true }), ['已批准', 'SYNTH-PORTFOLIO-PRICE20']);
    await nav('经营分析');
    await snap('19-recomputed', page.getByText('核心经营指标', { exact: true }), ['1384.00 USD', '670.00 USD', '272.00 USD']);

    await nav('数据运营工作台');
    await page.getByRole('tab', { name: '质量检查', exact: true }).click();
    await select('质量业务表', '库存');
    await wait();
    await snap('20-inventory-difference', page.getByText('问题明细与处理引导', { exact: true }), ['库存出库数量与有效完成订单数量不符']);
    await page.getByText('所选问题的原始值与技术证据', { exact: true }).click();
    await snap('21-inventory-source', page.getByText('所选问题的原始值与技术证据', { exact: true }), ['inventory_order_difference']);
    await download('下载数据质量报告（HTML）', 'quality-after.html');

    await nav('经营日报');
    await dateDay('退款观察截止日 H', 21);
    await snap('22-daily-dates', page.getByText('经营日期 D', { exact: true }), ['两日共同退款观察截止日：2026-10-21']);
    await snap('23-daily-after', page.getByText('当日表现与前一日比较', { exact: true }), ['112.00 USD', '2.00 USD', '0.56倍']);
    await snap('24-daily-limits', page.getByText('样本与数据限制', { exact: true }));
    await snap('25-daily-guidance', page.getByText('运营关注与核查建议', { exact: true }));
    await snap('26-daily-download', page.getByText('下载 HTML 日报', { exact: true }));
    await download('下载 HTML 日报', 'daily-after.html');
    await nav('经营分析');
    await snap('27-ending', page.getByText('核心经营指标', { exact: true }));
    fs.writeFileSync(path.join(out, 'capture-result.json'), JSON.stringify({ passed: true, shots: shots.length, events }, null, 2));
  } catch (e) {
    await root.screenshot({ path: path.join(out, 'capture-failure.png') }).catch(() => {});
    fs.writeFileSync(path.join(out, 'capture-result.json'), JSON.stringify({ passed: false, error: String(e), shots, events }, null, 2));
    throw e;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
