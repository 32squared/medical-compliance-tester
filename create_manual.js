const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "SKIX";
pres.title = "나만의 주치의 — 테스터 매뉴얼";

// Colors
const C = {
  bg: "0F172A",
  surface: "1E293B",
  accent: "38BDF8",
  green: "22C55E",
  yellow: "F59E0B",
  red: "EF4444",
  text: "F1F5F9",
  dim: "94A3B8",
  white: "FFFFFF",
  dark: "0B1120",
};

function loadImg(name) {
  const p = path.join(__dirname, "docs", "screenshots", name);
  if (!fs.existsSync(p)) return null;
  return "image/png;base64," + fs.readFileSync(p).toString("base64");
}

// ── Slide 1: Title ──
let s = pres.addSlide();
s.background = { color: C.dark };
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 5.625, fill: { color: C.bg } });
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 4.4, w: 10, h: 1.225, fill: { color: C.surface } });
s.addText("나만의 주치의", {
  x: 0.8, y: 1.0, w: 8.4, h: 1.0,
  fontSize: 44, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
s.addText("의료법 준수 테스트 도구", {
  x: 0.8, y: 1.9, w: 8.4, h: 0.6,
  fontSize: 24, fontFace: "맑은 고딕", color: C.text, margin: 0,
});
s.addText("테스터 사용 매뉴얼", {
  x: 0.8, y: 2.8, w: 8.4, h: 0.8,
  fontSize: 20, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
s.addText("2026.04", {
  x: 0.8, y: 4.7, w: 4, h: 0.5,
  fontSize: 14, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});

// ── Slide 2: 목차 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("목차", {
  x: 0.8, y: 0.4, w: 8.4, h: 0.7,
  fontSize: 32, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const toc = [
  "1. 회원가입 및 로그인",
  "2. 채팅 테스터 화면 구성",
  "3. AI와 대화하기",
  "4. 피드백 남기기 (좋음 / 나쁨)",
  "5. 커멘트 달기",
  "6. 시나리오 추출 및 등록",
  "7. RLHF 관리에서 결과 확인",
];
toc.forEach((item, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 1.0, y: 1.5 + i * 0.55, w: 8.0, h: 0.45,
    fill: { color: C.surface }, rectRadius: 0.05,
  });
  s.addText(item, {
    x: 1.3, y: 1.5 + i * 0.55, w: 7.5, h: 0.45,
    fontSize: 15, fontFace: "맑은 고딕", color: C.text, valign: "middle", margin: 0,
  });
});

// ── Slide 3: 회원가입 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("1. 회원가입", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const loginImg = loadImg("01_login_modal.png");
if (loginImg) {
  s.addImage({ data: loginImg, x: 5.2, y: 1.0, w: 4.3, h: 3.8, sizing: { type: "contain", w: 4.3, h: 3.8 } });
}
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.6, y: 1.0, w: 4.3, h: 4.2,
  fill: { color: C.surface }, rectRadius: 0.1,
});
const regSteps = [
  { n: "1", t: "사이트 접속 후 로그인 모달에서\n'회원가입' 탭을 클릭합니다." },
  { n: "2", t: "ID (2자 이상), 이름, 소속,\n비밀번호 (4자 이상)를 입력합니다." },
  { n: "3", t: "'가입 신청' 버튼을 클릭합니다." },
  { n: "4", t: "관리자 승인을 기다립니다.\n승인 후 로그인이 가능합니다." },
];
regSteps.forEach((step, i) => {
  s.addShape(pres.shapes.OVAL, {
    x: 0.9, y: 1.3 + i * 0.95, w: 0.4, h: 0.4,
    fill: { color: C.accent },
  });
  s.addText(step.n, {
    x: 0.9, y: 1.3 + i * 0.95, w: 0.4, h: 0.4,
    fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.t, {
    x: 1.5, y: 1.25 + i * 0.95, w: 3.2, h: 0.55,
    fontSize: 12, fontFace: "맑은 고딕", color: C.text, valign: "middle", margin: 0, lineSpacingMultiple: 1.2,
  });
});
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.8, y: 5.0, w: 8.4, h: 0.4,
  fill: { color: "1E3A5F" }, rectRadius: 0.05,
});
s.addText("TIP: 소속은 선택사항이지만 입력하면 관리자가 승인 시 참고할 수 있습니다.", {
  x: 1.0, y: 5.0, w: 8.0, h: 0.4,
  fontSize: 11, fontFace: "맑은 고딕", color: C.accent, valign: "middle", margin: 0,
});

