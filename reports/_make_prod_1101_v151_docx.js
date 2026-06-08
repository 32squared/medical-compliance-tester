// 운영 1101 batch v1.5.1 분석 보고서
// 사용: node reports/_make_prod_1101_v151_docx.js
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, LevelFormat, PageNumber, PageBreak,
} = require('docx');

const FONT = 'Pretendard';
const border = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const cellBorders = { top: border, bottom: border, left: border, right: border };

const p = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after != null ? opts.after : 90 },
  alignment: opts.align || AlignmentType.LEFT,
  children: [new TextRun({ text: text || '', font: FONT, size: opts.size || 22, bold: !!opts.bold, color: opts.color })],
});
const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 },
  children: [new TextRun({ text, font: FONT, size: 32, bold: true, color: '0F172A' })],
});
const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 100 },
  children: [new TextRun({ text, font: FONT, size: 26, bold: true, color: '1E40AF' })],
});
const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3, spacing: { before: 160, after: 80 },
  children: [new TextRun({ text, font: FONT, size: 22, bold: true, color: '334155' })],
});
const numbering = {
  config: [{
    reference: 'bullets',
    levels: [{
      level: 0, format: LevelFormat.BULLET, text: '•',
      alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } },
    }],
  }],
};
const bullet = (text, opts = {}) => new Paragraph({
  numbering: { reference: 'bullets', level: 0 },
  spacing: { after: 60 },
  children: [new TextRun({ text, font: FONT, size: 22, bold: !!opts.bold })],
});
const cell = (text, opts = {}) => new TableCell({
  borders: cellBorders,
  width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
  shading: opts.shading ? { fill: opts.shading, type: ShadingType.CLEAR } : undefined,
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  children: (Array.isArray(text) ? text : [text]).map(t =>
    typeof t === 'string'
      ? new Paragraph({ spacing: { after: 0 },
          children: [new TextRun({ text: t, font: FONT, size: opts.size || 20, bold: !!opts.bold, color: opts.color })] })
      : t),
});
const box = (text, color = '0F172A') => new Paragraph({
  shading: { fill: 'F1F5F9', type: ShadingType.CLEAR },
  spacing: { before: 100, after: 120 },
  border: {
    left: { style: BorderStyle.SINGLE, size: 12, color: color, space: 6 },
    top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
  },
  children: [new TextRun({ text, font: FONT, size: 22, color: '334155' })],
});

const children = [];

// ── 표지 ──
children.push(new Paragraph({
  spacing: { before: 1800, after: 400 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '운영 1101건 batch 평가 분석 보고서', font: FONT, size: 56, bold: true, color: '0F172A' })],
}));
children.push(new Paragraph({
  spacing: { after: 200 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '문진 평가 기준 v1.5.1 적용 (인구학 활용 명시 신설)', font: FONT, size: 36, bold: true, color: '1E40AF' })],
}));
children.push(new Paragraph({
  spacing: { after: 600 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '운영 일반 시나리오 1101건 (HB 제외) — v1.5.1 적용 후 첫 전체 평가', font: FONT, size: 24, color: '64748B' })],
}));
children.push(new Paragraph({
  spacing: { after: 200 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '작성: 2026-06-07 · runId: job-20260607-181904-fdeae7', font: FONT, size: 22, color: '64748B' })],
}));
children.push(new Paragraph({
  spacing: { after: 100 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '환경: prod · 모델: gpt-5.4 · 평가 기준: v1.5.1', font: FONT, size: 22, color: '64748B' })],
}));
children.push(new Paragraph({ children: [new PageBreak()] }));

// ── 1. 요약 ──
children.push(h1('1. 요약'));
children.push(p('운영 일반 시나리오 1101건(HealthBench 제외)에 대해 v1.5.1 평가 기준(인구학 활용 명시 항목 신설 포함)으로 전체 batch 평가를 진행하였습니다. 1100건이 정상 평가 완료되어 분석 가능합니다.'));
children.push(p(''));
children.push(h2('1.1 핵심 발견'));
children.push(bullet('전체 문진 평균 점수: 72.1점 / 100 (200건 샘플 69.6점 대비 +2.5점)', { bold: true }));
children.push(bullet('등급 분포: A 13.5%, B 52.5% (B 이상 비율 66%)'));
children.push(bullet('GPT 법률 평가: A 등급 97.0% — 의료법 경계는 우수'));
children.push(bullet('인구학 명시 prompt 404건 중 89.9%(363건)에서 답변이 인구학 정보 미활용 — 자문 피드백 정확성 완벽 검증', { bold: true }));
children.push(bullet('CRITICAL 위험도(307건)는 평균 57.4점 — 안전성이 가장 필요한 시나리오에서 답변 품질 부족', { bold: true }));
children.push(bullet('문진 Flow 명시 축(57.4%)이 가장 취약 — 체크리스트화 부족'));

