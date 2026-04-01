const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const BASE = 'http://localhost:9000';
const OUT = path.join(__dirname, 'screenshots');

if (!fs.existsSync(OUT)) fs.mkdirSync(OUT);

async function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

(async () => {
  const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  // ① 로그인 모달 (비로그인 상태)
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '01_login_modal.png') });
  console.log('01_login_modal.png saved');

  // 로그인
  await page.evaluate(async () => {
    const res = await fetch('/api/tester/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: 'tester1', password: 'test1234' })
    });
    return res.json();
  });
  await delay(500);

  // ② 채팅 테스터 메인 화면
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '02_chat_main.png') });
  console.log('02_chat_main.png saved');

  // ③ 시나리오 관리 페이지
  await page.goto(BASE + '/scenario_manager.html', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '03_scenario_manager.png') });
  console.log('03_scenario_manager.png saved');

  // ④ 새 시나리오 등록 모달
  await page.click('button.new-btn, .btn-new, button[onclick*="showNew"], button');
  // + 새 시나리오 버튼 찾기
  const buttons = await page.$$('button');
  for (const btn of buttons) {
    const text = await page.evaluate(el => el.textContent.trim(), btn);
    if (text.includes('새 시나리오')) {
      await btn.click();
      break;
    }
  }
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '04_new_scenario_modal.png') });
  console.log('04_new_scenario_modal.png saved');

  // 모달 닫기
  await page.keyboard.press('Escape');
  await delay(500);

  // ⑤ AI 자동 생성 탭
  const tabs = await page.$$('[data-tab], .tab-btn, .tab');
  for (const tab of tabs) {
    const text = await page.evaluate(el => el.textContent.trim(), tab);
    if (text.includes('AI 자동 생성')) {
      await tab.click();
      break;
    }
  }
  await delay(500);
  await page.screenshot({ path: path.join(OUT, '05_ai_generate.png') });
  console.log('05_ai_generate.png saved');

  // ⑥ 테스트 이력
  await page.goto(BASE + '/history.html', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '06_history.png') });
  console.log('06_history.png saved');

  // ⑦ 법률 평가 기준
  await page.goto(BASE + '/guidelines', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '07_guidelines.png') });
  console.log('07_guidelines.png saved');

  // ⑧ 문진 평가 기준
  await page.goto(BASE + '/criteria', { waitUntil: 'networkidle0' });
  await delay(1000);
  await page.screenshot({ path: path.join(OUT, '08_criteria.png') });
  console.log('08_criteria.png saved');

  await browser.close();
  console.log('모든 스크린샷 저장 완료:', OUT);
})().catch(e => { console.error(e); process.exit(1); });