// ── Slide 4: 로그인 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("1. 로그인", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
if (loginImg) {
  s.addImage({ data: loginImg, x: 5.2, y: 1.0, w: 4.3, h: 3.8, sizing: { type: "contain", w: 4.3, h: 3.8 } });
}
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.6, y: 1.0, w: 4.3, h: 3.0,
  fill: { color: C.surface }, rectRadius: 0.1,
});
const loginSteps = [
  { n: "1", t: "'로그인' 탭에서 가입한 ID와\n비밀번호를 입력합니다." },
  { n: "2", t: "'로그인' 버튼을 클릭하거나\nEnter 키를 누릅니다." },
  { n: "3", t: "로그인 성공 시 우측 상단에\n이름 배지가 표시됩니다." },
];
loginSteps.forEach((step, i) => {
  s.addShape(pres.shapes.OVAL, {
    x: 0.9, y: 1.3 + i * 0.85, w: 0.4, h: 0.4,
    fill: { color: C.accent },
  });
  s.addText(step.n, {
    x: 0.9, y: 1.3 + i * 0.85, w: 0.4, h: 0.4,
    fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.t, {
    x: 1.5, y: 1.25 + i * 0.85, w: 3.2, h: 0.55,
    fontSize: 12, fontFace: "맑은 고딕", color: C.text, valign: "middle", margin: 0, lineSpacingMultiple: 1.2,
  });
});

// ── Slide 5: 채팅 테스터 화면 구성 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("2. 채팅 테스터 화면 구성", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const chatImg = loadImg("02_chat_main.png");
if (chatImg) {
  s.addImage({ data: chatImg, x: 0.5, y: 1.0, w: 5.5, h: 4.2, sizing: { type: "contain", w: 5.5, h: 4.2 } });
}
// Callouts on right side
const areas = [
  { icon: "A", title: "좌측 사이드바", desc: "대화 목록, 새 대화 생성,\n대화 검색" },
  { icon: "B", title: "상단 네비게이션", desc: "채팅 테스터, 시나리오 관리,\nRLHF 관리 등 메뉴 이동" },
  { icon: "C", title: "중앙 대화 영역", desc: "AI 응답, 참고 자료,\n후속 질문 표시" },
  { icon: "D", title: "하단 입력창", desc: "질문 입력 후\nEnter로 전송" },
];
areas.forEach((a, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 6.3, y: 1.0 + i * 1.0, w: 3.3, h: 0.85,
    fill: { color: C.surface }, rectRadius: 0.08,
  });
  s.addShape(pres.shapes.OVAL, {
    x: 6.5, y: 1.1 + i * 1.0, w: 0.35, h: 0.35,
    fill: { color: C.accent },
  });
  s.addText(a.icon, {
    x: 6.5, y: 1.1 + i * 1.0, w: 0.35, h: 0.35,
    fontSize: 12, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(a.title, {
    x: 7.0, y: 1.05 + i * 1.0, w: 2.4, h: 0.3,
    fontSize: 13, fontFace: "맑은 고딕", bold: true, color: C.white, valign: "middle", margin: 0,
  });
  s.addText(a.desc, {
    x: 7.0, y: 1.35 + i * 1.0, w: 2.4, h: 0.45,
    fontSize: 10, fontFace: "맑은 고딕", color: C.dim, valign: "top", margin: 0, lineSpacingMultiple: 1.2,
  });
});

// ── Slide 6: AI와 대화하기 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("3. AI와 대화하기", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const convSteps = [
  { n: "1", t: "하단 입력창에 건강 관련 질문을 입력합니다.", ex: "예: \"비타민 D가 부족하면 어떤 증상이 나타나나요?\"" },
  { n: "2", t: "Enter 키를 누르거나 전송 버튼을 클릭합니다.", ex: "Shift+Enter로 줄바꿈 가능" },
  { n: "3", t: "AI가 실시간 스트리밍으로 답변합니다.", ex: "응답 시간, 토큰 사용량이 하단에 표시됩니다" },
  { n: "4", t: "후속 질문 버튼으로 연속 대화가 가능합니다.", ex: "AI가 제안하는 관련 질문을 클릭하세요" },
];
convSteps.forEach((step, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.8, y: 1.1 + i * 1.05, w: 8.4, h: 0.9,
    fill: { color: C.surface }, rectRadius: 0.08,
  });
  s.addShape(pres.shapes.OVAL, {
    x: 1.1, y: 1.25 + i * 1.05, w: 0.45, h: 0.45,
    fill: { color: C.accent },
  });
  s.addText(step.n, {
    x: 1.1, y: 1.25 + i * 1.05, w: 0.45, h: 0.45,
    fontSize: 16, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.t, {
    x: 1.8, y: 1.15 + i * 1.05, w: 7.2, h: 0.4,
    fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.white, valign: "middle", margin: 0,
  });
  s.addText(step.ex, {
    x: 1.8, y: 1.55 + i * 1.05, w: 7.2, h: 0.35,
    fontSize: 11, fontFace: "맑은 고딕", italic: true, color: C.dim, valign: "top", margin: 0,
  });
});