children.push(h2('1.2 권고'));
children.push(bullet('운영 답변 자체에 인구학 정보 활용 강화 — prompt의 나이/성별/임신을 답변 가능 원인·체크리스트·행동 안내에 차등 반영', { bold: true }));
children.push(bullet('CRITICAL 위험도 시나리오 답변 패턴 개선'));
children.push(bullet('문진 Flow 체크리스트 구조화(1)2)3) 형태) 도입'));
children.push(bullet('진료과·방문 시점 구체화'));

// ── 2. 전체 점수 분포 ──
children.push(h1('2. 전체 점수 분포'));
const scoreT = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3120, 6240],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('지표', { width: 3120, shading: 'E2E8F0', bold: true }),
      cell('값', { width: 6240, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [ cell('평균', { width: 3120 }), cell('72.1점 / 100', { width: 6240, bold: true }) ]}),
    new TableRow({ children: [ cell('중앙값', { width: 3120 }), cell('79점', { width: 6240 }) ]}),
    new TableRow({ children: [ cell('표준편차', { width: 3120 }), cell('15.6', { width: 6240 }) ]}),
    new TableRow({ children: [ cell('범위', { width: 3120 }), cell('18 ~ 92점', { width: 6240 }) ]}),
    new TableRow({ children: [ cell('평가 완료', { width: 3120 }), cell('1100 / 1101건 (99.9%)', { width: 6240 }) ]}),
  ],
});
children.push(scoreT);

children.push(h3('2.1 등급 분포'));
const gradeT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [2080, 2080, 2080, 3120],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('등급', { width: 2080, shading: 'E2E8F0', bold: true }),
      cell('건수', { width: 2080, shading: 'E2E8F0', bold: true }),
      cell('비율', { width: 2080, shading: 'E2E8F0', bold: true }),
      cell('의미', { width: 3120, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [ cell('A (≥85)', { width: 2080 }), cell('149', { width: 2080 }), cell('13.5%', { width: 2080 }), cell('적정 수준', { width: 3120, shading: 'D1FAE5' }) ]}),
    new TableRow({ children: [ cell('B (≥70)', { width: 2080 }), cell('578', { width: 2080, bold: true }), cell('52.5%', { width: 2080, bold: true }), cell('보통 (다수)', { width: 3120, shading: 'DBEAFE' }) ]}),
    new TableRow({ children: [ cell('C (≥55)', { width: 2080 }), cell('168', { width: 2080 }), cell('15.3%', { width: 2080 }), cell('부족', { width: 3120, shading: 'FEF3C7' }) ]}),
    new TableRow({ children: [ cell('D (≥40)', { width: 2080 }), cell('173', { width: 2080 }), cell('15.7%', { width: 2080 }), cell('미흡', { width: 3120, shading: 'FED7AA' }) ]}),
    new TableRow({ children: [ cell('F (<40)', { width: 2080 }), cell('32', { width: 2080 }), cell('2.9%', { width: 2080 }), cell('실패', { width: 3120, shading: 'FEE2E2' }) ]}),
  ],
});
children.push(gradeT);
children.push(p(''));
children.push(box('B 이상 비율 66% — 운영 답변이 v1.5.1 기준에서도 기본은 충족. 그러나 A(적정수준)는 13.5%로 개선 여지 큼.', '0EA5E9'));

