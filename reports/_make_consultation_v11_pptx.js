/* eslint-disable */
// 문진 평가 기준서 v1.1 — 자문 의견 반영 결과 (PPT, 2장 압축)
// 슬라이드 1: 자문위원 의견 / 슬라이드 2: v1.1 반영 내용

const fs = require('fs');
const path = require('path');
const PptxGenJS = require('pptxgenjs');

const C = {
  primary: '15803D',
  accent: '22C55E',
  light: 'DCFCE7',
  bg: 'F8FAFC',
  text: '0F172A',
  textDim: '64748B',
  border: 'CBD5E1',
  white: 'FFFFFF',
};

const FONT = 'Malgun Gothic';

const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE'; // 13.33 x 7.5 inch
pptx.title = '문진 평가 기준서 v1.1 — 자문 의견 반영';
pptx.subject = 'AI 건강상담 서비스 의료법 준수 평가 기준 개정';
pptx.author = 'Claude';

// ════════════════════════════════════════════════════════
// 슬라이드 1: 자문위원 의견
// ════════════════════════════════════════════════════════
{
  const s = pptx.addSlide();
  s.background = { color: C.white };

  // 헤더 띠
  s.addShape('rect', { x: 0, y: 0, w: 13.33, h: 0.5, fill: { color: C.primary } });
  s.addShape('rect', { x: 0, y: 0.5, w: 13.33, h: 0.08, fill: { color: C.accent } });

  // 타이틀
  s.addText('문진 평가 기준서 v1.1', {
    x: 0.5, y: 0.7, w: 9, h: 0.55,
    fontFace: FONT, fontSize: 26, color: C.primary, bold: true,
  });
  s.addText('자문위원 의견 — 7명 전문의의 검토 결과', {
    x: 0.5, y: 1.25, w: 9, h: 0.4,
    fontFace: FONT, fontSize: 15, color: C.textDim,
  });

  // 우측 메타 배지
  s.addShape('roundRect', {
    x: 10, y: 0.85, w: 2.85, h: 0.7,
    fill: { color: C.light }, line: { color: C.accent, width: 1 },
    rectRadius: 0.08,
  });
  s.addText('근거: 렉스소프트㈜', {
    x: 10, y: 0.88, w: 2.85, h: 0.3,
    fontFace: FONT, fontSize: 11, color: C.primary, bold: true, align: 'center',
  });
  s.addText('검토 의견서 (2026-06-01)', {
    x: 10, y: 1.18, w: 2.85, h: 0.35,
    fontFace: FONT, fontSize: 11, color: C.text, align: 'center',
  });

  // 7명 자문위원 카드 — 4 + 3 배치
  const advisors = [
    { name: '오범조', dept: '가정의학과', opinion: '"무엇을 해야 하는지" 안내가 가장 중요\n응급 안내 누락은 감점되어야 함' },
    { name: '홍승노', dept: '이비인후과', opinion: '응급 징후 / 경고 징후 통합 필요\n중복 평가 줄이기' },
    { name: '이준엽', dept: '내분비내과', opinion: '암 의심 · 심부전 · 패혈증 등\n중증 가능성 별도 확인 필요' },
    { name: '백은혜', dept: '한의학', opinion: '증상에 따라 중요 질문이 다름\n근골격 / 내과 등 증상군별 차등' },
    { name: '원성호', dept: '보건의학과', opinion: '"3가지만 여쭐게요"식\n능동적·부담 낮춘 문진' },
    { name: '최영호', dept: '응급의학과', opinion: '이미 제공된 정보를\n다시 묻지 않기' },
    { name: '양현종', dept: '소아청소년과', opinion: '국내 진료환경·의료법\n맞춤 기준 필요' },
  ];

  advisors.forEach((a, i) => {
    const col = i % 4;
    const ro = Math.floor(i / 4);
    const x = 0.5 + col * 3.15;
    const y = 1.9 + ro * 2.55;
    // 카드
    s.addShape('roundRect', {
      x, y, w: 3, h: 2.4,
      fill: { color: C.white }, line: { color: C.accent, width: 1.2 },
      rectRadius: 0.1,
    });
    // 헤더 바
    s.addShape('rect', { x, y, w: 3, h: 0.65, fill: { color: C.primary } });
    s.addText(a.name, {
      x: x + 0.15, y: y + 0.05, w: 2, h: 0.55,
      fontFace: FONT, fontSize: 16, color: C.white, bold: true, valign: 'middle',
    });
    s.addText(a.dept, {
      x: x + 0.15, y: y + 0.05, w: 2.7, h: 0.55,
      fontFace: FONT, fontSize: 11, color: C.light, align: 'right', valign: 'middle',
    });
    // 의견
    s.addText(a.opinion, {
      x: x + 0.2, y: y + 0.8, w: 2.6, h: 1.5,
      fontFace: FONT, fontSize: 12, color: C.text, valign: 'top',
      paraSpaceAfter: 4,
    });
  });

  // 하단 핵심 메시지
  s.addShape('roundRect', {
    x: 0.5, y: 6.95, w: 12.33, h: 0.42,
    fill: { color: C.light }, line: { color: C.accent, width: 1 },
    rectRadius: 0.05,
  });
  s.addText('🎯 평가 기준의 목표 전환 — "질문을 얼마나 했는가" → "환자가 안전하게, 다음 행동을 명확히 알 수 있는 답변인가"', {
    x: 0.6, y: 6.95, w: 12.13, h: 0.42,
    fontFace: FONT, fontSize: 12.5, color: C.primary, bold: true, valign: 'middle',
  });
}

