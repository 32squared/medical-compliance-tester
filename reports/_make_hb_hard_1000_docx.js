/**
 * HealthBench Hard 1,000건 분석 보고서 — .docx 생성기
 * 출력: reports/healthbench_hard_1000_analysis.docx
 */
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, WidthType,
  ShadingType, PageOrientation, PageBreak,
} = require('docx');

// ── 헬퍼 ──
const border = { style: BorderStyle.SINGLE, size: 4, color: 'D0D7DE' };
const allBorders = { top: border, bottom: border, left: border, right: border };

function txt(t, opts = {}) { return new TextRun({ text: t, ...opts }); }
function p(text, opts = {}) {
  const children = Array.isArray(text)
    ? text.map(x => (typeof x === 'string' ? new TextRun(x) : x))
    : [new TextRun(text)];
  return new Paragraph({ children, ...opts });
}
function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text, bold: true })] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text, bold: true })] }); }
function h3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text, bold: true, color: '6366F1' })] }); }
function cell(text, opts = {}) {
  const {
    bold = false, color, bg, width = 1800, align = AlignmentType.LEFT,
    fontSize = 20,
  } = opts;
  return new TableCell({
    borders: allBorders,
    width: { size: width, type: WidthType.DXA },
    shading: bg ? { fill: bg, type: ShadingType.CLEAR } : undefined,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text, bold, color, size: fontSize })],
    })],
  });
}
function headerCell(text, width = 1800, align = AlignmentType.LEFT) {
  return cell(text, { bold: true, bg: 'E2E8F0', color: '475569', width, align, fontSize: 18 });
}

// ── 보고서 컨텐츠 ──
const children = [];

// 제목 + 부제
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: '🩺 HealthBench Hard 1,000건 분석 보고서', bold: true, size: 36, color: '0F172A' })],
  spacing: { after: 100 },
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: 'SKIX 의료 응답 평가 결과 — 약점 패턴 식별 및 개선 우선순위 도출', size: 22, color: '64748B' })],
  spacing: { after: 200 },
}));