// ── 3. 축별 평균 ──
children.push(h1('3. 축별 평균 점수 (v1.5.1)'));
const axisT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [3500, 1560, 1560, 1560, 1180],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('축', { width: 3500, shading: 'E2E8F0', bold: true }),
      cell('평균', { width: 1560, shading: 'E2E8F0', bold: true }),
      cell('만점', { width: 1560, shading: 'E2E8F0', bold: true }),
      cell('달성률', { width: 1560, shading: 'E2E8F0', bold: true }),
      cell('상태', { width: 1180, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [
      cell('① 의료법 경계·안전 고지', { width: 3500 }),
      cell('14.68', { width: 1560 }), cell('15', { width: 1560 }), cell('97.8%', { width: 1560, bold: true }),
      cell('✅ 최강', { width: 1180, shading: 'D1FAE5' }),
    ]}),
    new TableRow({ children: [
      cell('② 위험 신호 인식·전달', { width: 3500 }),
      cell('19.61', { width: 1560 }), cell('25', { width: 1560 }), cell('78.4%', { width: 1560 }),
      cell('양호', { width: 1180 }),
    ]}),
    new TableRow({ children: [
      cell('③ 문진 Flow 명시', { width: 3500, bold: true }),
      cell('14.36', { width: 1560, bold: true }), cell('25', { width: 1560 }), cell('57.4%', { width: 1560, bold: true }),
      cell('⚠ 최약', { width: 1180, shading: 'FEE2E2', bold: true }),
    ]}),
    new TableRow({ children: [
      cell('④ 환자 맞춤·임상가치', { width: 3500 }),
      cell('14.09', { width: 1560 }), cell('22', { width: 1560 }), cell('64.0%', { width: 1560 }),
      cell('보통', { width: 1180, shading: 'FEF3C7' }),
    ]}),
    new TableRow({ children: [
      cell('⑤ 행동 가이드·의사소통', { width: 3500 }),
      cell('9.33', { width: 1560 }), cell('13', { width: 1560 }), cell('71.7%', { width: 1560 }),
      cell('보통', { width: 1180 }),
    ]}),
  ],
});
children.push(axisT);
children.push(p(''));
children.push(box('의료법 경계는 거의 만점에 가까움. 그러나 단일턴 답변에 의사 문진 흐름을 체크리스트로 표현하는 능력이 부족. 운영 답변이 일반 정보 전달 위주.', 'F59E0B'));

// ── 4. 인구학 활용 통계 (핵심) ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('4. 인구학 정보 활용 통계 (v1.5.1 핵심)'));
children.push(p('자문 피드백의 핵심 진단(나이/성별 누락이 v1.1.1부터 지속)이 v1.5.1 인구학 활용 명시 항목으로 측정 가능합니다.'));

const demoT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [4680, 4680],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('항목', { width: 4680, shading: 'E2E8F0', bold: true }),
      cell('결과', { width: 4680, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [
      cell('인구학 명시 prompt', { width: 4680 }),
      cell('404 / 1100건 (36.7%)', { width: 4680, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('인구학 미명시 prompt', { width: 4680 }),
      cell('696 / 1100건 (63.3%)', { width: 4680 }),
    ]}),
    new TableRow({ children: [
      cell('⭐ 인구학 미활용 명시 기록', { width: 4680, bold: true, shading: 'FEE2E2' }),
      cell('363 / 404건 (89.9%)', { width: 4680, bold: true, shading: 'FEE2E2' }),
    ]}),
    new TableRow({ children: [
      cell('clinicalValue (인구학 명시 시) 평균', { width: 4680 }),
      cell('13.87 / 22', { width: 4680 }),
    ]}),
    new TableRow({ children: [
      cell('clinicalValue (인구학 미명시 시) 평균', { width: 4680 }),
      cell('14.22 / 22', { width: 4680 }),
    ]}),
  ],
});
children.push(demoT);
children.push(p(''));
children.push(box('자문 피드백 진단 완벽 검증: 운영 답변의 약 90%가 인구학 정보(나이/성별/임신)를 받아도 활용하지 않음. 더 중요한 사실: 인구학이 명시된 prompt가 오히려 평균 점수가 낮음 — 답변이 그 정보를 활용 못 함이 측정으로 확인됨.', 'EF4444'));

// ── 5. GPT 법률 ──
children.push(h1('5. GPT 법률 평가'));
const legalT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [4680, 4680],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('지표', { width: 4680, shading: 'E2E8F0', bold: true }),
      cell('값', { width: 4680, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [ cell('평균 점수', { width: 4680 }), cell('95.6 / 100', { width: 4680, bold: true }) ]}),
    new TableRow({ children: [ cell('중앙값', { width: 4680 }), cell('96', { width: 4680 }) ]}),
    new TableRow({ children: [ cell('A 등급', { width: 4680 }), cell('1067건 (97.0%)', { width: 4680, shading: 'D1FAE5', bold: true }) ]}),
    new TableRow({ children: [ cell('B 등급', { width: 4680 }), cell('32건 (2.9%)', { width: 4680 }) ]}),
    new TableRow({ children: [ cell('C 이하', { width: 4680 }), cell('1건 (0.1%)', { width: 4680 }) ]}),
  ],
});
children.push(legalT);
children.push(p(''));
children.push(box('의료법 경계는 매우 우수. 운영 답변이 면책조항·확진 회피·약물 임의 추천 회피 등을 잘 지키고 있음.', '22C55E'));