// ── Slide 7: 피드백 — 좋음 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("4. 피드백 남기기 — 좋음 (Good)", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.green, margin: 0,
});
s.addText("AI 응답 아래 피드백 영역에서 평가를 남길 수 있습니다.", {
  x: 0.8, y: 0.85, w: 8.4, h: 0.4,
  fontSize: 13, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
// Good feedback flow
const goodFlow = [
  { icon: "👍", title: "'좋음' 버튼 클릭", desc: "답변이 적절하다고 판단되면 클릭" },
  { icon: "★", title: "별점 선택 (4~5점)", desc: "좋음 선택 시 자동으로 4점 이상" },
  { icon: "✍", title: "메모 입력 (선택)", desc: "어떤 점이 좋았는지 자유롭게 기록" },
  { icon: "💾", title: "'저장' 버튼 클릭", desc: "피드백이 서버에 저장됩니다" },
];
goodFlow.forEach((f, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5 + i * 2.35, y: 1.5, w: 2.15, h: 2.8,
    fill: { color: C.surface }, rectRadius: 0.1,
  });
  s.addText(f.icon, {
    x: 0.5 + i * 2.35, y: 1.7, w: 2.15, h: 0.7,
    fontSize: 36, fontFace: "맑은 고딕", align: "center", valign: "middle", margin: 0,
  });
  s.addText(f.title, {
    x: 0.5 + i * 2.35, y: 2.5, w: 2.15, h: 0.5,
    fontSize: 13, fontFace: "맑은 고딕", bold: true, color: C.white, align: "center", valign: "middle", margin: 0,
  });
  s.addText(f.desc, {
    x: 0.5 + i * 2.35, y: 3.0, w: 2.15, h: 0.8,
    fontSize: 11, fontFace: "맑은 고딕", color: C.dim, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.3,
  });
  if (i < goodFlow.length - 1) {
    s.addText("→", {
      x: 2.55 + i * 2.35, y: 2.2, w: 0.5, h: 0.5,
      fontSize: 24, fontFace: "맑은 고딕", color: C.accent, align: "center", valign: "middle", margin: 0,
    });
  }
});

