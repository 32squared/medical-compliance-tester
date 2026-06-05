// 법률↑+문진↓ 격차 분석 PPT 생성
// 사용: NODE_PATH="$(npm root -g)" node reports/_make_consultation_gap_pptx.js
const pptxgen = require('pptxgenjs');

const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.title = '법률↑+문진↓ 점수 격차 분석 및 평가 기준 개선안';
pres.author = '의료 컴플라이언스 테스트 도구';

// ─── 색상 팔레트 (Ocean Gradient) ───
const C = {
  primary: '065A82',   // deep blue
  primary2: '1C7293',  // teal
  midnight: '21295C',  // 어두운 배경
  ice: 'E0F2FE',       // 연한 파랑 배경
  white: 'FFFFFF',
  bg: 'F8FAFC',
  text: '0F172A',
  textDim: '64748B',
  border: 'E2E8F0',
  surface: 'F1F5F9',
  // semantic
  green: '22C55E',
  yellow: 'EAB308',
  orange: 'F97316',
  red: 'DC2626',
  purple: '7C3AED',
};

// ─── 헬퍼: 슬라이드 타이틀 ───
function addTitle(slide, text, opts = {}) {
  slide.addText(text, {
    x: 0.5, y: 0.3, w: 9, h: 0.6,
    fontSize: 24, fontFace: 'Calibri', bold: true,
    color: opts.color || C.text, align: 'left', valign: 'middle',
    margin: 0,
  });
  // 아래쪽 얇은 라인 (강조)
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0.92, w: 0.6, h: 0.03,
    fill: { color: opts.lineColor || C.primary }, line: { type: 'none' },
  });
}

// ─── 헬퍼: 푸터 ───
function addFooter(slide, pageNum, totalPages) {
  slide.addText('법률↑+문진↓ 점수 격차 분석', {
    x: 0.5, y: 5.25, w: 4, h: 0.3,
    fontSize: 9, fontFace: 'Calibri', color: C.textDim, align: 'left',
  });
  slide.addText(`${pageNum} / ${totalPages}`, {
    x: 8.5, y: 5.25, w: 1, h: 0.3,
    fontSize: 9, fontFace: 'Calibri', color: C.textDim, align: 'right',
  });
}

// ============================================================
// 슬라이드 1: 표지
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.midnight };

  // 우측 장식 사각형 (강조 모티프)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 8.5, y: 0, w: 1.5, h: 5.625,
    fill: { color: C.primary }, line: { type: 'none' },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 9.3, y: 0, w: 0.7, h: 5.625,
    fill: { color: C.primary2 }, line: { type: 'none' },
  });

  // 카테고리 라벨
  s.addText('의료 컴플라이언스 분석 보고서', {
    x: 0.7, y: 1.4, w: 7, h: 0.4,
    fontSize: 12, fontFace: 'Calibri', color: C.ice,
    charSpacing: 2, bold: true,
  });

  // 메인 타이틀
  s.addText('법률 평가↑ + 문진 평가↓\n점수 격차 분석', {
    x: 0.7, y: 1.85, w: 7.5, h: 1.6,
    fontSize: 40, fontFace: 'Calibri', bold: true,
    color: C.white, valign: 'top',
  });

  // 부제목
  s.addText('및 문진 평가 기준 개선 방향', {
    x: 0.7, y: 3.4, w: 7.5, h: 0.5,
    fontSize: 22, fontFace: 'Calibri',
    color: C.ice,
  });

  // 메타 정보
  s.addText([
    { text: '대상 배치  ', options: { color: C.textDim, fontSize: 11 } },
    { text: 'job-20260521-000816-86071f (1,101건)', options: { color: C.white, fontSize: 11, bold: true, breakLine: true } },
    { text: '실행일  ', options: { color: C.textDim, fontSize: 11 } },
    { text: '2026-05-21 · PROD', options: { color: C.white, fontSize: 11, bold: true, breakLine: true } },
    { text: '평균 점수  ', options: { color: C.textDim, fontSize: 11 } },
    { text: '법률 95.2 / 문진 48.1 / 격차 47.0점', options: { color: C.white, fontSize: 11, bold: true } },
  ], {
    x: 0.7, y: 4.4, w: 7.5, h: 0.9,
    fontFace: 'Calibri',
  });
}

// ============================================================
// 슬라이드 2: 목차
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '목차');

  const sections = [
    { num: '01', title: '핵심 요약', desc: 'TL;DR · 4개 KPI · 4분면 분포' },
    { num: '02', title: '격차의 원인 — 정량 관찰', desc: '응답 길이 · 정보 수집 · 응급 시나리오' },
    { num: '03', title: '본질적 충돌인가?', desc: '두 가설 비교 · 좁은 충돌 영역 분석' },
    { num: '04', title: '평가 기준 수정 필요성', desc: '현행 유지 / 정밀화 영역 분리' },
    { num: '05', title: '수정 예정 항목 및 일정', desc: '4가지 정밀화 방안 · 적용 계획' },
  ];

  let y = 1.15;
  for (const sec of sections) {
    // 번호 박스
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.7, y: y, w: 0.7, h: 0.65,
      fill: { color: C.primary }, line: { type: 'none' },
    });
    s.addText(sec.num, {
      x: 0.7, y: y, w: 0.7, h: 0.65,
      fontSize: 20, fontFace: 'Calibri', bold: true,
      color: C.white, align: 'center', valign: 'middle', margin: 0,
    });

    // 제목 + 설명
    s.addText(sec.title, {
      x: 1.6, y: y, w: 7.5, h: 0.38,
      fontSize: 17, fontFace: 'Calibri', bold: true,
      color: C.text, margin: 0, valign: 'top',
    });
    s.addText(sec.desc, {
      x: 1.6, y: y + 0.38, w: 7.5, h: 0.28,
      fontSize: 12, fontFace: 'Calibri', color: C.textDim,
      margin: 0, valign: 'top',
    });

    y += 0.78;
  }

  addFooter(s, 2, 15);
}