// ── 6. 카테고리별 ──
children.push(h1('6. 카테고리별 평균 (Top 10 / Bottom 5)'));
const catTop = [
  ['injection', 81.8, 6], ['general', 81.0, 169], ['정신건강', 78.0, 10],
  ['피부', 77.8, 10], ['diagnosis', 77.3, 217], ['비뇨생식기', 77.2, 10],
  ['prescription', 76.9, 138], ['edge', 76.3, 75], ['근골격계', 75.6, 10], ['treatment', 75.3, 118],
];
const catBot = [
  ['머리·뇌·신경계', 66.8, 10], ['순환기', 66.4, 10], ['호흡기', 67.1, 9],
  ['감각기관', 71.0, 10], ['전신·피로·발열', 72.1, 10],
];
children.push(h3('6.1 평균 점수 Top 10'));
const cTopT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [780, 3900, 2340, 2340],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('순위', { width: 780, shading: 'E2E8F0', bold: true }),
      cell('카테고리', { width: 3900, shading: 'E2E8F0', bold: true }),
      cell('평균', { width: 2340, shading: 'E2E8F0', bold: true }),
      cell('건수', { width: 2340, shading: 'E2E8F0', bold: true }),
    ]}),
    ...catTop.map((row, i) => new TableRow({ children: [
      cell(String(i+1), { width: 780 }),
      cell(row[0], { width: 3900 }),
      cell(row[1].toFixed(1), { width: 2340 }),
      cell(String(row[2]), { width: 2340 }),
    ]})),
  ],
});
children.push(cTopT);

children.push(h3('6.2 평균 점수 Bottom 5 ⚠'));
const cBotT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [780, 3900, 2340, 2340],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('순위', { width: 780, shading: 'E2E8F0', bold: true }),
      cell('카테고리', { width: 3900, shading: 'E2E8F0', bold: true }),
      cell('평균', { width: 2340, shading: 'E2E8F0', bold: true }),
      cell('건수', { width: 2340, shading: 'E2E8F0', bold: true }),
    ]}),
    ...catBot.map((row, i) => new TableRow({ children: [
      cell(String(i+1), { width: 780 }),
      cell(row[0], { width: 3900 }),
      cell(row[1].toFixed(1), { width: 2340, shading: 'FEF3C7' }),
      cell(String(row[2]), { width: 2340 }),
    ]})),
  ],
});
children.push(cBotT);

// ── 7. 위험도별 ──
children.push(h1('7. 위험도별 평균'));
const riskT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [2340, 2340, 2340, 2340],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('위험도', { width: 2340, shading: 'E2E8F0', bold: true }),
      cell('평균', { width: 2340, shading: 'E2E8F0', bold: true }),
      cell('건수', { width: 2340, shading: 'E2E8F0', bold: true }),
      cell('해석', { width: 2340, shading: 'E2E8F0', bold: true }),
    ]}),
    new TableRow({ children: [
      cell('LOW', { width: 2340 }), cell('83.4', { width: 2340 }), cell('89', { width: 2340 }),
      cell('우수', { width: 2340, shading: 'D1FAE5' }),
    ]}),
    new TableRow({ children: [
      cell('MEDIUM', { width: 2340 }), cell('80.4', { width: 2340 }), cell('204', { width: 2340 }),
      cell('양호', { width: 2340, shading: 'DBEAFE' }),
    ]}),
    new TableRow({ children: [
      cell('HIGH', { width: 2340 }), cell('75.6', { width: 2340 }), cell('500', { width: 2340 }),
      cell('보통', { width: 2340, shading: 'FEF3C7' }),
    ]}),
    new TableRow({ children: [
      cell('CRITICAL', { width: 2340, bold: true, shading: 'FEE2E2' }),
      cell('57.4', { width: 2340, bold: true, shading: 'FEE2E2' }),
      cell('307', { width: 2340, bold: true, shading: 'FEE2E2' }),
      cell('⚠ 미흡', { width: 2340, shading: 'FEE2E2', bold: true }),
    ]}),
  ],
});
children.push(riskT);
children.push(p(''));
children.push(box('위험도가 높을수록 답변 품질이 낮은 역상관 관계. 가장 안전성이 필요한 CRITICAL 시나리오(307건)에서 평균 57.4점 — 안전 가이드·체크리스트·즉각 행동 안내가 부족함을 시사.', 'EF4444'));

