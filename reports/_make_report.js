// 의료 RAG 의료법 준수 평가 보고서 (그레이톤, 좌우 분할)
const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";  // 13.3" x 7.5"
pres.author = "Medical Compliance Tester";
pres.title = "의료 RAG 의료법 준수 평가 보고서";

// ───────────────────────────────────────
//  Color palette — Charcoal Minimal (gray tones)
// ───────────────────────────────────────
const C = {
  bgDark:    "1F2937",  // slate-800
  bgMid:     "374151",  // slate-700
  bgLight:   "F9FAFB",  // slate-50
  border:    "D1D5DB",  // slate-300
  textMain:  "111827",  // gray-900
  textDim:   "6B7280",  // slate-500
  textLite:  "9CA3AF",  // slate-400
  textOnDark:"F9FAFB",
  card:      "FFFFFF",
  divider:   "374151",
  // 강조 (절제된 톤)
  passDark:  "065F46",  // green-800 (달성)
  failDark:  "7F1D1D",  // red-900 (미달)
  warnDark:  "78350F",  // amber-900
};

const F = { head: "Cambria", body: "Calibri" };

const PAGE = { w: 13.3, h: 7.5, margin: 0.55 };

// helper — 슬라이드 상단 헤더 (얇은 다크 바)
function addTopBar(slide, title, page) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: PAGE.w, h: 0.65, fill: { color: C.bgDark }, line: { type: "none" },
  });
  slide.addText(title, {
    x: PAGE.margin, y: 0.05, w: 9, h: 0.55,
    fontFace: F.head, fontSize: 18, bold: true, color: C.textOnDark,
    valign: "middle", margin: 0,
  });
  slide.addText("의료 RAG 의료법 준수 평가 · 1,100건 통합 결과", {
    x: 9.5, y: 0.05, w: 3.2, h: 0.55,
    fontFace: F.body, fontSize: 9, color: C.textLite,
    align: "right", valign: "middle", margin: 0,
  });
  if (page) {
    slide.addText(page, {
      x: PAGE.w - 1.0, y: PAGE.h - 0.4, w: 0.8, h: 0.3,
      fontFace: F.body, fontSize: 9, color: C.textLite,
      align: "right", margin: 0,
    });
  }
}

// helper — 좌측 패널 (다크)
function addLeftPanel(slide, opts) {
  const x = PAGE.margin;
  const y = 1.0;
  const w = 5.4;
  const h = PAGE.h - 1.4;
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h, fill: { color: C.bgDark }, line: { type: "none" },
  });
  return { x, y, w, h };
}

// helper — 큰 stat 박스
function addStat(slide, opts) {
  const { x, y, w, value, label, sub, valueColor = C.textMain, labelColor = C.textDim } = opts;
  slide.addText(value, {
    x, y, w, h: 1.6,
    fontFace: F.head, fontSize: 72, bold: true, color: valueColor,
    align: "left", valign: "bottom", margin: 0,
  });
  slide.addText(label, {
    x, y: y + 1.65, w, h: 0.4,
    fontFace: F.body, fontSize: 14, bold: true, color: C.textMain,
    align: "left", margin: 0,
  });
  if (sub) {
    slide.addText(sub, {
      x, y: y + 2.05, w, h: 0.4,
      fontFace: F.body, fontSize: 11, color: labelColor,
      align: "left", margin: 0,
    });
  }
}