// ============================================================
// 슬라이드 3: Executive Summary (TL;DR)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, 'Executive Summary');

  // 좌측: 카테고리 표시
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 0.1, h: 3.8,
    fill: { color: C.primary }, line: { type: 'none' },
  });

  s.addText('TL;DR · 한눈 요약', {
    x: 0.75, y: 1.2, w: 8, h: 0.4,
    fontSize: 12, fontFace: 'Calibri', bold: true,
    color: C.primary, charSpacing: 2, margin: 0,
  });

  s.addText([
    { text: '두 평가 기준의 본질적 충돌은 관찰되지 않습니다. ', options: { bold: true, color: C.primary } },
    { text: '법률 95.2 / 문진 48.1 / 격차 47점은 응답 길이·정보 수집 패턴의 영향이 더 큰 것으로 보입니다.', options: {} },
  ], {
    x: 0.75, y: 1.7, w: 8.7, h: 0.8,
    fontSize: 15, fontFace: 'Calibri', color: C.text, valign: 'top',
  });

  // 박스 3개 — 핵심 근거
  const boxes = [
    { x: 0.75, color: C.green, head: '양립 가능 증명',
      body: '응답 1000~1499자 구간(652건)에서 법률 94.3 + 문진 59.5 동시 달성' },
    { x: 3.95, color: C.orange, head: '회피 패턴 정량',
      body: '응답 0-299자 195건은 법률 97.7 + 문진 19.9 + 질문 1.5%만 포함' },
    { x: 7.15, color: C.red, head: '응급 평가 한계',
      body: 'CRITICAL 시나리오 78.5%가 짧은 응답 — 합리적이나 F등급 처리' },
  ];
  for (const b of boxes) {
    s.addShape(pres.shapes.RECTANGLE, {
      x: b.x, y: 2.7, w: 2.7, h: 1.8,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: b.x, y: 2.7, w: 2.7, h: 0.08,
      fill: { color: b.color }, line: { type: 'none' },
    });
    s.addText(b.head, {
      x: b.x + 0.15, y: 2.85, w: 2.4, h: 0.4,
      fontSize: 13, fontFace: 'Calibri', bold: true, color: b.color, margin: 0,
    });
    s.addText(b.body, {
      x: b.x + 0.15, y: 3.3, w: 2.4, h: 1.1,
      fontSize: 11, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
    });
  }

  // 하단 결론
  s.addText('→ 차기 평가 사이클에서 문진 평가 기준 정밀화 예정 (응급 차등 / 표현 가이드 / 위험도 가중)', {
    x: 0.75, y: 4.65, w: 8.7, h: 0.4,
    fontSize: 12, fontFace: 'Calibri', color: C.primary2,
  });

  addFooter(s, 3, 15);
}

// ============================================================
// 슬라이드 4: 핵심 KPI
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '01. 핵심 KPI');

  const kpis = [
    { val: '95.2', sub: '/ 100', label: '법률 평균 점수\n(GPT FinalScore)', color: C.green },
    { val: '48.1', sub: '/ 100', label: '문진 평균 점수\n(consultationEval)', color: C.red },
    { val: '−47.0', sub: '점', label: '두 점수 격차\n(법률 − 문진)', color: C.orange },
    { val: '−0.385', sub: '', label: 'Pearson 상관계수\n(약한 음의 상관)', color: C.purple },
  ];

  const startX = 0.5;
  const cardW = 2.2, cardH = 1.9, gap = 0.1;
  for (let i = 0; i < kpis.length; i++) {
    const k = kpis[i];
    const x = startX + i * (cardW + gap);
    // 카드 배경
    s.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.3, w: cardW, h: cardH,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    // 상단 색상 띠
    s.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.3, w: cardW, h: 0.12,
      fill: { color: k.color }, line: { type: 'none' },
    });
    // 큰 숫자
    s.addText([
      { text: k.val, options: { fontSize: 38, bold: true, color: k.color } },
      { text: ' ' + k.sub, options: { fontSize: 14, color: C.textDim } },
    ], {
      x: x, y: 1.55, w: cardW, h: 0.8,
      fontFace: 'Calibri', align: 'center', valign: 'middle', margin: 0,
    });
    // 라벨
    s.addText(k.label, {
      x: x + 0.1, y: 2.45, w: cardW - 0.2, h: 0.65,
      fontSize: 11, fontFace: 'Calibri', color: C.text,
      align: 'center', valign: 'top', margin: 0,
    });
  }

  // 하단 해석
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.55, w: 9, h: 1.5,
    fill: { color: C.ice }, line: { color: C.primary, width: 0.5 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.55, w: 0.08, h: 1.5,
    fill: { color: C.primary }, line: { type: 'none' },
  });
  s.addText('📊 해석', {
    x: 0.85, y: 3.65, w: 8, h: 0.3,
    fontSize: 12, fontFace: 'Calibri', bold: true, color: C.primary, margin: 0,
  });
  s.addText('법률 평가는 A등급 95.5% 도달로 안정화 단계 진입 (D/F 0건). 문진 평가는 A등급 0%, F등급 22.1% — 환자 정보 수집·구조적 접근에 개선 여지 큼. 약한 음의 상관(-0.385)은 응답 길이가 짧을수록 문진이 낮아지는 패턴이 강하게 나타남을 반영.', {
    x: 0.85, y: 3.97, w: 8.4, h: 1.0,
    fontSize: 11.5, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
  });

  addFooter(s, 4, 15);
}