// ── Slide 8: 피드백 — 나쁨 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("4. 피드백 남기기 — 나쁨 (Bad)", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.red, margin: 0,
});
s.addText("문제가 있는 답변에 대해 상세한 피드백을 남길 수 있습니다.", {
  x: 0.8, y: 0.85, w: 8.4, h: 0.4,
  fontSize: 13, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
// Left: steps
const badSteps = [
  { n: "1", t: "'나쁨' 버튼 클릭 → 별점 1~3점 선택" },
  { n: "2", t: "문제 태그 선택 (복수 선택 가능)" },
  { n: "3", t: "수정된 응답 작성 (선택사항)" },
  { n: "4", t: "메모 입력 후 '저장' 클릭" },
];
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.5, y: 1.4, w: 4.5, h: 3.8,
  fill: { color: C.surface }, rectRadius: 0.1,
});
badSteps.forEach((step, i) => {
  s.addShape(pres.shapes.OVAL, {
    x: 0.8, y: 1.7 + i * 0.85, w: 0.35, h: 0.35,
    fill: { color: C.red },
  });
  s.addText(step.n, {
    x: 0.8, y: 1.7 + i * 0.85, w: 0.35, h: 0.35,
    fontSize: 12, fontFace: "맑은 고딕", bold: true, color: C.white, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.t, {
    x: 1.35, y: 1.65 + i * 0.85, w: 3.4, h: 0.4,
    fontSize: 12, fontFace: "맑은 고딕", color: C.text, valign: "middle", margin: 0,
  });
});

// Right: tag grid
s.addText("문제 태그 종류", {
  x: 5.3, y: 1.4, w: 4.2, h: 0.4,
  fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.yellow, margin: 0,
});
const tags = ["진단언급", "처방시도", "치료지시", "적절한거절", "응급안내누락", "과잉친절", "정보부족", "우수답변"];
tags.forEach((tag, i) => {
  const col = i % 2;
  const row = Math.floor(i / 2);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.3 + col * 2.1, y: 1.9 + row * 0.55, w: 1.9, h: 0.42,
    fill: { color: "2D3748" }, rectRadius: 0.05,
    line: { color: C.yellow, width: 0.5 },
  });
  s.addText(tag, {
    x: 5.3 + col * 2.1, y: 1.9 + row * 0.55, w: 1.9, h: 0.42,
    fontSize: 11, fontFace: "맑은 고딕", color: C.yellow, align: "center", valign: "middle", margin: 0,
  });
});
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 5.3, y: 4.2, w: 4.2, h: 0.9,
  fill: { color: "1E3A5F" }, rectRadius: 0.08,
});
s.addText([
  { text: "TIP: ", options: { bold: true, color: C.accent } },
  { text: "'수정된 응답'을 작성하면 AI 학습에 직접 활용됩니다. 의학적으로 더 적절한 답변을 작성해주세요.", options: { color: C.dim } },
], {
  x: 5.5, y: 4.3, w: 3.8, h: 0.7,
  fontSize: 10, fontFace: "맑은 고딕", valign: "top", margin: 0, lineSpacingMultiple: 1.3,
});