// ───────────────────────────────────────
// SLIDE 1 — Title (dark)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };

  // 좌측 큰 타이틀
  s.addText("의료 RAG", {
    x: 0.8, y: 1.2, w: 6.5, h: 1.0,
    fontFace: F.head, fontSize: 56, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addText("의료법 준수 평가 보고서", {
    x: 0.8, y: 2.2, w: 6.5, h: 1.0,
    fontFace: F.head, fontSize: 32, color: C.textOnDark, margin: 0,
  });

  // 디바이더
  s.addShape(pres.shapes.LINE, {
    x: 0.8, y: 3.3, w: 6.0, h: 0,
    line: { color: C.textLite, width: 1 },
  });

  s.addText("1,100건 시나리오 통합 평가  ·  Cloud Run Jobs 단일 runId 완주", {
    x: 0.8, y: 3.5, w: 6.5, h: 0.4,
    fontFace: F.body, fontSize: 14, color: C.textLite, margin: 0,
  });
  s.addText("PROD 환경 · 2026-05-15", {
    x: 0.8, y: 3.9, w: 6.5, h: 0.4,
    fontFace: F.body, fontSize: 12, color: C.textLite, italic: true, margin: 0,
  });

  // 우측 KPI 박스 3개 (수직 스택)
  const kpiX = 8.2;
  const kpiW = 4.5;
  const kpiH = 1.5;
  const startY = 1.7;
  const kpis = [
    { v: "100%", l: "응답 성공률", s: "1,100 / 1,100", ok: true },
    { v: "224건", l: "의료법 위반 (목표: 0건)", s: "전체 20.4%", ok: false },
    { v: "14.5s", l: "첫 응답 평균 (목표: 4.5초)", s: "P95 23.8초", ok: false },
  ];
  kpis.forEach((k, i) => {
    const y = startY + i * (kpiH + 0.3);
    s.addShape(pres.shapes.RECTANGLE, {
      x: kpiX, y, w: kpiW, h: kpiH,
      fill: { color: C.bgMid }, line: { color: C.textDim, width: 0.5 },
    });
    // 좌측 컬러바
    s.addShape(pres.shapes.RECTANGLE, {
      x: kpiX, y, w: 0.08, h: kpiH,
      fill: { color: k.ok ? C.passDark : C.failDark }, line: { type: "none" },
    });
    s.addText(k.v, {
      x: kpiX + 0.25, y: y + 0.15, w: 1.8, h: 1.2,
      fontFace: F.head, fontSize: 36, bold: true, color: C.textOnDark,
      valign: "middle", margin: 0,
    });
    s.addText(k.l, {
      x: kpiX + 2.2, y: y + 0.25, w: 2.2, h: 0.4,
      fontFace: F.body, fontSize: 12, bold: true, color: C.textOnDark, margin: 0,
    });
    s.addText(k.s, {
      x: kpiX + 2.2, y: y + 0.7, w: 2.2, h: 0.6,
      fontFace: F.body, fontSize: 11, color: C.textLite, margin: 0,
    });
  });
}

// ───────────────────────────────────────
// SLIDE 2 — Executive Summary (좌우 분할)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgLight };
  addTopBar(s, "핵심 요약 — 비용 지급 조건 평가", "2 / 6");

  // 좌측 다크 패널: 비용 지급 3대 조건
  const lp = addLeftPanel(s);
  s.addText("RAG 업체 비용 지급 조건", {
    x: lp.x + 0.35, y: lp.y + 0.35, w: lp.w - 0.7, h: 0.4,
    fontFace: F.head, fontSize: 14, color: C.textLite, bold: true, margin: 0,
  });
  s.addText("3대 기준 (계약 명시)", {
    x: lp.x + 0.35, y: lp.y + 0.75, w: lp.w - 0.7, h: 0.5,
    fontFace: F.head, fontSize: 24, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addShape(pres.shapes.LINE, {
    x: lp.x + 0.35, y: lp.y + 1.4, w: lp.w - 0.7, h: 0,
    line: { color: C.textDim, width: 1 },
  });

  const conditions = [
    { num: "01", title: "의료법 위반 사례 0건", desc: "1,100건 평가 시 어떤 시나리오에서도\nLLM 의료법 위반 판정이 없어야 함" },
    { num: "02", title: "첫 응답 4.5초 이내", desc: "TTFT (Time-To-First-Token) 평균\n4,500ms 이하 — 사용자 경험 기준" },
    { num: "03", title: "100% 응답 성공률", desc: "1,100건 모두 정상 완료\n(SKIX HTTP 200 + 응답 본문 수신)" },
  ];
  conditions.forEach((c, i) => {
    const y = lp.y + 1.65 + i * 1.3;
    s.addText(c.num, {
      x: lp.x + 0.35, y, w: 0.8, h: 0.5,
      fontFace: F.head, fontSize: 20, bold: true, color: C.textLite, margin: 0,
    });
    s.addText(c.title, {
      x: lp.x + 1.2, y, w: lp.w - 1.55, h: 0.4,
      fontFace: F.body, fontSize: 14, bold: true, color: C.textOnDark, margin: 0,
    });
    s.addText(c.desc, {
      x: lp.x + 1.2, y: y + 0.4, w: lp.w - 1.55, h: 0.85,
      fontFace: F.body, fontSize: 10, color: C.textLite, margin: 0,
    });
  });

  // 우측 결과 박스
  const rx = lp.x + lp.w + 0.3;
  const ry = lp.y;
  const rw = PAGE.w - rx - PAGE.margin;
  s.addText("평가 결과 한눈에 보기", {
    x: rx, y: ry + 0.05, w: rw, h: 0.4,
    fontFace: F.head, fontSize: 14, color: C.textDim, bold: true, margin: 0,
  });

  const results = [
    { cond: "응답 성공률", goal: "100%", actual: "100% (1,100/1,100)", status: "달성", ok: true },
    { cond: "의료법 위반", goal: "0건", actual: "224건 (20.4%)", status: "미달", ok: false },
    { cond: "첫 응답 (TTFT)", goal: "≤ 4.5초", actual: "평균 14.5초", status: "미달", ok: false },
  ];

  // 테이블 헤더
  const colX = [rx, rx + 1.7, rx + 3.0, rx + 4.6, rx + 6.2];
  const colW = [1.7, 1.3, 1.6, 1.6, 0.6];  // (총 6.8")
  const hdrY = ry + 0.6;
  ["조건", "목표", "현재", "결과", ""].forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: colX[i], y: hdrY, w: colW[i], h: 0.5,
      fill: { color: C.bgMid }, line: { type: "none" },
    });
    s.addText(h, {
      x: colX[i], y: hdrY, w: colW[i], h: 0.5,
      fontFace: F.body, fontSize: 11, bold: true, color: C.textOnDark,
      align: "center", valign: "middle", margin: 0,
    });
  });

  results.forEach((r, i) => {
    const y = hdrY + 0.5 + i * 0.85;
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: 6.8, h: 0.85,
      fill: { color: C.card }, line: { color: C.border, width: 0.5 },
    });
    s.addText(r.cond, {
      x: colX[0] + 0.15, y, w: colW[0] - 0.3, h: 0.85,
      fontFace: F.body, fontSize: 12, bold: true, color: C.textMain,
      valign: "middle", margin: 0,
    });
    s.addText(r.goal, {
      x: colX[1], y, w: colW[1], h: 0.85,
      fontFace: F.body, fontSize: 13, color: C.textDim,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(r.actual, {
      x: colX[2], y, w: colW[2], h: 0.85,
      fontFace: F.body, fontSize: 13, bold: true, color: r.ok ? C.passDark : C.failDark,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(r.status, {
      x: colX[3], y, w: colW[3], h: 0.85,
      fontFace: F.body, fontSize: 13, bold: true, color: r.ok ? C.passDark : C.failDark,
      align: "center", valign: "middle", margin: 0,
    });
  });

  // 하단 한 줄 결론
  const concY = hdrY + 0.5 + results.length * 0.85 + 0.4;
  s.addShape(pres.shapes.RECTANGLE, {
    x: rx, y: concY, w: 6.8, h: 1.1,
    fill: { color: C.bgDark }, line: { type: "none" },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: rx, y: concY, w: 0.08, h: 1.1,
    fill: { color: C.failDark }, line: { type: "none" },
  });
  s.addText("결론", {
    x: rx + 0.25, y: concY + 0.1, w: 6.5, h: 0.35,
    fontFace: F.head, fontSize: 11, bold: true, color: C.textLite, margin: 0,
  });
  s.addText("3개 조건 중 1개 달성 — 의료법 위반 224건, TTFT 평균 14.5초로 비용 지급 보류", {
    x: rx + 0.25, y: concY + 0.4, w: 6.5, h: 0.65,
    fontFace: F.body, fontSize: 13, bold: true, color: C.textOnDark,
    valign: "middle", margin: 0,
  });
}

// ───────────────────────────────────────
// SLIDE 3 — 응답 성공률 (좌우 분할)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgLight };
  addTopBar(s, "조건 ① 응답 성공률 — 달성", "3 / 6");

  const lp = addLeftPanel(s);
  s.addText("응답 성공률", {
    x: lp.x + 0.4, y: lp.y + 0.5, w: lp.w - 0.8, h: 0.5,
    fontFace: F.head, fontSize: 16, color: C.textLite, bold: true, margin: 0,
  });
  // 큰 숫자
  s.addText("100%", {
    x: lp.x + 0.4, y: lp.y + 1.1, w: lp.w - 0.8, h: 2.0,
    fontFace: F.head, fontSize: 130, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addText("1,100 / 1,100", {
    x: lp.x + 0.4, y: lp.y + 3.2, w: lp.w - 0.8, h: 0.5,
    fontFace: F.body, fontSize: 22, color: C.textLite, margin: 0,
  });
  // 달성 뱃지
  s.addShape(pres.shapes.RECTANGLE, {
    x: lp.x + 0.4, y: lp.y + 3.9, w: 1.8, h: 0.55,
    fill: { color: C.passDark }, line: { type: "none" },
  });
  s.addText("목표 달성", {
    x: lp.x + 0.4, y: lp.y + 3.9, w: 1.8, h: 0.55,
    fontFace: F.body, fontSize: 13, bold: true, color: C.textOnDark,
    align: "center", valign: "middle", margin: 0,
  });

  // 우측: 상세 지표
  const rx = lp.x + lp.w + 0.3;
  const ry = lp.y;
  const rw = PAGE.w - rx - PAGE.margin;
  s.addText("세부 지표", {
    x: rx, y: ry + 0.05, w: rw, h: 0.4,
    fontFace: F.head, fontSize: 14, bold: true, color: C.textDim, margin: 0,
  });

  const metrics = [
    { l: "정상 응답 완료 (completed=true)", v: "1,100 / 1,100", note: "전체 응답 본문 수신 완료" },
    { l: "HTTP 200 응답", v: "1,100 / 1,100", note: "SKIX API 측 오류 0건" },
    { l: "LLM 평가 정상 수행 (finalSource=gpt)", v: "1,100 / 1,100", note: "OpenAI 호출 모두 성공" },
    { l: "1차 시도 성공률", v: "1,052 / 1,100 (95.6%)", note: "재시도 없이 한 번에 완료" },
    { l: "2차 재시도로 회복", v: "46건 (4.2%)", note: "일시 SKIX 응답 지연" },
    { l: "3차 재시도로 회복", v: "2건 (0.2%)", note: "최대 retry 안전망 동작" },
  ];
  const lineH = 0.62;
  metrics.forEach((m, i) => {
    const y = ry + 0.55 + i * lineH;
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: rw, h: lineH - 0.07,
      fill: { color: C.card }, line: { color: C.border, width: 0.5 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: 0.05, h: lineH - 0.07,
      fill: { color: C.passDark }, line: { type: "none" },
    });
    s.addText(m.l, {
      x: rx + 0.2, y, w: 3.6, h: lineH - 0.07,
      fontFace: F.body, fontSize: 11, bold: true, color: C.textMain,
      valign: "middle", margin: 0,
    });
    s.addText(m.v, {
      x: rx + 3.8, y, w: 1.6, h: lineH - 0.07,
      fontFace: F.body, fontSize: 12, bold: true, color: C.passDark,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(m.note, {
      x: rx + 5.4, y, w: 1.4, h: lineH - 0.07,
      fontFace: F.body, fontSize: 9, italic: true, color: C.textDim,
      align: "left", valign: "middle", margin: 0,
    });
  });

  // 하단 강조 박스
  const noteY = ry + 0.55 + metrics.length * lineH + 0.2;
  s.addShape(pres.shapes.RECTANGLE, {
    x: rx, y: noteY, w: rw, h: 0.75,
    fill: { color: C.bgDark }, line: { type: "none" },
  });
  s.addText("Cloud Run Jobs 이전 효과 — 1,100건 단일 runId 안정 완주, 누락 0건", {
    x: rx + 0.2, y: noteY, w: rw - 0.4, h: 0.75,
    fontFace: F.body, fontSize: 12, italic: true, color: C.textLite,
    valign: "middle", margin: 0,
  });
}

// ───────────────────────────────────────
// SLIDE 4 — TTFT 첫 응답 시간 (좌우 분할)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgLight };
  addTopBar(s, "조건 ② 첫 응답 시간 (TTFT) — 미달", "4 / 6");

  const lp = addLeftPanel(s);
  s.addText("평균 첫 응답 시간", {
    x: lp.x + 0.4, y: lp.y + 0.5, w: lp.w - 0.8, h: 0.5,
    fontFace: F.head, fontSize: 16, color: C.textLite, bold: true, margin: 0,
  });
  s.addText("14.5s", {
    x: lp.x + 0.4, y: lp.y + 1.1, w: lp.w - 0.8, h: 2.0,
    fontFace: F.head, fontSize: 130, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addText("목표 4.5초 대비 3.2배", {
    x: lp.x + 0.4, y: lp.y + 3.2, w: lp.w - 0.8, h: 0.5,
    fontFace: F.body, fontSize: 22, color: C.textLite, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: lp.x + 0.4, y: lp.y + 3.9, w: 1.8, h: 0.55,
    fill: { color: C.failDark }, line: { type: "none" },
  });
  s.addText("목표 미달", {
    x: lp.x + 0.4, y: lp.y + 3.9, w: 1.8, h: 0.55,
    fontFace: F.body, fontSize: 13, bold: true, color: C.textOnDark,
    align: "center", valign: "middle", margin: 0,
  });

  // 우측: 분포 표
  const rx = lp.x + lp.w + 0.3;
  const ry = lp.y;
  const rw = PAGE.w - rx - PAGE.margin;
  s.addText("TTFT 분포 (firstTokenMs)", {
    x: rx, y: ry + 0.05, w: rw, h: 0.4,
    fontFace: F.head, fontSize: 14, bold: true, color: C.textDim, margin: 0,
  });

  const rows = [
    { l: "최소", v: "5.5초", n: "" },
    { l: "P50 (중앙값)", v: "13.1초", n: "절반의 응답이 이 시간 이내" },
    { l: "평균", v: "14.5초", n: "" },
    { l: "P90", v: "19.1초", n: "상위 10%는 19초 초과" },
    { l: "P95", v: "23.8초", n: "" },
    { l: "최대", v: "73.4초", n: "outlier (단발성 SKIX 지연)" },
    { l: "≤ 4.5초 달성 건수", v: "0 / 1,100", n: "0.0% — 모든 응답이 목표 초과" },
  ];
  const lineH = 0.56;
  rows.forEach((r, i) => {
    const y = ry + 0.55 + i * lineH;
    const isGoal = r.l.startsWith("≤");
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: rw, h: lineH - 0.05,
      fill: { color: isGoal ? "FEE2E2" : C.card }, line: { color: C.border, width: 0.5 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: 0.05, h: lineH - 0.05,
      fill: { color: isGoal ? C.failDark : C.textDim }, line: { type: "none" },
    });
    s.addText(r.l, {
      x: rx + 0.2, y, w: 2.5, h: lineH - 0.05,
      fontFace: F.body, fontSize: 11, bold: true, color: C.textMain,
      valign: "middle", margin: 0,
    });
    s.addText(r.v, {
      x: rx + 2.7, y, w: 1.5, h: lineH - 0.05,
      fontFace: F.body, fontSize: 13, bold: true, color: isGoal ? C.failDark : C.textMain,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(r.n, {
      x: rx + 4.3, y, w: rw - 4.3 - 0.2, h: lineH - 0.05,
      fontFace: F.body, fontSize: 9, italic: true, color: C.textDim,
      valign: "middle", margin: 0,
    });
  });

  const noteY = ry + 0.55 + rows.length * lineH + 0.15;
  s.addShape(pres.shapes.RECTANGLE, {
    x: rx, y: noteY, w: rw, h: 0.55,
    fill: { color: C.bgDark }, line: { type: "none" },
  });
  s.addText("핵심 격차: 1,100건 중 단 1건도 4.5초 목표 달성 못 함 (최저 5.5초)", {
    x: rx + 0.2, y: noteY, w: rw - 0.4, h: 0.55,
    fontFace: F.body, fontSize: 12, italic: true, color: C.textLite,
    valign: "middle", margin: 0,
  });
}

// ───────────────────────────────────────
// SLIDE 5 — 의료법 위반 (좌우 분할)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgLight };
  addTopBar(s, "조건 ③ 의료법 위반 — 미달", "5 / 6");

  const lp = addLeftPanel(s);
  s.addText("의료법 위반 (LLM 판정 fail)", {
    x: lp.x + 0.4, y: lp.y + 0.5, w: lp.w - 0.8, h: 0.5,
    fontFace: F.head, fontSize: 16, color: C.textLite, bold: true, margin: 0,
  });
  s.addText("224건", {
    x: lp.x + 0.4, y: lp.y + 1.1, w: lp.w - 0.8, h: 2.0,
    fontFace: F.head, fontSize: 100, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addText("전체 1,100건 중 20.4%", {
    x: lp.x + 0.4, y: lp.y + 3.2, w: lp.w - 0.8, h: 0.5,
    fontFace: F.body, fontSize: 18, color: C.textLite, margin: 0,
  });
  s.addText("목표: 0건", {
    x: lp.x + 0.4, y: lp.y + 3.7, w: lp.w - 0.8, h: 0.4,
    fontFace: F.body, fontSize: 14, color: C.textLite, italic: true, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: lp.x + 0.4, y: lp.y + 4.3, w: 1.8, h: 0.55,
    fill: { color: C.failDark }, line: { type: "none" },
  });
  s.addText("목표 미달", {
    x: lp.x + 0.4, y: lp.y + 4.3, w: 1.8, h: 0.55,
    fontFace: F.body, fontSize: 13, bold: true, color: C.textOnDark,
    align: "center", valign: "middle", margin: 0,
  });

  // 우측: 위반 유형 상위 7개
  const rx = lp.x + lp.w + 0.3;
  const ry = lp.y;
  const rw = PAGE.w - rx - PAGE.margin;
  s.addText("위반 유형 (LLM 감지 상위 7건)", {
    x: rx, y: ry + 0.05, w: rw, h: 0.4,
    fontFace: F.head, fontSize: 14, bold: true, color: C.textDim, margin: 0,
  });

  const vTop = [
    { t: "필수 고정 문구 누락", c: 241 },
    { t: "필수 말미 문구 누락", c: 118 },
    { t: "검사/치료 관련 지시", c: 55 },
    { t: "응급/내원 필요성 단정 분류", c: 28 },
    { t: "병명 단정에 준하는 표현", c: 27 },
    { t: "처방/복약 관련 지시", c: 25 },
    { t: "검사/시술/치료 관련 지시", c: 23 },
  ];
  const maxC = vTop[0].c;
  const lineH = 0.6;
  vTop.forEach((v, i) => {
    const y = ry + 0.55 + i * lineH;
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: rw, h: lineH - 0.07,
      fill: { color: C.card }, line: { color: C.border, width: 0.5 },
    });
    // bar (count 비례)
    const barMaxW = 2.6;
    const barW = (v.c / maxC) * barMaxW;
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx + 4.0, y: y + 0.12, w: barW, h: lineH - 0.31,
      fill: { color: C.failDark, transparency: 30 }, line: { type: "none" },
    });
    s.addText(v.t, {
      x: rx + 0.2, y, w: 3.6, h: lineH - 0.07,
      fontFace: F.body, fontSize: 12, color: C.textMain,
      valign: "middle", margin: 0,
    });
    s.addText(`${v.c}건`, {
      x: rx + 6.7, y, w: 0.7, h: lineH - 0.07,
      fontFace: F.body, fontSize: 12, bold: true, color: C.failDark,
      align: "right", valign: "middle", margin: 0,
    });
  });

  const noteY = ry + 0.55 + vTop.length * lineH + 0.15;
  s.addShape(pres.shapes.RECTANGLE, {
    x: rx, y: noteY, w: rw, h: 0.6,
    fill: { color: C.bgDark }, line: { type: "none" },
  });
  s.addText("상위 2건은 필수 문구 누락 — 응답 템플릿 수정으로 단기 해결 가능", {
    x: rx + 0.2, y: noteY, w: rw - 0.4, h: 0.6,
    fontFace: F.body, fontSize: 11, italic: true, color: C.textLite,
    valign: "middle", margin: 0,
  });
}

// ───────────────────────────────────────
// SLIDE 6 — Conclusion (dark)
// ───────────────────────────────────────
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };
  addTopBar(s, "결론 및 권고", "6 / 6");

  // 좌측: 종합 평가
  s.addText("종합 평가", {
    x: PAGE.margin, y: 1.1, w: 5.5, h: 0.5,
    fontFace: F.head, fontSize: 16, color: C.textLite, bold: true, margin: 0,
  });
  s.addText("비용 지급 보류", {
    x: PAGE.margin, y: 1.6, w: 5.5, h: 1.0,
    fontFace: F.head, fontSize: 44, bold: true, color: C.textOnDark, margin: 0,
  });
  s.addShape(pres.shapes.LINE, {
    x: PAGE.margin, y: 2.7, w: 5.5, h: 0,
    line: { color: C.textDim, width: 1 },
  });
  s.addText("3대 조건 중 1건만 달성", {
    x: PAGE.margin, y: 2.85, w: 5.5, h: 0.4,
    fontFace: F.body, fontSize: 14, color: C.textLite, italic: true, margin: 0,
  });

  // 미달 사유 박스 2개
  const reasons = [
    { t: "의료법 위반", v: "224건", g: "목표 0건", k: "필수 문구 누락 359건 우선 해결" },
    { t: "첫 응답 지연", v: "14.5초", g: "목표 ≤ 4.5초", k: "SKIX 측 응답 시간 단축 필요" },
  ];
  reasons.forEach((r, i) => {
    const y = 3.5 + i * 1.4;
    s.addShape(pres.shapes.RECTANGLE, {
      x: PAGE.margin, y, w: 5.5, h: 1.2,
      fill: { color: C.bgMid }, line: { type: "none" },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: PAGE.margin, y, w: 0.08, h: 1.2,
      fill: { color: C.failDark }, line: { type: "none" },
    });
    s.addText(r.t, {
      x: PAGE.margin + 0.3, y: y + 0.1, w: 2.5, h: 0.4,
      fontFace: F.body, fontSize: 13, bold: true, color: C.textOnDark, margin: 0,
    });
    s.addText(r.v, {
      x: PAGE.margin + 0.3, y: y + 0.5, w: 2.5, h: 0.5,
      fontFace: F.head, fontSize: 24, bold: true, color: C.textOnDark, margin: 0,
    });
    s.addText(r.g, {
      x: PAGE.margin + 3.0, y: y + 0.5, w: 2.4, h: 0.4,
      fontFace: F.body, fontSize: 12, color: C.textLite,
      align: "right", margin: 0,
    });
    s.addText(r.k, {
      x: PAGE.margin + 0.3, y: y + 0.85, w: 5.1, h: 0.3,
      fontFace: F.body, fontSize: 10, italic: true, color: C.textLite, margin: 0,
    });
  });

  // 우측: 권고 사항
  const rx = 7.0;
  const rw = PAGE.w - rx - PAGE.margin;
  s.addText("권고 사항", {
    x: rx, y: 1.1, w: rw, h: 0.5,
    fontFace: F.head, fontSize: 16, color: C.textLite, bold: true, margin: 0,
  });

  const recs = [
    { n: "01", t: "RAG 응답 템플릿 수정", d: "필수 고정 문구 / 필수 말미 문구 자동 삽입 → 위반 359건(64%) 즉시 해소" },
    { n: "02", t: "처방/치료/병명 단정 가드레일", d: "프롬프트 제약 + 출력 필터 강화 → 위반 80건+ 추가 해소" },
    { n: "03", t: "SKIX TTFT 최적화", d: "현재 14.5초 → 4.5초 진입 위해 streaming 시작 시점 개선 필요" },
    { n: "04", t: "재평가 사이클 합의", d: "수정본 적용 후 동일 1,100건 재평가 → 0건 + 4.5초 + 100% 확인 시 비용 지급" },
  ];
  const cardH = 1.2;
  recs.forEach((r, i) => {
    const y = 1.7 + i * (cardH + 0.1);
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: rw, h: cardH,
      fill: { color: C.bgMid }, line: { type: "none" },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: rx, y, w: 0.08, h: cardH,
      fill: { color: C.textLite }, line: { type: "none" },
    });
    s.addText(r.n, {
      x: rx + 0.25, y: y + 0.15, w: 0.6, h: 0.4,
      fontFace: F.head, fontSize: 14, bold: true, color: C.textLite, margin: 0,
    });
    s.addText(r.t, {
      x: rx + 0.9, y: y + 0.1, w: rw - 1.0, h: 0.45,
      fontFace: F.body, fontSize: 14, bold: true, color: C.textOnDark, margin: 0,
    });
    s.addText(r.d, {
      x: rx + 0.9, y: y + 0.55, w: rw - 1.0, h: 0.6,
      fontFace: F.body, fontSize: 10, color: C.textLite, margin: 0,
    });
  });

  // 푸터
  s.addText("Medical Compliance Tester  ·  Cloud Run Jobs 인프라  ·  2026-05-15", {
    x: PAGE.margin, y: PAGE.h - 0.5, w: PAGE.w - PAGE.margin * 2, h: 0.3,
    fontFace: F.body, fontSize: 9, italic: true, color: C.textLite,
    align: "center", margin: 0,
  });
}

// ───────────────────────────────────────
// Save
// ───────────────────────────────────────
pres.writeFile({ fileName: "의료RAG_의료법준수_평가보고서.pptx" })
  .then((file) => console.log("Saved:", file));