// ============================================================
// 슬라이드 5: 4분면 분포
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '4분면 분포 — 기준선: 법률 ≥80, 문진 ≥70');

  // 2x2 격자
  const quads = [
    { x: 1.0, y: 1.35, w: 4.0, h: 1.7, val: '107건', pct: '9.7%',
      head: '법률↑ + 문진↑ (이상적)', desc: '두 기준 모두 충족 — 양립 가능 증명',
      bgFill: 'DCFCE7', color: C.green },
    { x: 5.2, y: 1.35, w: 4.0, h: 1.7, val: '986건', pct: '89.6%',
      head: '법률↑ + 문진↓ (현재 주류)', desc: '법률 우수, 문진 미흡 — 보수적 응답 패턴',
      bgFill: 'FEF3C7', color: C.yellow },
    { x: 1.0, y: 3.2, w: 4.0, h: 1.7, val: '0건', pct: '0.00%',
      head: '법률↓ + 문진↑ (충돌 영역)', desc: '거의 비어 있음 — 충돌 가설 반박 결정적 근거',
      bgFill: 'FEE2E2', color: C.red },
    { x: 5.2, y: 3.2, w: 4.0, h: 1.7, val: '7건', pct: '0.64%',
      head: '둘 다 미흡', desc: '단순 실패 케이스',
      bgFill: 'F1F5F9', color: C.textDim },
  ];

  for (const q of quads) {
    s.addShape(pres.shapes.RECTANGLE, {
      x: q.x, y: q.y, w: q.w, h: q.h,
      fill: { color: q.bgFill },
      line: { color: q.color, width: 1.5 },
    });
    // 큰 숫자
    s.addText([
      { text: q.val, options: { fontSize: 36, bold: true, color: q.color } },
      { text: '  ' + q.pct, options: { fontSize: 16, color: C.text, bold: true } },
    ], {
      x: q.x + 0.2, y: q.y + 0.15, w: q.w - 0.4, h: 0.7,
      fontFace: 'Calibri', valign: 'top', margin: 0,
    });
    // 제목 + 설명
    s.addText(q.head, {
      x: q.x + 0.2, y: q.y + 0.95, w: q.w - 0.4, h: 0.35,
      fontSize: 12, fontFace: 'Calibri', bold: true, color: C.text, margin: 0,
    });
    s.addText(q.desc, {
      x: q.x + 0.2, y: q.y + 1.3, w: q.w - 0.4, h: 0.4,
      fontSize: 10.5, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
    });
  }

  addFooter(s, 5, 15);
}

// ============================================================
// 슬라이드 6: 핵심 관찰 ① — 응답 길이별 점수
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '02. 격차 원인 ① — 응답 길이별 점수');

  // 표 데이터
  const headerStyle = { fill: { color: C.primary }, color: C.white, bold: true, fontSize: 11, fontFace: 'Calibri' };
  const cellStyle = { fontSize: 11, fontFace: 'Calibri', color: C.text };
  const tableData = [
    [
      { text: '응답 길이', options: headerStyle },
      { text: '건수', options: headerStyle },
      { text: '비율', options: headerStyle },
      { text: '법률 평균', options: headerStyle },
      { text: '문진 평균', options: headerStyle },
      { text: '질문 포함', options: headerStyle },
    ],
    [
      { text: '0–299자 (매우 짧음)', options: { ...cellStyle, bold: true, fill: { color: 'FEE2E2' } } },
      { text: '195', options: { ...cellStyle, fill: { color: 'FEE2E2' } } },
      { text: '17.7%', options: { ...cellStyle, fill: { color: 'FEE2E2' } } },
      { text: '97.7', options: { ...cellStyle, fill: { color: 'FEE2E2' }, color: C.green, bold: true } },
      { text: '19.9', options: { ...cellStyle, fill: { color: 'FEE2E2' }, color: C.red, bold: true } },
      { text: '1.5%', options: { ...cellStyle, fill: { color: 'FEE2E2' }, bold: true } },
    ],
    [
      { text: '300–599자', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
      { text: '109', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
      { text: '9.9%', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
      { text: '96.9', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
      { text: '21.0', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
      { text: '8.3%', options: { ...cellStyle, fill: { color: 'FEF3C7' } } },
    ],
    [
      { text: '600–999자', options: cellStyle },
      { text: '109', options: cellStyle },
      { text: '9.9%', options: cellStyle },
      { text: '94.4', options: cellStyle },
      { text: '53.8', options: cellStyle },
      { text: '81.7%', options: cellStyle },
    ],
    [
      { text: '1000–1499자 (균형)', options: { ...cellStyle, bold: true, fill: { color: 'DCFCE7' } } },
      { text: '652', options: { ...cellStyle, fill: { color: 'DCFCE7' } } },
      { text: '59.2%', options: { ...cellStyle, fill: { color: 'DCFCE7' } } },
      { text: '94.3', options: { ...cellStyle, fill: { color: 'DCFCE7' }, color: C.green, bold: true } },
      { text: '59.5', options: { ...cellStyle, fill: { color: 'DCFCE7' }, color: C.green, bold: true } },
      { text: '94.6%', options: { ...cellStyle, fill: { color: 'DCFCE7' }, bold: true } },
    ],
    [
      { text: '1500–1999자 (이상적)', options: { ...cellStyle, bold: true, fill: { color: 'DCFCE7' } } },
      { text: '34', options: { ...cellStyle, fill: { color: 'DCFCE7' } } },
      { text: '3.1%', options: { ...cellStyle, fill: { color: 'DCFCE7' } } },
      { text: '94.3', options: { ...cellStyle, fill: { color: 'DCFCE7' }, color: C.green, bold: true } },
      { text: '60.9', options: { ...cellStyle, fill: { color: 'DCFCE7' }, color: C.green, bold: true } },
      { text: '97.1%', options: { ...cellStyle, fill: { color: 'DCFCE7' }, bold: true } },
    ],
  ];

  s.addTable(tableData, {
    x: 0.5, y: 1.15, w: 9, colW: [2.4, 1.0, 1.0, 1.5, 1.5, 1.6],
    rowH: 0.36, fontSize: 11, fontFace: 'Calibri',
    border: { type: 'solid', pt: 0.5, color: C.border },
  });

  // 하단 해석
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.6, w: 9, h: 1.4,
    fill: { color: C.ice }, line: { color: C.primary, width: 0.5 },
  });
  s.addText('📊 해석', {
    x: 0.7, y: 3.7, w: 8, h: 0.3,
    fontSize: 11, fontFace: 'Calibri', bold: true, color: C.primary, margin: 0,
  });
  s.addText([
    { text: '• 짧은 응답 구간(0~299자)은 법률 97.7 + 문진 19.9 — 핵심 정보만 간결히 전달하는 패턴', options: { breakLine: true } },
    { text: '• 1000~1999자 구간은 법률 94+ + 문진 59~61 동시 달성 — ', options: {} },
    { text: '두 기준이 양립 가능한 구간 존재', options: { bold: true, color: C.green, breakLine: true } },
    { text: '• 법률 점수는 모든 길이 구간에서 93~97점으로 안정 — 응답 길이가 늘어도 법률 점수 저하 없음', options: {} },
  ], {
    x: 0.7, y: 3.98, w: 8.6, h: 0.95,
    fontSize: 11, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
  });

  addFooter(s, 6, 15);
}

// ============================================================
// 슬라이드 7: 핵심 관찰 ② — 환자 정보 수집 패턴
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '02. 격차 원인 ② — 환자 정보 수집 패턴');

  const headerStyle = { fill: { color: C.primary }, color: C.white, bold: true, fontSize: 11, fontFace: 'Calibri' };
  const cellStyle = { fontSize: 11, fontFace: 'Calibri', color: C.text };
  const redCellStyle = { ...cellStyle, color: C.red, bold: true };

  const tableData = [
    [
      { text: '환자 정보 요청 패턴', options: headerStyle },
      { text: '전체 (1,101건)', options: headerStyle },
      { text: '짧은 응답 <500자 (301건)', options: headerStyle },
      { text: '긴 응답 ≥1000자 (688건)', options: headerStyle },
    ],
    [
      { text: '복용 약물 확인', options: cellStyle },
      { text: '11.8%', options: cellStyle },
      { text: '1.3%', options: redCellStyle },
      { text: '16.1%', options: cellStyle },
    ],
    [
      { text: '기저질환 확인', options: cellStyle },
      { text: '8.9%', options: cellStyle },
      { text: '0.0%', options: redCellStyle },
      { text: '12.6%', options: cellStyle },
    ],
    [
      { text: '나이/성별 확인', options: cellStyle },
      { text: '6.2%', options: cellStyle },
      { text: '0.3%', options: redCellStyle },
      { text: '9.3%', options: cellStyle },
    ],
    [
      { text: '증상 강도 확인', options: cellStyle },
      { text: '12.3%', options: cellStyle },
      { text: '0.0%', options: redCellStyle },
      { text: '17.4%', options: cellStyle },
    ],
    [
      { text: '응답에 "?" 1개 이상 포함', options: { ...cellStyle, bold: true, fill: { color: 'FEF3C7' } } },
      { text: '67.9%', options: { ...cellStyle, bold: true, fill: { color: 'FEF3C7' } } },
      { text: '3.0%', options: { ...redCellStyle, fill: { color: 'FEF3C7' } } },
      { text: '93.3%', options: { ...cellStyle, bold: true, fill: { color: 'FEF3C7' } } },
    ],
  ];

  s.addTable(tableData, {
    x: 0.5, y: 1.15, w: 9, colW: [2.6, 1.8, 2.3, 2.3],
    rowH: 0.36, fontSize: 11, fontFace: 'Calibri',
    border: { type: 'solid', pt: 0.5, color: C.border },
  });

  // 핵심 관찰 박스
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.55, w: 9, h: 1.45,
    fill: { color: 'FEE2E2' }, line: { color: C.red, width: 0.5 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.55, w: 0.1, h: 1.45,
    fill: { color: C.red }, line: { type: 'none' },
  });
  s.addText('🔍 짧은 응답 301건의 결정적 특징', {
    x: 0.75, y: 3.65, w: 8.5, h: 0.35,
    fontSize: 12, fontFace: 'Calibri', bold: true, color: C.red, margin: 0,
  });
  s.addText([
    { text: '• 97.0%(292건)에 질문(?)이 포함되지 않음', options: { bold: true, breakLine: true } },
    { text: '• 기저질환·증상 강도 요청 ', options: {} },
    { text: '0.0%', options: { bold: true, color: C.red } },
    { text: ' / 나이·성별 0.3% / 복용약 1.3%', options: { breakLine: true } },
    { text: '• 이런 정보 요청은 의료법 27조와 ', options: {} },
    { text: '충돌하지 않는 질문 행위', options: { bold: true, color: C.red } },
    { text: '임에도 짧은 응답 구간에서 누락 빈도 매우 높음', options: {} },
  ], {
    x: 0.75, y: 3.97, w: 8.6, h: 1,
    fontSize: 11, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
  });

  addFooter(s, 7, 15);
}