// 메타 정보
const metaTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2340, 2340, 2340, 2340],
  rows: [
    new TableRow({
      children: [
        cell('run_id', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('job-20260518-191745-3b1b90', { width: 2340 }),
        cell('시점', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('2026-05-18', { width: 2340 }),
      ],
    }),
    new TableRow({
      children: [
        cell('환경', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('PROD', { width: 2340 }),
        cell('데이터셋', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('HealthBench Hard subset (1,000건)', { width: 2340 }),
      ],
    }),
    new TableRow({
      children: [
        cell('모델', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('gpt-4o-mini (rubric grader)', { width: 2340 }),
        cell('실행 시간', { bold: true, bg: 'F1F5F9', width: 2340 }),
        cell('~17분', { width: 2340 }),
      ],
    }),
  ],
});
children.push(metaTable);
children.push(p(''));

// TL;DR
children.push(new Paragraph({
  shading: { fill: 'EFF6FF', type: ShadingType.CLEAR },
  border: { left: { style: BorderStyle.SINGLE, size: 24, color: '0EA5E9' } },
  spacing: { before: 100, after: 100 },
  children: [new TextRun({ text: '📌 한 줄 요약', bold: true, color: '0EA5E9', size: 22 })],
}));
children.push(new Paragraph({
  shading: { fill: 'EFF6FF', type: ShadingType.CLEAR },
  border: { left: { style: BorderStyle.SINGLE, size: 24, color: '0EA5E9' } },
  spacing: { after: 200 },
  children: [
    new TextRun({ text: 'SKIX 의 Hard subset 평균 점수는 ', size: 22 }),
    new TextRun({ text: '23.67점 (≈ GPT-4o-mini 수준)', bold: true, size: 22, color: '6366F1' }),
    new TextRun({ text: '. 가장 큰 약점은 ', size: 22 }),
    new TextRun({ text: 'accuracy', bold: true, size: 22 }),
    new TextRun({ text: ' (70회 × −350pt 손실) 와 ', size: 22 }),
    new TextRun({ text: 'context_seeking × instruction_following (−46.8%)', bold: true, size: 22 }),
    new TextRun({ text: '. 0점 시나리오 315건 중 83%가 음수 페널티 발생. 만점 시나리오 32건은 평균 rubric 4.7개로 단순 시나리오만 만점 가능.', size: 22 }),
  ],
}));

// 1. 핵심 지표
children.push(h2('1. 핵심 지표'));
const kpiTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [1560, 1560, 1560, 1560, 1560, 1560],
  rows: [
    new TableRow({
      children: [
        cell('23.67', { bold: true, fontSize: 36, color: 'EAB308', align: AlignmentType.CENTER, width: 1560 }),
        cell('17.14', { bold: true, fontSize: 36, color: '0F172A', align: AlignmentType.CENTER, width: 1560 }),
        cell('15.7%', { bold: true, fontSize: 36, color: 'EF4444', align: AlignmentType.CENTER, width: 1560 }),
        cell('1,000', { bold: true, fontSize: 36, color: '0EA5E9', align: AlignmentType.CENTER, width: 1560 }),
        cell('997', { bold: true, fontSize: 36, color: 'A855F7', align: AlignmentType.CENTER, width: 1560 }),
        cell('~17분', { bold: true, fontSize: 36, color: '22C55E', align: AlignmentType.CENTER, width: 1560 }),
      ],
    }),
    new TableRow({
      children: [
        cell('평균 점수', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
        cell('Median', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
        cell('통과율 (≥50)', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
        cell('시나리오 수', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
        cell('평가 완료', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
        cell('실행 소요', { fontSize: 16, align: AlignmentType.CENTER, width: 1560, bg: 'F8FAFC' }),
      ],
    }),
  ],
});
children.push(kpiTable);
children.push(p(''));
children.push(p('Hard subset의 본질: HealthBench Hard 는 모델이 풀기 어려운 시나리오만 모은 부분집합 (5,000건 중 1,000건). 점수가 전반적으로 낮은 게 정상 — OpenAI 의 reference 모델들도 Hard 에서 평균 30–50점.', { spacing: { after: 200 } }));

// 2. 점수 분포
children.push(h2('2. 점수 분포'));
const bucketTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2340, 1560, 1560, 3900],
  rows: [
    new TableRow({ children: [
      headerCell('구간', 2340),
      headerCell('건수', 1560, AlignmentType.RIGHT),
      headerCell('비율', 1560, AlignmentType.RIGHT),
      headerCell('비고', 3900),
    ]}),
    new TableRow({ children: [
      cell('75–100 (우수)', { width: 2340, bg: 'D1FAE5' }),
      cell('53', { width: 1560, align: AlignmentType.RIGHT }),
      cell('5.3%', { width: 1560, align: AlignmentType.RIGHT, bold: true, color: '22C55E' }),
      cell('만점·우수 시나리오', { width: 3900 }),
    ]}),
    new TableRow({ children: [
      cell('50–74 (통과)', { width: 2340, bg: 'DBEAFE' }),
      cell('104', { width: 1560, align: AlignmentType.RIGHT }),
      cell('10.4%', { width: 1560, align: AlignmentType.RIGHT, bold: true, color: '0EA5E9' }),
      cell('PASS 기준 (≥50점)', { width: 3900 }),
    ]}),
    new TableRow({ children: [
      cell('25–49 (미흡)', { width: 2340, bg: 'FEF3C7' }),
      cell('245', { width: 1560, align: AlignmentType.RIGHT }),
      cell('24.5%', { width: 1560, align: AlignmentType.RIGHT, bold: true, color: 'EAB308' }),
      cell('일부 핵심 누락', { width: 3900 }),
    ]}),
    new TableRow({ children: [
      cell('0–24 (심각)', { width: 2340, bg: 'FEE2E2' }),
      cell('595', { width: 1560, align: AlignmentType.RIGHT, bold: true }),
      cell('59.5%', { width: 1560, align: AlignmentType.RIGHT, bold: true, color: 'EF4444' }),
      cell('음수 페널티 또는 핵심 항목 다수 누락', { width: 3900 }),
    ]}),
    new TableRow({ children: [
      cell('no-score', { width: 2340 }),
      cell('3', { width: 1560, align: AlignmentType.RIGHT }),
      cell('0.3%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('rubric 평가 오류', { width: 3900 }),
    ]}),
  ],
});
children.push(bucketTable);
children.push(p(''));
children.push(p([
  txt('가장 큰 신호: ', { bold: true }),
  txt('0~9점 시나리오가 '),
  txt('416건 (41.6%)', { bold: true }),
  txt('. 절반 가까이가 0점 근처에 몰림. 즉 SKIX 가 음수 페널티 rubric 항목을 회피하지 못하거나 핵심 항목을 놓침.'),
], { spacing: { after: 200 } }));

// 3. Theme별 평균
children.push(h2('3. Theme별 평균 점수'));
const themeTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2300, 1100, 1100, 1100, 3760],
  rows: [
    new TableRow({ children: [
      headerCell('Theme', 2300),
      headerCell('n', 1100, AlignmentType.RIGHT),
      headerCell('평균', 1100, AlignmentType.RIGHT),
      headerCell('통과율', 1100, AlignmentType.RIGHT),
      headerCell('강·약', 3760),
    ]}),
    new TableRow({ children: [
      cell('hedging', { width: 2300, bold: true }),
      cell('167', { width: 1100, align: AlignmentType.RIGHT }),
      cell('34.56', { width: 1100, align: AlignmentType.RIGHT, bold: true, color: '22C55E' }),
      cell('24.6%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('🟢 상대적 강점 — 안전 표현·의사 상담 권유', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('health_data_tasks', { width: 2300 }),
      cell('114', { width: 1100, align: AlignmentType.RIGHT }),
      cell('27.57', { width: 1100, align: AlignmentType.RIGHT }),
      cell('21.1%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('—', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('context_seeking', { width: 2300 }),
      cell('178', { width: 1100, align: AlignmentType.RIGHT }),
      cell('26.37', { width: 1100, align: AlignmentType.RIGHT }),
      cell('19.7%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('—', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('emergency_referrals', { width: 2300 }),
      cell('66', { width: 1100, align: AlignmentType.RIGHT }),
      cell('22.19', { width: 1100, align: AlignmentType.RIGHT }),
      cell('10.6%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('—', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('global_health', { width: 2300 }),
      cell('279', { width: 1100, align: AlignmentType.RIGHT }),
      cell('20.71', { width: 1100, align: AlignmentType.RIGHT }),
      cell('12.5%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('—', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('communication', { width: 2300, bold: true }),
      cell('111', { width: 1100, align: AlignmentType.RIGHT }),
      cell('15.48', { width: 1100, align: AlignmentType.RIGHT, bold: true, color: 'F97316' }),
      cell('7.2%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('🟡 약함 — 전문용어 풀이·표현', { width: 3760 }),
    ]}),
    new TableRow({ children: [
      cell('complex_responses', { width: 2300, bold: true }),
      cell('82', { width: 1100, align: AlignmentType.RIGHT }),
      cell('12.55', { width: 1100, align: AlignmentType.RIGHT, bold: true, color: 'EF4444' }),
      cell('8.5%', { width: 1100, align: AlignmentType.RIGHT }),
      cell('🔴 가장 약함 — 복합·구조화 응답', { width: 3760 }),
    ]}),
  ],
});
children.push(themeTable);
children.push(p(''));

// 4. Axis별 가중점수
children.push(h2('4. Axis별 가중점수'));
const axisTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2500, 1400, 1400, 2300, 1760],
  rows: [
    new TableRow({ children: [
      headerCell('Axis', 2500),
      headerCell('items', 1400, AlignmentType.RIGHT),
      headerCell('met', 1400, AlignmentType.RIGHT),
      headerCell('awarded / possible', 2300, AlignmentType.RIGHT),
      headerCell('가중점수', 1760, AlignmentType.RIGHT),
    ]}),
    new TableRow({ children: [
      cell('communication_quality', { width: 2500, bold: true }),
      cell('709', { width: 1400, align: AlignmentType.RIGHT }),
      cell('266', { width: 1400, align: AlignmentType.RIGHT }),
      cell('1,042 / 2,174', { width: 2300, align: AlignmentType.RIGHT }),
      cell('47.93', { width: 1760, align: AlignmentType.RIGHT, bold: true, color: '22C55E' }),
    ]}),
    new TableRow({ children: [
      cell('instruction_following', { width: 2500 }),
      cell('541', { width: 1400, align: AlignmentType.RIGHT }),
      cell('224', { width: 1400, align: AlignmentType.RIGHT }),
      cell('863 / 1,981', { width: 2300, align: AlignmentType.RIGHT }),
      cell('43.56', { width: 1760, align: AlignmentType.RIGHT, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('context_awareness', { width: 2500 }),
      cell('2,436', { width: 1400, align: AlignmentType.RIGHT }),
      cell('895', { width: 1400, align: AlignmentType.RIGHT }),
      cell('4,026 / 11,371', { width: 2300, align: AlignmentType.RIGHT }),
      cell('35.41', { width: 1760, align: AlignmentType.RIGHT, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('completeness', { width: 2500 }),
      cell('4,615', { width: 1400, align: AlignmentType.RIGHT }),
      cell('1,670', { width: 1400, align: AlignmentType.RIGHT }),
      cell('6,762 / 20,742', { width: 2300, align: AlignmentType.RIGHT }),
      cell('32.60', { width: 1760, align: AlignmentType.RIGHT, bold: true, color: 'F97316' }),
    ]}),
    new TableRow({ children: [
      cell('accuracy', { width: 2500, bold: true }),
      cell('3,505', { width: 1400, align: AlignmentType.RIGHT }),
      cell('872', { width: 1400, align: AlignmentType.RIGHT }),
      cell('4,627 / 15,166', { width: 2300, align: AlignmentType.RIGHT }),
      cell('30.51', { width: 1760, align: AlignmentType.RIGHT, bold: true, color: 'EF4444' }),
    ]}),
  ],
});
children.push(axisTable);
children.push(p(''));
children.push(p([
  txt('관찰: ', { bold: true }),
  txt('accuracy (의학적 정확성) 가 가장 약함. completeness 도 낮음 — 핵심 정보 일부 누락. 표현(communication_quality) + 지시 따르기는 상대적으로 양호.'),
], { spacing: { after: 200 } }));

// 페이지 break
children.push(new Paragraph({ children: [new PageBreak()] }));

// 5. Theme × Axis Heatmap (cross-table)
children.push(h2('5. Theme × Axis 가중점수 Cross-table'));
children.push(p([
  txt('각 셀의 값은 '),
  txt('(awarded / possible) × 100', { font: 'Consolas', size: 18 }),
  txt('. 음수는 음수 rubric 항목 met 이 양수보다 큰 경우 (점수 차감).'),
], { spacing: { after: 100 } }));

function hmCell(value, opts = {}) {
  return cell(value, { width: 1290, align: AlignmentType.CENTER, fontSize: 18, ...opts });
}
const hmTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2010, 1290, 1290, 1290, 1290, 1290, 900],
  rows: [
    new TableRow({ children: [
      headerCell('Theme \\ Axis', 2010),
      headerCell('accuracy', 1290, AlignmentType.CENTER),
      headerCell('communication', 1290, AlignmentType.CENTER),
      headerCell('completeness', 1290, AlignmentType.CENTER),
      headerCell('ctx_aware', 1290, AlignmentType.CENTER),
      headerCell('instr_follow', 1290, AlignmentType.CENTER),
      headerCell('평균', 900, AlignmentType.CENTER),
    ]}),
    new TableRow({ children: [
      cell('hedging', { width: 2010, bold: true, bg: 'F8FAFC' }),
      hmCell('45.1%', { bg: '22C55E', color: 'FFFFFF', bold: true }),
      hmCell('21.6%', { bg: 'FEF3C7' }),
      hmCell('17.8%', { bg: 'FEF3C7' }),
      hmCell('19.3%', { bg: 'FEF3C7' }),
      hmCell('1.4%', { bg: 'FEE2E2' }),
      cell('34.6', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('health_data_tasks', { width: 2010, bg: 'F8FAFC' }),
      hmCell('12.5%', { bg: 'FEE2E2' }),
      hmCell('25.0%', { bg: 'FED7AA' }),
      hmCell('20.1%', { bg: 'FED7AA' }),
      hmCell('15.0%', { bg: 'FEF3C7' }),
      hmCell('38.0%', { bg: 'FDE68A' }),
      cell('27.6', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('context_seeking', { width: 2010, bg: 'F8FAFC' }),
      hmCell('35.4%', { bg: 'FDE68A' }),
      hmCell('-7.7%', { bg: 'FECACA' }),
      hmCell('19.7%', { bg: 'FED7AA' }),
      hmCell('16.0%', { bg: 'FEF3C7' }),
      hmCell('-46.8%', { bg: 'DC2626', color: 'FFFFFF', bold: true }),
      cell('26.4', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('emergency_referrals', { width: 2010, bg: 'F8FAFC' }),
      hmCell('25.0%', { bg: 'FED7AA' }),
      hmCell('48.6%', { bg: '86EFAC' }),
      hmCell('12.0%', { bg: 'FEE2E2' }),
      hmCell('17.4%', { bg: 'FEF3C7' }),
      hmCell('0.0%', { bg: 'FEE2E2' }),
      cell('22.2', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('global_health', { width: 2010, bg: 'F8FAFC' }),
      hmCell('16.7%', { bg: 'FEF3C7' }),
      hmCell('67.4%', { bg: '22C55E', color: 'FFFFFF', bold: true }),
      hmCell('2.3%', { bg: 'FEE2E2' }),
      hmCell('28.6%', { bg: 'FED7AA' }),
      hmCell('16.5%', { bg: 'FEF3C7' }),
      cell('20.7', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('communication', { width: 2010, bg: 'F8FAFC' }),
      hmCell('13.6%', { bg: 'FEE2E2' }),
      hmCell('37.2%', { bg: 'FDE68A' }),
      hmCell('-12.6%', { bg: 'FECACA', bold: true }),
      hmCell('11.6%', { bg: 'FEE2E2' }),
      hmCell('0.0%', { bg: 'FEE2E2' }),
      cell('15.5', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
    new TableRow({ children: [
      cell('complex_responses', { width: 2010, bg: 'F8FAFC' }),
      hmCell('10.3%', { bg: 'FEE2E2' }),
      hmCell('3.1%', { bg: 'FEE2E2' }),
      hmCell('-19.4%', { bg: 'FECACA', bold: true }),
      hmCell('19.3%', { bg: 'FEF3C7' }),
      hmCell('-23.0%', { bg: 'FCA5A5', color: 'FFFFFF', bold: true }),
      cell('12.6', { width: 900, align: AlignmentType.CENTER, bold: true }),
    ]}),
  ],
});
children.push(hmTable);
children.push(p(''));

// 약점/강점 박스
children.push(new Paragraph({
  shading: { fill: 'FEE2E2', type: ShadingType.CLEAR },
  border: { left: { style: BorderStyle.SINGLE, size: 24, color: 'EF4444' } },
  children: [new TextRun({ text: '가장 큰 약점 (Heatmap red zone)', bold: true, color: 'B91C1C' })],
  spacing: { before: 100, after: 50 },
}));
children.push(p([
  txt('• context_seeking × instruction_following = −46.8%: 추가 정보를 물어야 할 상황에서 지시 안 따름', { size: 22 }),
], { shading: { fill: 'FEE2E2', type: ShadingType.CLEAR } }));
children.push(p([
  txt('• complex_responses: completeness −19.4% + instruction_following −23.0% — 복합 응답 처리 능력 부족', { size: 22 }),
], { shading: { fill: 'FEE2E2', type: ShadingType.CLEAR } }));
children.push(p([
  txt('• communication × completeness = −12.6%: 응답 구조 짤 때 핵심 정보 누락', { size: 22 }),
], { shading: { fill: 'FEE2E2', type: ShadingType.CLEAR }, spacing: { after: 100 } }));

children.push(new Paragraph({
  shading: { fill: 'D1FAE5', type: ShadingType.CLEAR },
  border: { left: { style: BorderStyle.SINGLE, size: 24, color: '22C55E' } },
  children: [new TextRun({ text: '강점', bold: true, color: '064E3B' })],
  spacing: { before: 50, after: 50 },
}));
children.push(p([
  txt('• global_health × communication_quality = 67.4%: 일반 건강 질의에 친화적 설명', { size: 22 }),
], { shading: { fill: 'D1FAE5', type: ShadingType.CLEAR } }));
children.push(p([
  txt('• emergency_referrals × communication_quality = 48.6%: 응급 상황 안내 표현 양호', { size: 22 }),
], { shading: { fill: 'D1FAE5', type: ShadingType.CLEAR } }));
children.push(p([
  txt('• hedging × accuracy = 45.1%: 불확실성 표현·안전 권유는 정확', { size: 22 }),
], { shading: { fill: 'D1FAE5', type: ShadingType.CLEAR }, spacing: { after: 200 } }));

// 6. 가장 자주 놓친 양수 Rubric
children.push(h2('6. 가장 자주 놓친 양수 Rubric (손실 점수 TOP 10)'));
const rubricTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [800, 800, 1200, 1860, 4700],
  rows: [
    new TableRow({ children: [
      headerCell('횟수', 800, AlignmentType.CENTER),
      headerCell('점수', 800, AlignmentType.CENTER),
      headerCell('손실', 1200, AlignmentType.RIGHT),
      headerCell('Axis', 1860),
      headerCell('Criterion 요약', 4700),
    ]}),
    new TableRow({ children: [
      cell('70', { width: 800, align: AlignmentType.CENTER, bold: true }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('350', { width: 1200, align: AlignmentType.RIGHT, bold: true, color: 'EF4444' }),
      cell('accuracy', { width: 1860, bg: 'FEE2E2' }),
      cell('"response must be entirely factually accurate" (메타 rubric — 모든 문장 정확)', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('45', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('225', { width: 1200, align: AlignmentType.RIGHT, bold: true }),
      cell('comm_quality', { width: 1860, bg: 'FEF3C7' }),
      cell('"core question 을 명확히 일찍 답변"', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('45', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('225', { width: 1200, align: AlignmentType.RIGHT, bold: true }),
      cell('context_aware', { width: 1860, bg: 'FEF3C7' }),
      cell('비전문가 사용자 컨텍스트 처리', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('37', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('185', { width: 1200, align: AlignmentType.RIGHT }),
      cell('accuracy', { width: 1860, bg: 'FEE2E2' }),
      cell('보건의료 전문가 사용자 컨텍스트 정확성', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('28', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('140', { width: 1200, align: AlignmentType.RIGHT }),
      cell('comm_quality', { width: 1860, bg: 'FEF3C7' }),
      cell('전문가 대상 응답 표현', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('26', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('130', { width: 1200, align: AlignmentType.RIGHT }),
      cell('instr_follow', { width: 1860, bg: 'FDE68A' }),
      cell('"누락된 정보가 있을 때 정확/안전 위해 task 거부"', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('23', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('115', { width: 1200, align: AlignmentType.RIGHT }),
      cell('instr_follow', { width: 1860, bg: 'FDE68A' }),
      cell('요청된 형식/길이/범위 정확히 준수', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('22', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('110', { width: 1200, align: AlignmentType.RIGHT }),
      cell('accuracy', { width: 1860, bg: 'FEE2E2' }),
      cell('"factually correct + relevant" 메타 기준', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('19', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('95', { width: 1200, align: AlignmentType.RIGHT }),
      cell('context_aware', { width: 1860, bg: 'FEF3C7' }),
      cell('"follow up 질문으로 컨텍스트 보강"', { width: 4700 }),
    ]}),
    new TableRow({ children: [
      cell('16', { width: 800, align: AlignmentType.CENTER }),
      cell('+5', { width: 800, align: AlignmentType.CENTER }),
      cell('80', { width: 1200, align: AlignmentType.RIGHT }),
      cell('comm_quality', { width: 1860, bg: 'FEF3C7' }),
      cell('의사 검토 기준 — "응답은 다소 simple 해야"', { width: 4700 }),
    ]}),
  ],
});
children.push(rubricTable);
children.push(p(''));
children.push(p([
  txt('핵심 약점: ', { bold: true }),
  txt('SKIX 가 자주 놓치는 항목은 '),
  txt('accuracy 메타 rubric', { bold: true }),
  txt(' + '),
  txt('communication_quality (core question 우선 답변)', { bold: true }),
  txt('. 이는 모든 응답에 공통 적용되는 기준이므로 prompt 수준의 보강이 효과적.'),
], { spacing: { after: 200 } }));

// 7. 0점 시나리오 분석
children.push(h2('7. 0점 시나리오 315건 원인 분석'));
const zeroTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2340, 1560, 5460],
  rows: [
    new TableRow({ children: [
      headerCell('원인', 2340),
      headerCell('건수', 1560, AlignmentType.RIGHT),
      headerCell('의미', 5460),
    ]}),
    new TableRow({ children: [
      cell('음수 met + 양수 met (clamp)', { width: 2340, bg: 'FEE2E2' }),
      cell('178', { width: 1560, align: AlignmentType.RIGHT, bold: true, fontSize: 28, color: 'EF4444' }),
      cell('좋은 답변 일부 했지만 음수 페널티로 점수 0으로 clamp (56.5%)', { width: 5460 }),
    ]}),
    new TableRow({ children: [
      cell('음수 met only (양수 0 met)', { width: 2340, bg: 'FEE2E2' }),
      cell('85', { width: 1560, align: AlignmentType.RIGHT, bold: true, fontSize: 28, color: 'EF4444' }),
      cell('가장 명백한 위반 (27%)', { width: 5460 }),
    ]}),
    new TableRow({ children: [
      cell('모두 missed', { width: 2340, bg: 'FEF3C7' }),
      cell('52', { width: 1560, align: AlignmentType.RIGHT, bold: true, fontSize: 28, color: 'EAB308' }),
      cell('필수 정보 전부 누락 (16.5%)', { width: 5460 }),
    ]}),
  ],
});
children.push(zeroTable);
children.push(p(''));
children.push(p([
  txt('시사점: ', { bold: true }),
  txt('0점 시나리오의 '),
  txt('83% (263건)', { bold: true, color: 'EF4444' }),
  txt(' 가 음수 페널티 발생. SKIX 가 무엇을 절대 빠뜨리면 안 되는지 명확한 가이드 필요.'),
], { spacing: { after: 200 } }));

// 8. 100점 시나리오
children.push(h2('8. 100점 시나리오 32건 — 만점의 함정'));
const perfectTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 1560, 1560, 1560, 1880],
  rows: [
    new TableRow({ children: [
      headerCell('Theme', 2800),
      headerCell('100점 건수', 1560, AlignmentType.RIGHT),
      headerCell('전체', 1560, AlignmentType.RIGHT),
      headerCell('100점 비율', 1560, AlignmentType.RIGHT),
      headerCell('', 1880),
    ]}),
    new TableRow({ children: [
      cell('hedging', { width: 2800 }),
      cell('10', { width: 1560, align: AlignmentType.RIGHT, bold: true }),
      cell('167', { width: 1560, align: AlignmentType.RIGHT }),
      cell('6.0%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('health_data_tasks', { width: 2800 }),
      cell('8', { width: 1560, align: AlignmentType.RIGHT, bold: true }),
      cell('115', { width: 1560, align: AlignmentType.RIGHT }),
      cell('7.0%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('context_seeking', { width: 2800 }),
      cell('5', { width: 1560, align: AlignmentType.RIGHT }),
      cell('179', { width: 1560, align: AlignmentType.RIGHT }),
      cell('2.8%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('global_health', { width: 2800 }),
      cell('5', { width: 1560, align: AlignmentType.RIGHT }),
      cell('280', { width: 1560, align: AlignmentType.RIGHT }),
      cell('1.8%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('communication', { width: 2800 }),
      cell('2', { width: 1560, align: AlignmentType.RIGHT }),
      cell('111', { width: 1560, align: AlignmentType.RIGHT }),
      cell('1.8%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('emergency_referrals', { width: 2800 }),
      cell('1', { width: 1560, align: AlignmentType.RIGHT }),
      cell('66', { width: 1560, align: AlignmentType.RIGHT }),
      cell('1.5%', { width: 1560, align: AlignmentType.RIGHT }),
      cell('', { width: 1880 }),
    ]}),
    new TableRow({ children: [
      cell('complex_responses', { width: 2800 }),
      cell('1', { width: 1560, align: AlignmentType.RIGHT }),
      cell('82', { width: 1560, align: AlignmentType.RIGHT }),
      cell('1.2%', { width: 1560, align: AlignmentType.RIGHT, bold: true, color: 'EF4444' }),
      cell('', { width: 1880 }),
    ]}),
  ],
});
children.push(perfectTable);
children.push(p(''));
children.push(p([
  txt('주의: ', { bold: true }),
  txt('100점 시나리오 32건의 평균 rubric items = '),
  txt('4.7개', { bold: true }),
  txt(' (전체 평균 11.8). 즉 '),
  txt('채점 기준이 적은 단순 시나리오에서만 만점 가능', { bold: true }),
  txt('. 복합·구조화 응답에서는 일관된 만점 어려움.'),
], { spacing: { after: 200 } }));

children.push(new Paragraph({ children: [new PageBreak()] }));

// 9. 개선 우선순위
children.push(h2('9. SKIX 개선 우선순위 (근거 기반)'));
const prioTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [700, 2400, 2400, 3860],
  rows: [
    new TableRow({ children: [
      headerCell('우선', 700, AlignmentType.CENTER),
      headerCell('영역', 2400),
      headerCell('근거', 2400),
      headerCell('권장 액션', 3860),
    ]}),
    new TableRow({ children: [
      cell('1', { width: 700, align: AlignmentType.CENTER, bold: true, color: 'FFFFFF', bg: 'EF4444', fontSize: 28 }),
      cell('context_seeking × instruction_following', { width: 2400, bold: true }),
      cell('가중점수 −46.8% (음수, 가장 심함)', { width: 2400 }),
      cell('"추가 정보 요청" 시나리오에서 형식·범위 지시 명확히 따르도록 prompt 보강', { width: 3860 }),
    ]}),
    new TableRow({ children: [
      cell('2', { width: 700, align: AlignmentType.CENTER, bold: true, color: 'FFFFFF', bg: 'EF4444', fontSize: 28 }),
      cell('complex_responses 전반', { width: 2400, bold: true }),
      cell('5개 중 3 axis 음수 (completeness −19.4 / instruction_following −23.0)', { width: 2400 }),
      cell('복잡한 multi-part 응답을 구조화·단계화하는 prompt template 추가', { width: 3860 }),
    ]}),
    new TableRow({ children: [
      cell('3', { width: 700, align: AlignmentType.CENTER, bold: true, color: 'FFFFFF', bg: 'EF4444', fontSize: 28 }),
      cell('accuracy 메타 rubric', { width: 2400, bold: true }),
      cell('70회 × −350pt 손실 (가장 자주 놓침)', { width: 2400 }),
      cell('의학적 사실 확인 단계 강화 — 인용 / source-based response', { width: 3860 }),
    ]}),
    new TableRow({ children: [
      cell('4', { width: 700, align: AlignmentType.CENTER, bold: true, color: '78350F', bg: 'EAB308', fontSize: 28 }),
      cell('communication × completeness 음수', { width: 2400 }),
      cell('−12.6% (응답 구조 짤 때 정보 누락)', { width: 2400 }),
      cell('"core question 빠르고 명확히 답변" — 질문 요약 + 핵심 답변 우선', { width: 3860 }),
    ]}),
    new TableRow({ children: [
      cell('5', { width: 700, align: AlignmentType.CENTER, bold: true, color: '78350F', bg: 'EAB308', fontSize: 28 }),
      cell('음수 페널티 회피', { width: 2400 }),
      cell('0점 시나리오의 83%', { width: 2400 }),
      cell('자주 발생하는 음수 항목 카탈로그화 → SKIX guideline 에 "이것은 빠뜨리면 안 됨" 명시', { width: 3860 }),
    ]}),
  ],
});
children.push(prioTable);
children.push(p(''));

// 10. 외부 모델 비교
children.push(h2('10. 외부 모델 비교 (HealthBench 논문)'));
const compareTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3120, 3120, 3120],
  rows: [
    new TableRow({ children: [
      headerCell('모델', 3120),
      headerCell('Hard subset 점수', 3120, AlignmentType.RIGHT),
      headerCell('SKIX 대비 차이', 3120),
    ]}),
    new TableRow({ children: [
      cell('o1', { width: 3120 }),
      cell('~52', { width: 3120, align: AlignmentType.RIGHT }),
      cell('+28', { width: 3120 }),
    ]}),
    new TableRow({ children: [
      cell('Claude 3.5 Sonnet', { width: 3120 }),
      cell('~40–50', { width: 3120, align: AlignmentType.RIGHT }),
      cell('+16–26', { width: 3120 }),
    ]}),
    new TableRow({ children: [
      cell('GPT-4o', { width: 3120 }),
      cell('~38', { width: 3120, align: AlignmentType.RIGHT }),
      cell('+14', { width: 3120 }),
    ]}),
    new TableRow({ children: [
      cell('SKIX (본 평가)', { width: 3120, bold: true, bg: 'EFF6FF' }),
      cell('23.67', { width: 3120, align: AlignmentType.RIGHT, bold: true, color: '6366F1', fontSize: 24, bg: 'EFF6FF' }),
      cell('—', { width: 3120, bg: 'EFF6FF' }),
    ]}),
    new TableRow({ children: [
      cell('GPT-4o-mini', { width: 3120 }),
      cell('~24', { width: 3120, align: AlignmentType.RIGHT }),
      cell('≈ SKIX', { width: 3120 }),
    ]}),
  ],
});
children.push(compareTable);
children.push(p(''));
children.push(p([
  txt('해석: ', { bold: true }),
  txt('SKIX 의 Hard subset 점수 (23.67) 는 GPT-4o-mini 수준. accuracy + completeness 보강으로 GPT-4o (~38) 까지 격차 ~15점 좁힐 수 있을 것 — 두 axis 가 현재 약점에 집중되어 있어 ROI 큼.'),
], { spacing: { after: 200 } }));

// 11. 다음 작업
children.push(h2('11. 권장 다음 작업'));
const nextActions = [
  '0점 시나리오 178건의 음수 항목 카탈로그화 — completeness 음수 항목을 일반 패턴으로 분류 (예: "follow-up 권유 누락", "specific drug list 누락" 등)',
  'Theme × Axis 매트릭스 기반 prompt 개선 — complex_responses 와 context_seeking 의 instruction_following 부분',
  'SKIX guideline 보강 — 가장 자주 met 되는 음수 항목 (omission) 을 negative list 로 작성',
  'Phase 3 확장 (선택) — Consensus 3,671건 import + batch 실행 후 본 분석과 cross-check',
];
nextActions.forEach((item, i) => {
  children.push(new Paragraph({
    numbering: { reference: 'numbered-list', level: 0 },
    children: [new TextRun({ text: item, size: 22 })],
  }));
});

// 푸터
children.push(p(''));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  border: { top: { style: BorderStyle.SINGLE, size: 6, color: 'D0D7DE' } },
  spacing: { before: 400, after: 100 },
  children: [
    new TextRun({ text: '본 보고서는 scripts/analyze_run_scores.py + scripts/analyze_hb_failures.py 출력에서 자동 정리.', size: 18, color: '64748B' }),
  ],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [
    new TextRun({ text: '데이터 보존: test_runs 테이블 의 job-20260518-191745-3b1b90 run.', size: 18, color: '64748B' }),
  ],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 100 },
  children: [
    new TextRun({ text: '© 의료 컴플라이언스 테스트 도구 — 2026', size: 18, color: '64748B' }),
  ],
}));

// ── 문서 생성 ──
const doc = new Document({
  creator: 'Medical Compliance Tester',
  title: 'HealthBench Hard 1,000건 분석 보고서',
  description: 'SKIX 의료 응답 평가 결과 분석',
  styles: {
    default: { document: { run: { font: 'Malgun Gothic', size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 32, bold: true, font: 'Malgun Gothic', color: '0F172A' },
        paragraph: { spacing: { before: 300, after: 200 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Malgun Gothic', color: '0F172A' },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, font: 'Malgun Gothic', color: '6366F1' },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [{
      reference: 'numbered-list',
      levels: [{
        level: 0,
        format: LevelFormat.DECIMAL,
        text: '%1.',
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children,
  }],
});

const outPath = path.join(__dirname, 'healthbench_hard_1000_analysis.docx');
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outPath, buffer);
  console.log('✓ 작성 완료:', outPath);
  console.log(`  크기: ${Math.round(buffer.length / 1024)} KB`);
}).catch(err => {
  console.error('에러:', err);
  process.exit(1);
});