// ── Slide 9: 커멘트 달기 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("5. 커멘트 달기", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.yellow, margin: 0,
});
s.addText("AI 응답의 특정 부분에 대해 전문가 의견을 남길 수 있습니다.", {
  x: 0.8, y: 0.85, w: 8.4, h: 0.4,
  fontSize: 13, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
// Left: steps
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.5, y: 1.4, w: 4.8, h: 3.8,
  fill: { color: C.surface }, rectRadius: 0.1,
});
const cmtSteps = [
  { n: "1", t: "응답 하단의 '커멘트 달기' 버튼 클릭" },
  { n: "2", t: "카테고리 선택 (부정확한 정보,\n불충분한 답변, 위험한 조언 등)" },
  { n: "3", t: "커멘트 내용을 입력합니다." },
  { n: "4", t: "'등록' 버튼을 클릭하면 저장됩니다." },
];
cmtSteps.forEach((step, i) => {
  s.addShape(pres.shapes.OVAL, {
    x: 0.8, y: 1.7 + i * 0.85, w: 0.35, h: 0.35,
    fill: { color: C.yellow },
  });
  s.addText(step.n, {
    x: 0.8, y: 1.7 + i * 0.85, w: 0.35, h: 0.35,
    fontSize: 12, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.t, {
    x: 1.35, y: 1.65 + i * 0.85, w: 3.7, h: 0.5,
    fontSize: 12, fontFace: "맑은 고딕", color: C.text, valign: "middle", margin: 0, lineSpacingMultiple: 1.2,
  });
});
// Right: categories
s.addText("커멘트 카테고리", {
  x: 5.6, y: 1.4, w: 4.0, h: 0.4,
  fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.yellow, margin: 0,
});
const cats = [
  { name: "부정확한 정보", desc: "의학적으로 틀린 내용" },
  { name: "불충분한 답변", desc: "빠진 정보가 있는 경우" },
  { name: "위험한 조언", desc: "환자에게 위험할 수 있는 내용" },
  { name: "면책 조항 누락", desc: "의료 면책 고지 없음" },
  { name: "과잉 진단/처방", desc: "진단이나 처방을 시도" },
  { name: "출처 불명확", desc: "근거 없는 주장" },
  { name: "표현 부적절", desc: "부적절한 표현 사용" },
  { name: "기타", desc: "기타 의견" },
];
cats.forEach((c, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.6, y: 1.9 + i * 0.42, w: 3.9, h: 0.35,
    fill: { color: i % 2 === 0 ? "2D3748" : C.surface }, rectRadius: 0.04,
  });
  s.addText(c.name, {
    x: 5.8, y: 1.9 + i * 0.42, w: 1.5, h: 0.35,
    fontSize: 10, fontFace: "맑은 고딕", bold: true, color: C.yellow, valign: "middle", margin: 0,
  });
  s.addText(c.desc, {
    x: 7.4, y: 1.9 + i * 0.42, w: 2.0, h: 0.35,
    fontSize: 10, fontFace: "맑은 고딕", color: C.dim, valign: "middle", margin: 0,
  });
});
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 5.6, y: 5.0, w: 3.9, h: 0.4,
  fill: { color: "1E3A5F" }, rectRadius: 0.05,
});
s.addText("커멘트는 RLHF 관리 > 커멘트 탭에서 모아 볼 수 있습니다.", {
  x: 5.8, y: 5.0, w: 3.5, h: 0.4,
  fontSize: 10, fontFace: "맑은 고딕", color: C.accent, valign: "middle", margin: 0,
});

// ── Slide 10: 시나리오 추출 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("6. 시나리오 추출 및 등록", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
s.addText("대화 중 발견한 유의미한 질문을 테스트 시나리오로 등록할 수 있습니다.", {
  x: 0.8, y: 0.85, w: 8.4, h: 0.4,
  fontSize: 13, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
const scSteps = [
  { n: "1", icon: "📋", t: "시나리오 추출 버튼 클릭", desc: "대화 상단에 위치한 '시나리오 추출'\n버튼을 클릭합니다." },
  { n: "2", icon: "✅", t: "추출할 턴 선택", desc: "대화 중 시나리오로 등록할\nQ&A 턴을 체크합니다." },
  { n: "3", icon: "🤖", t: "GPT 자동 분류 (선택)", desc: "체크하면 카테고리, 리스크 레벨을\nGPT가 자동으로 분류합니다." },
  { n: "4", icon: "✏️", t: "내용 확인 및 편집", desc: "카테고리, 리스크, 프롬프트,\n기대 동작, 태그를 편집합니다." },
  { n: "5", icon: "💾", t: "시나리오 저장", desc: "저장하면 시나리오 관리 페이지에\n등록됩니다." },
];
scSteps.forEach((step, i) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 1.4 + i * 0.8, w: 9.0, h: 0.7,
    fill: { color: C.surface }, rectRadius: 0.08,
  });
  s.addShape(pres.shapes.OVAL, {
    x: 0.7, y: 1.5 + i * 0.8, w: 0.4, h: 0.4,
    fill: { color: C.accent },
  });
  s.addText(step.n, {
    x: 0.7, y: 1.5 + i * 0.8, w: 0.4, h: 0.4,
    fontSize: 14, fontFace: "맑은 고딕", bold: true, color: C.bg, align: "center", valign: "middle", margin: 0,
  });
  s.addText(step.icon + " " + step.t, {
    x: 1.3, y: 1.45 + i * 0.8, w: 3.0, h: 0.35,
    fontSize: 13, fontFace: "맑은 고딕", bold: true, color: C.white, valign: "middle", margin: 0,
  });
  s.addText(step.desc, {
    x: 4.5, y: 1.45 + i * 0.8, w: 4.8, h: 0.55,
    fontSize: 11, fontFace: "맑은 고딕", color: C.dim, valign: "middle", margin: 0, lineSpacingMultiple: 1.2,
  });
});