// ============================================================
// 슬라이드 8: 핵심 관찰 ③ — 응급/CRITICAL 시나리오
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '02. 격차 원인 ③ — 응급/CRITICAL 시나리오 특성');

  // 좌측: 카테고리별 짧은 응답
  s.addText('카테고리별 짧은 응답(<500자) 비율', {
    x: 0.5, y: 1.15, w: 4.5, h: 0.3,
    fontSize: 12, fontFace: 'Calibri', bold: true, color: C.primary, margin: 0,
  });

  const catData = [
    { name: 'emergency', total: 278, short: 213, pct: 76.6, highlight: true },
    { name: 'edge', total: 75, short: 9, pct: 12.0 },
    { name: 'treatment', total: 118, short: 13, pct: 11.0 },
    { name: 'diagnosis', total: 217, short: 20, pct: 9.2 },
    { name: 'prescription', total: 138, short: 9, pct: 6.5 },
    { name: 'general', total: 169, short: 6, pct: 3.6 },
  ];
  let y = 1.55;
  for (const c of catData) {
    const barW = (c.pct / 100) * 2.5;
    s.addText(c.name, {
      x: 0.5, y: y, w: 1.4, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', bold: c.highlight, color: c.highlight ? C.red : C.text, margin: 0, valign: 'middle',
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 1.9, y: y + 0.05, w: 2.5, h: 0.2,
      fill: { color: C.surface }, line: { type: 'none' },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 1.9, y: y + 0.05, w: barW, h: 0.2,
      fill: { color: c.highlight ? C.red : C.primary2 }, line: { type: 'none' },
    });
    s.addText(`${c.pct}%`, {
      x: 4.5, y: y, w: 0.5, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', bold: c.highlight, color: c.highlight ? C.red : C.text, margin: 0, valign: 'middle',
    });
    y += 0.32;
  }

  // 우측: 위험도별
  s.addText('위험도별 짧은 응답 비율', {
    x: 5.3, y: 1.15, w: 4.5, h: 0.3,
    fontSize: 12, fontFace: 'Calibri', bold: true, color: C.primary, margin: 0,
  });
  const riskData = [
    { name: 'CRITICAL', total: 307, short: 241, pct: 78.5, highlight: true },
    { name: 'HIGH', total: 500, short: 55, pct: 11.0 },
    { name: 'MEDIUM', total: 205, short: 4, pct: 2.0 },
    { name: 'LOW', total: 89, short: 1, pct: 1.1 },
  ];
  y = 1.55;
  for (const r of riskData) {
    const barW = (r.pct / 100) * 2.5;
    s.addText(r.name, {
      x: 5.3, y: y, w: 1.4, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', bold: r.highlight, color: r.highlight ? C.red : C.text, margin: 0, valign: 'middle',
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.7, y: y + 0.05, w: 2.5, h: 0.2,
      fill: { color: C.surface }, line: { type: 'none' },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.7, y: y + 0.05, w: barW, h: 0.2,
      fill: { color: r.highlight ? C.red : C.primary2 }, line: { type: 'none' },
    });
    s.addText(`${r.pct}%`, {
      x: 9.3, y: y, w: 0.6, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', bold: r.highlight, color: r.highlight ? C.red : C.text, margin: 0, valign: 'middle',
    });
    y += 0.32;
  }

  // 하단 핵심 관찰
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.85, w: 9, h: 1.2,
    fill: { color: 'FEF3C7' }, line: { color: C.yellow, width: 0.5 },
  });
  s.addText('⚠️ 주요 관찰', {
    x: 0.7, y: 3.95, w: 8.5, h: 0.3,
    fontSize: 11, fontFace: 'Calibri', bold: true, color: '92400E', margin: 0,
  });
  s.addText('짧은 응답 301건 중 약 71%(213건)가 응급 카테고리에서 발생. CRITICAL 시나리오의 78.5%가 짧은 응답.\n응급 상황 짧은 응답은 의료적으로 합리적 (119/응급실 안내가 환자 안전에 더 유리). 그러나 현재 문진 평가가 응급과 일반 상담을 동일한 5축으로 평가하여 응급 안내 위주 응답이 낮게 평가되는 구조.', {
    x: 0.7, y: 4.25, w: 8.5, h: 0.85,
    fontSize: 11, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
  });

  addFooter(s, 8, 15);
}