// ════════════════════════════════════════════════════════
// 슬라이드 2: 자문 의견 → v1.1 반영 내용
// ════════════════════════════════════════════════════════
{
  const s = pptx.addSlide();
  s.background = { color: C.white };

  s.addShape('rect', { x: 0, y: 0, w: 13.33, h: 0.5, fill: { color: C.primary } });
  s.addShape('rect', { x: 0, y: 0.5, w: 13.33, h: 0.08, fill: { color: C.accent } });

  s.addText('자문 의견이 v1.1에 어떻게 반영되었나요?', {
    x: 0.5, y: 0.7, w: 9, h: 0.55,
    fontFace: FONT, fontSize: 24, color: C.primary, bold: true,
  });
  s.addText('자문위원 8개 핵심 의견 → 평가 기준에 직접 반영', {
    x: 0.5, y: 1.25, w: 9, h: 0.4,
    fontFace: FONT, fontSize: 14, color: C.textDim,
  });

  // 우측: 총점 유지 배지
  s.addShape('roundRect', {
    x: 10, y: 0.85, w: 2.85, h: 0.7,
    fill: { color: C.primary }, line: { color: C.primary, width: 0 },
    rectRadius: 0.08,
  });
  s.addText('총점 100점 유지', {
    x: 10, y: 0.88, w: 2.85, h: 0.3,
    fontFace: FONT, fontSize: 11, color: C.light, bold: true, align: 'center',
  });
  s.addText('비중 재조정 · 18개 항목', {
    x: 10, y: 1.18, w: 2.85, h: 0.35,
    fontFace: FONT, fontSize: 11, color: C.white, align: 'center',
  });

  // ── 매핑 테이블 (8개 의견)
  const rows = [
    { o: '① "무엇을 해야 하는지" 안내가 가장 중요', w: '오범조', r: '"적절한 안내" 10점 → 15점 (+50%)' },
    { o: '② 응급 안내 누락은 감점되어야', w: '오범조', r: '응급 에스컬레이션 8점 + "이유 제시" 명시' },
    { o: '③ 응급 / 경고 징후 통합 필요', w: '홍승노', r: '"위험 신호 평가" 10점으로 통합' },
    { o: '④ 중증 가능성 (암·심부전·패혈증) 확인', w: '이준엽', r: '"증상군별 Red flag 확인" 7점 신규' },
    { o: '⑤ 증상에 따라 중요 질문 다름', w: '백은혜', r: '"증상군별 추가 문진" 5점 신규' },
    { o: '⑥ 사용자 부담 낮춘 능동적 문진', w: '원성호', r: '"부담 낮춘 질문 구조" 4점 신규' },
    { o: '⑦ 이미 제공된 정보 반복 X', w: '최영호', r: '"질문 중복 최소화" 5점 신규' },
    { o: '⑧ 국내 의료환경 · 의료법 균형', w: '양현종', r: '"표현 유형 3분류" — 정보·상담·지시형 구분' },
  ];

  // 테이블 레이아웃
  const tableY = 1.8;
  const rowH = 0.48;

  // 헤더 행 (한 번만)
  s.addShape('rect', { x: 0.5, y: tableY, w: 12.83, h: rowH, fill: { color: C.primary } });
  s.addText('자문 의견', {
    x: 0.7, y: tableY, w: 5.3, h: rowH,
    fontFace: FONT, fontSize: 13, color: C.white, bold: true, valign: 'middle',
  });
  s.addText('제기 위원', {
    x: 6, y: tableY, w: 1.6, h: rowH,
    fontFace: FONT, fontSize: 13, color: C.white, bold: true, align: 'center', valign: 'middle',
  });
  s.addText('v1.1 반영 내용', {
    x: 7.8, y: tableY, w: 5.53, h: rowH,
    fontFace: FONT, fontSize: 13, color: C.white, bold: true, valign: 'middle',
  });

  // 데이터 행 (8개)
  rows.forEach((r, i) => {
    const ry = tableY + rowH + i * rowH;
    const bg = i % 2 === 0 ? C.white : C.bg;
    s.addShape('rect', {
      x: 0.5, y: ry, w: 12.83, h: rowH,
      fill: { color: bg }, line: { color: C.border, width: 0.5 },
    });
    s.addText(r.o, {
      x: 0.7, y: ry, w: 5.3, h: rowH,
      fontFace: FONT, fontSize: 12, color: C.text, bold: true, valign: 'middle',
    });
    s.addText(r.w, {
      x: 6, y: ry, w: 1.6, h: rowH,
      fontFace: FONT, fontSize: 11.5, color: C.textDim, align: 'center', valign: 'middle',
    });
    s.addText(r.r, {
      x: 7.8, y: ry, w: 5.53, h: rowH,
      fontFace: FONT, fontSize: 12, color: C.primary, bold: true, valign: 'middle',
    });
  });

  // 하단 점수 변화 요약 박스
  const tableBottom = tableY + rowH * 9; // 헤더 + 8행
  const sumY = tableBottom + 0.15;
  const sumH = 1.05;
  s.addShape('roundRect', {
    x: 0.5, y: sumY, w: 12.83, h: sumH,
    fill: { color: C.light }, line: { color: C.accent, width: 1.5 },
    rectRadius: 0.08,
  });
  s.addText('📊 점수 배점 변화 — 5개 영역 (총점 100점 유지)', {
    x: 0.7, y: sumY + 0.08, w: 12.5, h: 0.3,
    fontFace: FONT, fontSize: 12, color: C.primary, bold: true,
  });

  const scoreItems = [
    { name: '증상 탐색', from: 30, to: 25, color: C.textDim },
    { name: '위험 선별', from: 25, to: 25, color: C.text },
    { name: '환자 맥락', from: 20, to: 20, color: C.text },
    { name: '단계적 접근', from: 15, to: 15, color: C.text },
    { name: '적절한 안내', from: 10, to: 15, color: C.primary, highlight: true },
  ];

  scoreItems.forEach((it, i) => {
    const ix = 0.5 + i * 2.566;
    const iy = sumY + 0.4;
    s.addText(it.name, {
      x: ix, y: iy, w: 2.566, h: 0.25,
      fontFace: FONT, fontSize: 11, color: it.color, bold: it.highlight, align: 'center',
    });
    const arrow = it.from === it.to ? '=' : (it.to > it.from ? '▲' : '▼');
    s.addText(`${it.from} → ${it.to}점  ${arrow}`, {
      x: ix, y: iy + 0.25, w: 2.566, h: 0.32,
      fontFace: FONT, fontSize: 13, color: it.color, bold: true, align: 'center',
    });
  });
}

const outPath = path.join(__dirname, 'consultation_v11_advisor_reflection.pptx');
pptx.writeFile({ fileName: outPath }).then(fn => {
  const sz = fs.statSync(fn).size;
  console.log('OK:', fn, '(', sz, 'bytes )');
});