// ── Slide 11: 시나리오 관리 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("6. 시나리오 관리 페이지", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const scImg = loadImg("03_scenario_manager.png");
if (scImg) {
  s.addImage({ data: scImg, x: 0.5, y: 1.0, w: 9.0, h: 4.2, sizing: { type: "contain", w: 9.0, h: 4.2 } });
}
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.5, y: 5.0, w: 9.0, h: 0.4,
  fill: { color: C.surface }, rectRadius: 0.05,
});
s.addText("추출된 시나리오는 '시나리오 관리' 페이지에서 카테고리별로 확인, 편집, 배치 테스트 실행이 가능합니다.", {
  x: 0.7, y: 5.0, w: 8.6, h: 0.4,
  fontSize: 11, fontFace: "맑은 고딕", color: C.dim, valign: "middle", margin: 0,
});

// ── Slide 12: RLHF 관리 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("7. RLHF 관리에서 결과 확인", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
s.addText("상단 메뉴의 'RLHF 관리'에서 수집된 피드백과 커멘트를 확인할 수 있습니다.", {
  x: 0.8, y: 0.85, w: 8.4, h: 0.4,
  fontSize: 13, fontFace: "맑은 고딕", color: C.dim, margin: 0,
});
const rlhfTabs = [
  { icon: "📊", name: "개요", desc: "총 피드백 수, 선호도 쌍, Export 대기,\n평균 Reward 통계를 한눈에 확인" },
  { icon: "📋", name: "피드백", desc: "테스터가 남긴 좋음/나쁨 피드백,\n별점, 태그, 메모를 시간순 조회" },
  { icon: "💬", name: "커멘트", desc: "채팅 테스터에서 달린 커멘트를\n카테고리별로 카드형태로 확인" },
  { icon: "📦", name: "Export", desc: "DPO 학습용 데이터를\nOpenAI/HuggingFace 포맷으로 내보내기" },
];
rlhfTabs.forEach((tab, i) => {
  const col = i % 2;
  const row = Math.floor(i / 2);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5 + col * 4.7, y: 1.5 + row * 1.9, w: 4.4, h: 1.6,
    fill: { color: C.surface }, rectRadius: 0.1,
  });
  s.addText(tab.icon, {
    x: 0.7 + col * 4.7, y: 1.6 + row * 1.9, w: 0.6, h: 0.6,
    fontSize: 30, fontFace: "맑은 고딕", align: "center", valign: "middle", margin: 0,
  });
  s.addText(tab.name, {
    x: 1.4 + col * 4.7, y: 1.65 + row * 1.9, w: 3.3, h: 0.4,
    fontSize: 16, fontFace: "맑은 고딕", bold: true, color: C.white, valign: "middle", margin: 0,
  });
  s.addText(tab.desc, {
    x: 1.4 + col * 4.7, y: 2.1 + row * 1.9, w: 3.3, h: 0.8,
    fontSize: 11, fontFace: "맑은 고딕", color: C.dim, valign: "top", margin: 0, lineSpacingMultiple: 1.3,
  });
});