// ============================================================
// 슬라이드 9: 두 가설 비교
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '03. 본질적 충돌인가? — 두 가설 비교');

  // 좌측: 충돌 가설
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 4.35, h: 3.4,
    fill: { color: 'FFF5F5' }, line: { color: C.red, width: 1 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 4.35, h: 0.5,
    fill: { color: C.red }, line: { type: 'none' },
  });
  s.addText('🅐  본질적 충돌 가설이 맞다면?', {
    x: 0.65, y: 1.2, w: 4.2, h: 0.5,
    fontSize: 13, fontFace: 'Calibri', bold: true, color: C.white, valign: 'middle', margin: 0,
  });
  s.addText([
    { text: '법률↓+문진↑ 케이스가 다수 분포해야 함 ', options: { bullet: true, breakLine: true } },
    { text: '(문진 가점이 법률 점수 저하를 유발)', options: { color: C.textDim, fontSize: 10, breakLine: true } },
    { text: '긴 응답일수록 법률 점수가 현저히 저하되어야 함', options: { bullet: true, breakLine: true } },
    { text: '이상적(법률↑+문진↑) 응답이 매우 드물어야 함', options: { bullet: true, breakLine: true } },
    { text: '평균 응답 길이별 점수가 역상관이어야 함', options: { bullet: true } },
  ], {
    x: 0.75, y: 1.85, w: 4.05, h: 2.7,
    fontSize: 11, fontFace: 'Calibri', color: C.text, valign: 'top', margin: 0,
    paraSpaceAfter: 3,
  });

  // 우측: 실제 데이터
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.15, y: 1.2, w: 4.35, h: 3.4,
    fill: { color: 'F0FDF4' }, line: { color: C.green, width: 1 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.15, y: 1.2, w: 4.35, h: 0.5,
    fill: { color: C.green }, line: { type: 'none' },
  });
  s.addText('🅑  실제 데이터에서 관찰된 양상', {
    x: 5.3, y: 1.2, w: 4.2, h: 0.5,
    fontSize: 13, fontFace: 'Calibri', bold: true, color: C.white, valign: 'middle', margin: 0,
  });
  s.addText([
    { text: '법률↓+문진↑ = ', options: { bullet: true } },
    { text: '0건 (0.00%)', options: { bold: true, color: C.green } },
    { text: ' — 충돌 가설 예측과 완전히 다름', options: { breakLine: true } },
    { text: '1000–1999자 응답에서 법률 94+ + 문진 59~61 ', options: { bullet: true } },
    { text: '동시 달성', options: { bold: true, color: C.green, breakLine: true } },
    { text: '이상적 응답 ', options: { bullet: true } },
    { text: '107건(9.7%) 실재', options: { bold: true, color: C.green } },
    { text: ' — 양립 가능 사례 확인', options: { breakLine: true } },
    { text: '법률 점수가 모든 길이 구간에서 93~97점 안정', options: { bullet: true } },
  ], {
    x: 5.4, y: 1.85, w: 4.05, h: 2.7,
    fontSize: 11, fontFace: 'Calibri', color: C.text, valign: 'top', margin: 0,
    paraSpaceAfter: 3,
  });

  // 하단 판단 (푸터 위로 올림)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.7, w: 9, h: 0.45,
    fill: { color: C.midnight }, line: { type: 'none' },
  });
  s.addText('판단: 응답 패턴(길이·정보 요청 빈도)이 격차의 주요 원인 — 두 기준은 양립 가능, 본질적 충돌 부재', {
    x: 0.7, y: 4.7, w: 8.7, h: 0.45,
    fontSize: 11.5, fontFace: 'Calibri', bold: true, color: C.white, valign: 'middle', margin: 0,
  });

  addFooter(s, 9, 15);
}

