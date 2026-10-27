// Verify actual local MP4 playback in Microsoft Edge. No application writes.
// node verify_video.cjs <video-directory>
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
const out = path.resolve(process.argv[2]);
(async () => {
  const html = '<!doctype html><meta charset="utf-8"><title>V2.1 中文字幕演示</title><style>body{margin:0;background:#000}video{width:100vw;height:100vh;object-fit:contain}</style><video controls muted preload="auto" src="ecommerce-v21-demo-zh-CN.mp4"></video>';
  fs.writeFileSync(path.join(out, 'watch.html'), html);
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    await page.goto(pathToFileURL(path.join(out, 'watch.html')).href);
    await page.waitForFunction(() => document.querySelector('video').readyState >= 2);
    const metadata = await page.locator('video').evaluate(v => ({ duration: v.duration, width: v.videoWidth, height: v.videoHeight, codecSupport: v.canPlayType('video/mp4; codecs="avc1.640028"') }));
    assert(Math.abs(metadata.duration - 300) < 0.1);
    assert.equal(metadata.width, 1920); assert.equal(metadata.height, 1080);
    await page.locator('video').evaluate(v => v.play());
    await page.waitForTimeout(1200);
    const advanced = await page.locator('video').evaluate(v => { v.pause(); return v.currentTime; });
    assert(advanced > 0.5, 'Playback time must advance');
    const seekChecks = [];
    for (const time of [1, 30, 75, 120, 170, 195, 220, 245, 275, 295]) {
      await page.locator('video').evaluate((v, time) => new Promise(resolve => {
        v.addEventListener('seeked', resolve, { once: true }); v.currentTime = time;
      }), time);
      await page.waitForTimeout(350);
      const state = await page.locator('video').evaluate(v => ({ time: v.currentTime, error: v.error?.message || null, readyState: v.readyState }));
      assert.equal(state.error, null); assert(state.readyState >= 2);
      await page.screenshot({ path: path.join(out, `playback-${String(time).padStart(3, '0')}.png`) });
      seekChecks.push(state);
    }
    const result = { passed: true, browser: 'Microsoft Edge / Playwright', ...metadata, playbackAdvancedSeconds: advanced, seekChecks };
    fs.writeFileSync(path.join(out, 'playback-verification.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