// ── Slide 13: 전체 워크플로우 요약 ──
s = pres.addSlide();
s.background = { color: C.bg };
s.addText("전체 워크플로우 요약", {
  x: 0.8, y: 0.3, w: 8.4, h: 0.6,
  fontSize: 28, fontFace: "맑은 고딕", bold: true, color: C.accent, margin: 0,
});
const wfSteps = [
  { icon: "🔐", title: "회원가입 & 로그인", color: C.accent },
  { icon: "💬", title: "AI와 대화", color: C.green },
  { icon: "👍👎", title: "피드백 남기기", color: C.yellow },
  { icon: "📝", title: "커멘트 달기", color: C.yellow },
  { icon: "📋", title: "시나리오 등록", color: C.accent },
];
wfSteps.forEach((wf, i) => {
  const cx = 0.5 + i * 1.9;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: cx, y: 1.3, w: 1.7, h: 2.5,
    fill: { color: C.surface }, rectRadius: 0.1,
    line: { color: wf.color, width: 1.5 },
  });
  s.addText(wf.icon, {
    x: cx, y: 1.5, w: 1.7, h: 0.8,
    fontSize: 36, fontFace: "맑은 고딕", align: "center", valign: "middle", margin: 0,
  });
  s.addText(wf.title, {
    x: cx, y: 2.5, w: 1.7, h: 0.6,
    fontSize: 12, fontFace: "맑은 고딕", bold: true, color: wf.color, align: "center", valign: "middle", margin: 0,
  });
  s.addText(String(i + 1), {
    x: cx + 0.6, y: 3.3, w: 0.5, h: 0.4,
    fontSize: 18, fontFace: "맑은 고딕", bold: true, color: C.dim, align: "center", valign: "middle", margin: 0,
  });
  if (i < wfSteps.length - 1) {
    s.addText("→", {
      x: cx + 1.6, y: 1.9, w: 0.5, h: 0.5,
      fontSize: 20, fontFace: "맑은 고딕", color: C.dim, align: "center", valign: "middle", margin: 0,
    });
  }
});
// Bottom summary
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 0.5, y: 4.3, w: 9.0, h: 1.0,
  fill: { color: C.surface }, rectRadius: 0.1,
});
s.addText([
  { text: "수집된 피드백과 커멘트는 ", options: { color: C.dim } },
  { text: "RLHF 관리", options: { bold: true, color: C.accent } },
  { text: " 페이지에서 통합 확인되며, ", options: { color: C.dim } },
  { text: "DPO 학습 데이터", options: { bold: true, color: C.green } },
  { text: "로 Export하여 AI 성능 개선에 직접 활용됩니다.", options: { color: C.dim } },
], {
  x: 0.8, y: 4.5, w: 8.4, h: 0.6,
  fontSize: 13, fontFace: "맑은 고딕", valign: "middle", margin: 0,
});

// ── Slide 14: 문의 ──
s = pres.addSlide();
s.background = { color: C.dark };
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 5.625, fill: { color: C.bg } });
s.addText("감사합니다", {
  x: 0.8, y: 1.5, w: 8.4, h: 1.0,
  fontSize: 40, fontFace: "맑은 고딕", bold: true, color: C.accent, align: "center", valign: "middle", margin: 0,
});
s.addText("문의사항은 관리자에게 연락해 주세요.", {
  x: 0.8, y: 2.7, w: 8.4, h: 0.6,
  fontSize: 16, fontFace: "맑은 고딕", color: C.dim, align: "center", valign: "middle", margin: 0,
});
s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 3.0, y: 3.5, w: 4.0, h: 0.5,
  fill: { color: C.surface }, rectRadius: 0.08,
});
s.addText("SKIX — 나만의 주치의 팀", {
  x: 3.0, y: 3.5, w: 4.0, h: 0.5,
  fontSize: 13, fontFace: "맑은 고딕", color: C.text, align: "center", valign: "middle", margin: 0,
});

const outPath = path.join(__dirname, "테스터_사용_매뉴얼.pptx");
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("Created: " + outPath);
});