// ============================================================
// 슬라이드 10: 응답 패턴 관찰
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '03. End Point의 응답 패턴 — 관찰된 경향');

  const items = [
    { num: '1', head: '응급 상황 → 즉시 119/응급실 안내 중심의 간결한 응답',
      desc: '241건의 CRITICAL 케이스에서 관찰되는 의료적으로 적절한 패턴', color: C.red },
    { num: '2', head: '법률 위반 위험이 감지될 때 → 정보 제공 자제, 일반 안내로 마무리',
      desc: '예: "정확한 진단은 의료진과 상담하세요" 위주 응답', color: C.orange },
    { num: '3', head: '환자 정보 요청 단계 생략',
      desc: '짧은 응답에서 복용약·기저질환·증상 강도 정보 요청 빈도 거의 0%', color: C.yellow },
    { num: '4', head: '양립 표현 활용 여지',
      desc: '"고려해보실 수 있습니다", "○○가 의심됩니다" 같은 의료법 친화적 표현 활용 폭 확장 가능', color: C.primary2 },
    { num: '5', head: '법률 점수는 안정화 단계 도달',
      desc: '모든 길이 구간에서 93~97점, 평균 95.2점 · 추가 개선보다 문진 보강이 ROI 측면 유리', color: C.green },
  ];

  let y = 1.2;
  for (const it of items) {
    // 번호 원
    s.addShape(pres.shapes.OVAL, {
      x: 0.6, y: y + 0.05, w: 0.5, h: 0.5,
      fill: { color: it.color }, line: { type: 'none' },
    });
    s.addText(it.num, {
      x: 0.6, y: y + 0.05, w: 0.5, h: 0.5,
      fontSize: 16, fontFace: 'Calibri', bold: true,
      color: it.color === C.yellow ? '78350F' : C.white,
      align: 'center', valign: 'middle', margin: 0,
    });

    // 헤드
    s.addText(it.head, {
      x: 1.25, y: y, w: 8, h: 0.32,
      fontSize: 13, fontFace: 'Calibri', bold: true, color: C.text, margin: 0,
    });
    // 설명
    s.addText(it.desc, {
      x: 1.25, y: y + 0.35, w: 8, h: 0.35,
      fontSize: 11, fontFace: 'Calibri', color: C.textDim, margin: 0,
    });

    y += 0.78;
  }

  addFooter(s, 10, 15);
}

// ============================================================
// 슬라이드 11: 충돌 영역 분석
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '03. 실제 충돌이 잠재하는 좁은 영역 (10점 / 100점)');

  // 도넛 시각화 (대신 두 큰 영역 비교)
  // 좌: 충돌 없음 영역 85점
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 3.5, h: 3.7,
    fill: { color: 'DCFCE7' }, line: { color: C.green, width: 1 },
  });
  s.addText('85점 / 100점', {
    x: 0.5, y: 1.4, w: 3.5, h: 0.6,
    fontSize: 30, fontFace: 'Calibri', bold: true, color: C.green, align: 'center', margin: 0,
  });
  s.addText('충돌 없음 영역', {
    x: 0.5, y: 2.0, w: 3.5, h: 0.35,
    fontSize: 13, fontFace: 'Calibri', bold: true, color: C.green, align: 'center', margin: 0,
  });
  s.addText([
    { text: '증상 탐색  ', options: { color: C.textDim } },
    { text: '30점', options: { bold: true, breakLine: true } },
    { text: '위험 선별  ', options: { color: C.textDim } },
    { text: '25점', options: { bold: true, breakLine: true } },
    { text: '환자 맥락  ', options: { color: C.textDim } },
    { text: '20점', options: { bold: true, breakLine: true } },
    { text: '질문·정보수집  ', options: { color: C.textDim } },
    { text: '10점', options: { bold: true } },
  ], {
    x: 0.7, y: 2.55, w: 3.1, h: 1.7,
    fontSize: 12, fontFace: 'Calibri', color: C.text, valign: 'top', margin: 0,
    paraSpaceAfter: 4,
  });
  s.addText('환자에게 묻기 · 정보 수집은 의료법과 무관', {
    x: 0.5, y: 4.45, w: 3.5, h: 0.4,
    fontSize: 10, fontFace: 'Calibri', color: C.textDim, align: 'center', margin: 0,
  });

  // 우: 충돌 가능 영역 10점
  s.addShape(pres.shapes.RECTANGLE, {
    x: 4.2, y: 1.2, w: 5.3, h: 3.7,
    fill: { color: 'FEF3C7' }, line: { color: C.yellow, width: 1 },
  });
  s.addText('10점 / 100점', {
    x: 4.2, y: 1.4, w: 5.3, h: 0.6,
    fontSize: 30, fontFace: 'Calibri', bold: true, color: C.yellow, align: 'center', margin: 0,
  });
  s.addText('좁은 충돌 영역', {
    x: 4.2, y: 2.0, w: 5.3, h: 0.35,
    fontSize: 13, fontFace: 'Calibri', bold: true, color: C.orange, align: 'center', margin: 0,
  });

  // 표 형식으로 충돌 영역 항목
  const headerStyle = { fill: { color: C.yellow }, color: C.white, bold: true, fontSize: 10, fontFace: 'Calibri', margin: 0 };
  const cellStyle = { fontSize: 10, fontFace: 'Calibri', color: C.text, margin: 0 };
  const tdata = [
    [
      { text: '항목 (배점)', options: headerStyle },
      { text: '충돌 위험', options: headerStyle },
      { text: '양립 통로', options: headerStyle },
    ],
    [
      { text: '진료과 안내 (3점)', options: cellStyle },
      { text: '"○○과 가세요" = 위반', options: cellStyle },
      { text: '"고려해보실 수 있습니다"', options: { ...cellStyle, color: C.green } },
    ],
    [
      { text: '방문 시기 (2점)', options: cellStyle },
      { text: '"오늘 안에 가세요"', options: cellStyle },
      { text: '"지속되면 의료기관 방문"', options: { ...cellStyle, color: C.green } },
    ],
    [
      { text: '맞춤 답변 (5점)', options: cellStyle },
      { text: '"당신에게 ○○치료 필요"', options: cellStyle },
      { text: '"가능성·의심" 표현 우회', options: { ...cellStyle, color: C.green } },
    ],
  ];
  s.addTable(tdata, {
    x: 4.3, y: 2.5, w: 5.1, colW: [1.5, 1.9, 1.7],
    rowH: 0.36, fontSize: 10, fontFace: 'Calibri',
    border: { type: 'solid', pt: 0.5, color: C.border },
  });

  addFooter(s, 11, 15);
}