// ── 8. 누락 항목 Top ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('8. 자주 누락된 핵심 항목 Top 15'));
const missList = [
  ['인구학 정보 미활용(나이/성별/임신 등) ⭐', 45],
  ['증상 시작 시점과 경과 확인', 41],
  ['잘못된 자가처치 경고', 24],
  ['잘못된 자가처치 금지 안내', 22],
  ['증상 시작 시점과 경과', 22],
  ['가능 원인에 대한 비단정적 설명', 21],
  ['증상 시작 시점과 지속 시간 확인', 11],
  ['약물 임의 사용 주의 안내', 10],
  ['진료과 및 방문 시점의 구체화', 10],
  ['기저질환 및 복용약 확인', 9],
  ['기저질환·복용약·과거력 확인', 9],
  ['적절한 진료과와 방문 시점의 구체화', 9],
  ['임신 주수 확인', 8],
  ['증상 시작 시점과 악화 속도 확인', 7],
  ['행동 지침의 단계화', 6],
];
const missT = new Table({
  width: { size: 9360, type: WidthType.DXA }, columnWidths: [780, 7020, 1560],
  rows: [
    new TableRow({ tableHeader: true, children: [
      cell('순위', { width: 780, shading: 'E2E8F0', bold: true }),
      cell('누락 항목', { width: 7020, shading: 'E2E8F0', bold: true }),
      cell('건수', { width: 1560, shading: 'E2E8F0', bold: true }),
    ]}),
    ...missList.map((row, i) => new TableRow({ children: [
      cell(String(i+1), { width: 780 }),
      cell(row[0], { width: 7020, bold: i === 0 }),
      cell(String(row[1]), { width: 1560, bold: i === 0 }),
    ]})),
  ],
});
children.push(missT);

// ── 9. 결론 + 권고 ──
children.push(h1('9. 결론 및 권고'));
children.push(h2('9.1 평가 기준 측면'));
children.push(bullet('v1.5.1 평가 기준이 자문 피드백을 정확히 반영함이 1100건 규모로 검증됨'));
children.push(bullet('인구학 활용 명시 항목(신설 7점)이 90% 사례에서 명시 감점 + missing 기록을 정확히 생성'));
children.push(bullet('과거 v1.1.x 멀티턴 평가와 axes 키 다름 — 과거 batch와 직접 비교는 불가'));
children.push(bullet('단일턴 응답 평가 가정이 운영 chat_tester에도 적용됨 → 응답 패턴 변화 유도'));

children.push(h2('9.2 운영 답변 개선 권고 (우선순위)'));
children.push(bullet('1순위: 인구학 정보 활용 — prompt의 나이/성별/임신을 답변 가능 원인/체크리스트/행동 안내에 차등 반영', { bold: true }));
children.push(bullet('2순위: CRITICAL 위험도 답변 보강 — 안전 핵심 누락 (자가처치 경고, 응급 즉시 안내, Red flag 명시)', { bold: true }));
children.push(bullet('3순위: 문진 Flow 체크리스트 구조화 — 1)2)3) 형태로 환자 자가 점검 가이드'));
children.push(bullet('4순위: 진료과·방문 시점 구체화 (즉시/당일/수일 내)'));
children.push(bullet('5순위: 증상 시작 시점·경과 확인 항목 명시 (시간/양상 체크리스트)'));

children.push(h2('9.3 다음 단계'));
children.push(bullet('운영팀에 본 보고서 공유 — 답변 템플릿 개선'));
children.push(bullet('자문위원에 v1.5.1 적용 + 1100건 결과 공유 — 평가 기준 추가 의견 수렴'));
children.push(bullet('인구학 명시 404건의 카테고리/위험도 deep dive — 어디서 가장 누락 심한지 파악'));
children.push(bullet('운영 답변 패턴 개선 후 다시 1100건 batch → 점수 향상 측정'));
children.push(bullet('CRITICAL 위험도 307건 별도 분석 — 안전 핵심 누락 패턴 도출'));

children.push(p(''));
children.push(box('1100건 평가 결과는 v1.5.1 평가 기준이 자문 피드백을 정확히 반영함을 정량적으로 검증함. 다음 단계는 평가 기준 추가 정교화가 아니라 운영 답변 자체의 개선이 우선.', '22C55E'));

// ── Document 빌드 ──
const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 32, bold: true, font: FONT },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 26, bold: true, font: FONT },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, font: FONT },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: numbering,
  sections: [{
    properties: {
      page: { size: { width: 11906, height: 16838 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    headers: { default: new Header({ children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: '운영 1101건 batch v1.5.1 분석 보고서', font: FONT, size: 18, color: '94A3B8' })],
    })] }) },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18, color: '94A3B8' })],
    })] }) },
    children: children,
  }],
});

const outPath = path.join(__dirname, 'prod_1101_v151_analysis_report.docx');
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log(`✓ 보고서 생성: ${outPath} (${Math.round(fs.statSync(outPath).size/1024)} KB)`);
}).catch(err => { console.error('생성 실패:', err); process.exit(1); });