// ============================================================
// 슬라이드 12: 평가 기준 수정 필요성 검토
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '04. 평가 기준 수정 필요성 검토');

  // 좌: 현행 유지
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 4.35, h: 3.85,
    fill: { color: 'F0FDF4' }, line: { color: C.green, width: 1 },
  });
  s.addText('✓  현행 유지가 적절한 영역', {
    x: 0.65, y: 1.3, w: 4.2, h: 0.4,
    fontSize: 14, fontFace: 'Calibri', bold: true, color: C.green, margin: 0,
  });
  s.addText('총 85점 — 충돌 관찰 없음', {
    x: 0.65, y: 1.65, w: 4.2, h: 0.3,
    fontSize: 11, fontFace: 'Calibri', color: C.green, margin: 0,
  });
  s.addText([
    { text: '증상 탐색 (30점)  ', options: { bullet: true } },
    { text: '위치/양상/시기/강도/동반', options: { color: C.textDim, fontSize: 10, breakLine: true } },
    { text: '위험 선별 (25점)  ', options: { bullet: true } },
    { text: '응급 징후·red flag 확인', options: { color: C.textDim, fontSize: 10, breakLine: true } },
    { text: '환자 맥락 (20점)  ', options: { bullet: true } },
    { text: '나이/기저질환/복용약 요청', options: { color: C.textDim, fontSize: 10, breakLine: true } },
    { text: '질문 먼저·추가 질문 유도 (10점)  ', options: { bullet: true } },
    { text: '정보 수집 행위', options: { color: C.textDim, fontSize: 10 } },
  ], {
    x: 0.8, y: 2.0, w: 4.0, h: 2.9,
    fontSize: 11.5, fontFace: 'Calibri', color: C.text, valign: 'top', margin: 0,
    paraSpaceAfter: 4,
  });

  // 우: 정밀화 필요
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.15, y: 1.2, w: 4.35, h: 3.85,
    fill: { color: 'FEF3C7' }, line: { color: C.yellow, width: 1 },
  });
  s.addText('⚠  정밀화 필요 영역', {
    x: 5.3, y: 1.3, w: 4.2, h: 0.4,
    fontSize: 14, fontFace: 'Calibri', bold: true, color: '92400E', margin: 0,
  });
  s.addText('총 15점 + 응급 시나리오 평가 트랙', {
    x: 5.3, y: 1.65, w: 4.2, h: 0.3,
    fontSize: 11, fontFace: 'Calibri', color: '92400E', margin: 0,
  });

  // 3개 소항목
  const items = [
    { head: 'A. 응급/CRITICAL 차등 평가', body: '5축 일률 적용 → 응급 안내 위주 응답이 F등급 처리', color: C.red },
    { head: 'B. "맞춤 답변(5점)" 정의 명확화', body: '"개인화된 답변" 표현이 27조 "맞춤 치료 계획"과 혼동 가능', color: C.orange },
    { head: 'C. "적절한 안내(5점)" 위험도 가중', body: '응급 위험도에서 "○○과 진료 고려" 표현이 부적절할 수 있음', color: C.yellow },
  ];
  let y = 2.0;
  for (const it of items) {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.3, y: y, w: 0.05, h: 0.85,
      fill: { color: it.color }, line: { type: 'none' },
    });
    s.addText(it.head, {
      x: 5.45, y: y, w: 4.0, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', bold: true, color: C.text, margin: 0,
    });
    s.addText(it.body, {
      x: 5.45, y: y + 0.32, w: 4.0, h: 0.55,
      fontSize: 10, fontFace: 'Calibri', color: C.textDim, margin: 0, valign: 'top',
    });
    y += 0.95;
  }

  addFooter(s, 12, 15);
}

// ============================================================
// 슬라이드 13: 수정 예정 항목 (4가지)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '05. 수정 예정 — 차기 평가 사이클 (v1.0.1 → v1.1.0)');

  const items = [
    {
      num: '1',
      head: '응급 시나리오 별도 평가 트랙 신설',
      body: 'CRITICAL/emergency 시나리오는 "위험 선별 + 적절한 안내" 2축으로 재정규화',
      impact: '예상 영향: 응급 241건 평균 ~20점 → 65점+ 상승',
      color: C.primary,
    },
    {
      num: '2',
      head: '"맞춤 답변(5점)" 정의 재작성',
      body: '"수집된 정보를 반영한 일반 안내" + 가능성·고려·의심 어휘 권장',
      impact: '의료법 27조와의 표현상 혼동 제거',
      color: C.primary2,
    },
    {
      num: '3',
      head: '"적절한 안내(5점)" 위험도 가중 적용',
      body: 'CRITICAL → 응급 안내 강조 / MEDIUM·LOW → 진료과·시기 안내 강조',
      impact: '시나리오 위험도별 차등 평가로 합리성 강화',
      color: C.midnight,
    },
    {
      num: '4',
      head: '평가 가이드 문서 보강',
      body: '각 축 만점 예시 + 의료법 양립 표현 통로 명시 (고려/의심/상담 권장)',
      impact: '평가 일관성·예측 가능성 개선',
      color: '0F766E',
    },
  ];

  // 2x2 그리드
  const positions = [
    { x: 0.5, y: 1.2 }, { x: 5.15, y: 1.2 },
    { x: 0.5, y: 3.2 }, { x: 5.15, y: 3.2 },
  ];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const p = positions[i];

    s.addShape(pres.shapes.RECTANGLE, {
      x: p.x, y: p.y, w: 4.35, h: 1.85,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    // 좌측 색상 띠
    s.addShape(pres.shapes.RECTANGLE, {
      x: p.x, y: p.y, w: 0.1, h: 1.85,
      fill: { color: it.color }, line: { type: 'none' },
    });
    // 번호 원
    s.addShape(pres.shapes.OVAL, {
      x: p.x + 0.25, y: p.y + 0.2, w: 0.55, h: 0.55,
      fill: { color: it.color }, line: { type: 'none' },
    });
    s.addText(it.num, {
      x: p.x + 0.25, y: p.y + 0.2, w: 0.55, h: 0.55,
      fontSize: 18, fontFace: 'Calibri', bold: true,
      color: C.white, align: 'center', valign: 'middle', margin: 0,
    });
    // 헤드
    s.addText(it.head, {
      x: p.x + 0.95, y: p.y + 0.2, w: 3.3, h: 0.6,
      fontSize: 12.5, fontFace: 'Calibri', bold: true, color: C.text, margin: 0, valign: 'top',
    });
    // body
    s.addText(it.body, {
      x: p.x + 0.25, y: p.y + 0.85, w: 4.0, h: 0.5,
      fontSize: 10.5, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
    });
    // impact
    s.addText('→ ' + it.impact, {
      x: p.x + 0.25, y: p.y + 1.4, w: 4.0, h: 0.4,
      fontSize: 10, fontFace: 'Calibri', color: it.color, margin: 0, valign: 'top',
    });
  }

  addFooter(s, 13, 15);
}

// ============================================================
// 슬라이드 14: 결론
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  addTitle(s, '05. 결론 — 핵심 시사점');

  const concl = [
    { txt: '47점 격차는 두 평가 기준의 본질적 충돌보다 ', highlight: '응답 패턴 영향', tail: '이 더 큰 것으로 보임' },
    { txt: '법률↓+문진↑ 케이스 ', highlight: '0건(0.00%)', tail: ' — 충돌 가설 결정적 반박' },
    { txt: '응답 1000~1999자 구간(686건)에서 ', highlight: '법률 94+ + 문진 59~61 동시 달성', tail: '' },
    { txt: '법률 점수 ', highlight: '평균 95.2점 안정화 단계', tail: ' (A등급 95.5%, D/F 0건)' },
    { txt: '문진 85점 영역은 ', highlight: '현행 유지가 적절', tail: ', 10점 + 응급 평가 트랙 정밀화 필요' },
    { txt: '주요 개선 방향: ', highlight: '응답 템플릿에 환자 정보 질문 단계 추가', tail: ' (27조 위반 아님)' },
  ];

  let y = 1.2;
  for (let i = 0; i < concl.length; i++) {
    const c = concl[i];
    // 좌측 번호 + 작은 마커
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: y + 0.05, w: 0.06, h: 0.5,
      fill: { color: C.primary }, line: { type: 'none' },
    });
    s.addText(String(i + 1).padStart(2, '0'), {
      x: 0.65, y: y, w: 0.5, h: 0.4,
      fontSize: 16, fontFace: 'Calibri', bold: true, color: C.primary2, margin: 0,
    });
    // 본문
    const runs = [{ text: c.txt, options: {} }];
    if (c.highlight) runs.push({ text: c.highlight, options: { bold: true, color: C.primary } });
    if (c.tail) runs.push({ text: c.tail, options: {} });
    s.addText(runs, {
      x: 1.3, y: y, w: 8.2, h: 0.6,
      fontSize: 12.5, fontFace: 'Calibri', color: C.text, margin: 0, valign: 'top',
    });
    y += 0.64;
  }

  addFooter(s, 14, 15);
}

// ============================================================
// 슬라이드 15: 마무리 (다음 단계)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.midnight };

  // 우측 강조 색상 띠
  s.addShape(pres.shapes.RECTANGLE, {
    x: 9.3, y: 0, w: 0.7, h: 5.625,
    fill: { color: C.primary2 }, line: { type: 'none' },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 8.5, y: 0, w: 0.8, h: 5.625,
    fill: { color: C.primary }, line: { type: 'none' },
  });

  s.addText('NEXT STEPS', {
    x: 0.7, y: 1.0, w: 7.5, h: 0.4,
    fontSize: 13, fontFace: 'Calibri', color: C.ice, charSpacing: 3, bold: true,
  });

  s.addText('다음 단계 및 일정', {
    x: 0.7, y: 1.5, w: 7.5, h: 0.8,
    fontSize: 32, fontFace: 'Calibri', bold: true, color: C.white,
  });

  const steps = [
    { num: '01', label: '평가 기준 변경 작업', detail: 'v1.0.1 → v1.1.0 마이너 버전 업그레이드' },
    { num: '02', label: '동일 1,101건 재평가', detail: '새 기준 적용한 비교 분석 수행' },
    { num: '03', label: 'GPT 평가 프롬프트 반영', detail: '_build_consultation_prompt 업데이트' },
    { num: '04', label: '검증 후 운영 적용', detail: '비교 결과 검토 후 정식 배포' },
  ];

  let y = 2.5;
  for (const st of steps) {
    s.addText(st.num, {
      x: 0.7, y: y, w: 0.8, h: 0.4,
      fontSize: 18, fontFace: 'Calibri', bold: true, color: C.primary2, margin: 0,
    });
    s.addText(st.label, {
      x: 1.5, y: y, w: 6.7, h: 0.35,
      fontSize: 14, fontFace: 'Calibri', bold: true, color: C.white, margin: 0,
    });
    s.addText(st.detail, {
      x: 1.5, y: y + 0.32, w: 6.7, h: 0.3,
      fontSize: 11, fontFace: 'Calibri', color: C.ice, margin: 0,
    });
    y += 0.68;
  }

  // 하단 footer
  s.addText('의료 컴플라이언스 테스트 도구 · 2026', {
    x: 0.7, y: 5.2, w: 7, h: 0.3,
    fontSize: 9, fontFace: 'Calibri', color: C.textDim,
  });
}

// 저장
const outPath = require('path').resolve(__dirname, 'consultation_score_gap_analysis.pptx');
pres.writeFile({ fileName: outPath }).then(() => {
  const fs = require('fs');
  const size = fs.statSync(outPath).size;
  console.log(`✓ 작성 완료: ${outPath}`);
  console.log(`  크기: ${Math.round(size / 1024)} KB`);
});
