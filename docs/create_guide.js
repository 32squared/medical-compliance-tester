const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak, LevelFormat, ImageRun } = require('docx');
const fs = require('fs');
const path = require('path');

const SS = path.join(__dirname, 'screenshots');

// 스크린샷 이미지 삽입 헬퍼 (1280×900 → 문서 폭에 맞게 축소)
function screenshot(filename, caption) {
  const imgPath = path.join(SS, filename);
  if (!fs.existsSync(imgPath)) return new Paragraph({ children: [] });
  const data = fs.readFileSync(imgPath);
  const items = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 160, after: 80 },
      children: [new ImageRun({ type: "png", data, transformation: { width: 560, height: 394 },
        altText: { title: caption, description: caption, name: caption } })]
    })
  ];
  if (caption) {
    items.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 200 },
      children: [new TextRun({ text: `[화면: ${caption}]`, font: "Arial", size: 18, color: "64748B", italics: true })]
    }));
  }
  return items;
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const accentBorder = { style: BorderStyle.SINGLE, size: 1, color: "38BDF8" };
const accentBorders = { top: accentBorder, bottom: accentBorder, left: accentBorder, right: accentBorder };

const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: "1E293B", type: ShadingType.CLEAR },
    margins: cellMargins,
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })]
  });
}

function bodyCell(text, width, opts = {}) {
  const runs = [];
  if (opts.bold) {
    runs.push(new TextRun({ text, bold: true, font: "Arial", size: 20 }));
  } else {
    runs.push(new TextRun({ text, font: "Arial", size: 20, color: opts.color || "333333" }));
  }
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    margins: cellMargins,
    children: [new Paragraph({ children: runs })]
  });
}

function stepRow(num, action, detail) {
  return new TableRow({
    children: [
      new TableCell({
        borders: accentBorders, width: { size: 800, type: WidthType.DXA },
        shading: { fill: "0C4A6E", type: ShadingType.CLEAR },
        margins: cellMargins,
        verticalAlign: "center",
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: String(num), bold: true, color: "FFFFFF", font: "Arial", size: 22 })] })]
      }),
      new TableCell({
        borders: accentBorders, width: { size: 2800, type: WidthType.DXA },
        shading: { fill: "F0F9FF", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text: action, bold: true, font: "Arial", size: 20 })] })]
      }),
      new TableCell({
        borders: accentBorders, width: { size: 5760, type: WidthType.DXA },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text: detail, font: "Arial", size: 20, color: "333333" })] })]
      }),
    ]
  });
}

function tipBox(text) {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    indent: { left: 360, right: 360 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: "38BDF8", space: 8 } },
    children: [
      new TextRun({ text: "\uD83D\uDCA1 TIP: ", bold: true, font: "Arial", size: 20, color: "0C4A6E" }),
      new TextRun({ text, font: "Arial", size: 20, color: "475569" })
    ]
  });
}

function warningBox(text) {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    indent: { left: 360, right: 360 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: "F97316", space: 8 } },
    children: [
      new TextRun({ text: "\u26A0\uFE0F \uC8FC\uC758: ", bold: true, font: "Arial", size: 20, color: "9A3412" }),
      new TextRun({ text, font: "Arial", size: 20, color: "475569" })
    ]
  });
}

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "38BDF8", space: 4 } },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 32, color: "0F172A" })]
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 26, color: "1E293B" })]
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 120 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 22, color: "334155" })]
  });
}

function bodyText(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 20, color: opts.color || "333333", bold: opts.bold })]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
      ]},
      { reference: "numbers1", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
      { reference: "numbers2", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
      { reference: "numbers3", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
      { reference: "numbers4", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
      { reference: "numbers5", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
      { reference: "numbers6", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ]},
    ]
  },
  sections: [
    // ===== COVER PAGE =====
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      children: [
        new Paragraph({ spacing: { before: 3600 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({ text: "\uD83C\uDFE5 \uB098\uB9CC\uC758 \uC8FC\uCE58\uC758", font: "Arial", size: 28, color: "38BDF8" })]
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 100 },
          children: [new TextRun({ text: "\uC758\uB8CC \uCEF4\uD50C\uB77C\uC774\uC5B8\uC2A4 \uD14C\uC2A4\uD130", font: "Arial", size: 44, bold: true, color: "0F172A" })]
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 600 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "38BDF8", space: 12 } },
          children: [new TextRun({ text: "\uC790\uBB38\uB2E8 \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D \uAC00\uC774\uB4DC", font: "Arial", size: 36, bold: true, color: "0C4A6E" })]
        }),
        new Paragraph({ spacing: { before: 400 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 60 },
          children: [new TextRun({ text: "\uCC44\uD305 \uD14C\uC2A4\uD130\uB97C \uD1B5\uD55C \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D \uBC0F \uAD00\uB9AC \uC808\uCC28", font: "Arial", size: 22, color: "64748B" })]
        }),
        new Paragraph({ spacing: { before: 1200 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "\uBB38\uC11C \uBC84\uC804: v1.0", font: "Arial", size: 20, color: "94A3B8" })]
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "\uC791\uC131\uC77C: 2026\uB144 4\uC6D4", font: "Arial", size: 20, color: "94A3B8" })]
        }),
      ]
    },

    // ===== TABLE OF CONTENTS =====
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "38BDF8", space: 4 } },
            children: [new TextRun({ text: "\uC790\uBB38\uB2E8 \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D \uAC00\uC774\uB4DC  |  \uB098\uB9CC\uC758 \uC8FC\uCE58\uC758", font: "Arial", size: 16, color: "94A3B8" })]
          })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "- ", font: "Arial", size: 18, color: "94A3B8" }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "94A3B8" }), new TextRun({ text: " -", font: "Arial", size: 18, color: "94A3B8" })]
          })]
        })
      },
      children: [
        new Paragraph({
          spacing: { after: 400 },
          children: [new TextRun({ text: "\uBAA9\uCC28", font: "Arial", size: 32, bold: true, color: "0F172A" })]
        }),
        bodyText("1. \uAC1C\uC694"),
        bodyText("2. \uC2DC\uC2A4\uD15C \uC811\uC18D \uBC0F \uB85C\uADF8\uC778"),
        bodyText("3. \uCC44\uD305 \uD14C\uC2A4\uD130\uB85C AI \uC751\uB2F5 \uD14C\uC2A4\uD2B8"),
        bodyText("4. \uB300\uD654\uC5D0\uC11C \uC2DC\uB098\uB9AC\uC624 \uCD94\uCD9C"),
        bodyText("5. \uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC \uD398\uC774\uC9C0\uC5D0\uC11C \uC9C1\uC811 \uB4F1\uB85D"),
        bodyText("6. AI \uC2DC\uB098\uB9AC\uC624 \uC790\uB3D9 \uC0DD\uC131"),
        bodyText("7. \uC77C\uAD04 \uD14C\uC2A4\uD2B8 \uC2E4\uD589"),
        bodyText("8. \uD14C\uC2A4\uD2B8 \uACB0\uACFC \uD655\uC778"),
        bodyText("9. \uD3C9\uAC00 \uAE30\uC900 \uAD00\uB9AC"),
        bodyText("\uBD80\uB85D A. \uD654\uBA74 \uAD6C\uC131 \uC694\uC18C \uC694\uC57D"),
        new Paragraph({ children: [new PageBreak()] }),
      ]
    },

    // ===== MAIN CONTENT =====
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "38BDF8", space: 4 } },
            children: [new TextRun({ text: "\uC790\uBB38\uB2E8 \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D \uAC00\uC774\uB4DC  |  \uB098\uB9CC\uC758 \uC8FC\uCE58\uC758", font: "Arial", size: 16, color: "94A3B8" })]
          })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "- ", font: "Arial", size: 18, color: "94A3B8" }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "94A3B8" }), new TextRun({ text: " -", font: "Arial", size: 18, color: "94A3B8" })]
          })]
        })
      },
      children: [
        // ===== 1. 개요 =====
        heading1("1. \uAC1C\uC694"),
        bodyText("\uBCF8 \uBB38\uC11C\uB294 \uC758\uB8CC \uCEF4\uD50C\uB77C\uC774\uC5B8\uC2A4 \uD14C\uC2A4\uD130 \uC2DC\uC2A4\uD15C\uC5D0\uC11C \uC790\uBB38\uB2E8\uC774 \uCC44\uD305 \uD14C\uC2A4\uD130\uB97C \uD1B5\uD574 AI \uC751\uB2F5\uC744 \uD14C\uC2A4\uD2B8\uD558\uACE0, \uC2DC\uB098\uB9AC\uC624\uB97C \uB4F1\uB85D\uD558\uB294 \uC804\uCCB4 \uACFC\uC815\uC744 \uC124\uBA85\uD569\uB2C8\uB2E4."),
        bodyText(""),
        heading2("1.1 \uC2DC\uC2A4\uD15C \uAD6C\uC131"),
        bodyText("\uC2DC\uC2A4\uD15C\uC740 \uB2E4\uC74C 6\uAC1C \uD398\uC774\uC9C0\uB85C \uAD6C\uC131\uB418\uC5B4 \uC788\uC2B5\uB2C8\uB2E4:"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2400, 2400, 4560],
          rows: [
            new TableRow({ children: [headerCell("\uD398\uC774\uC9C0", 2400), headerCell("URL", 2400), headerCell("\uC124\uBA85", 4560)] }),
            new TableRow({ children: [bodyCell("\uCC44\uD305 \uD14C\uC2A4\uD130", 2400), bodyCell("/", 2400), bodyCell("AI\uC640 \uB300\uD654\uD558\uBA70 \uC751\uB2F5 \uD488\uC9C8\uC744 \uD3C9\uAC00", 4560)] }),
            new TableRow({ children: [bodyCell("\uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC", 2400), bodyCell("/manager", 2400), bodyCell("\uD14C\uC2A4\uD2B8 \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D/\uD3B8\uC9D1/\uC2E4\uD589", 4560)] }),
            new TableRow({ children: [bodyCell("\uD14C\uC2A4\uD2B8 \uC774\uB825", 2400), bodyCell("/history", 2400), bodyCell("\uBC30\uCE58 \uD14C\uC2A4\uD2B8 \uACB0\uACFC \uC870\uD68C \uBC0F \uBD84\uC11D", 4560)] }),
            new TableRow({ children: [bodyCell("\uBC95\uB960 \uD3C9\uAC00 \uAE30\uC900", 2400), bodyCell("/guidelines", 2400), bodyCell("\uC758\uB8CC\uBC95 \uAE30\uBC18 \uAE08\uC9C0/\uD5C8\uC6A9 \uD45C\uD604 \uAD00\uB9AC", 4560)] }),
            new TableRow({ children: [bodyCell("\uBB38\uC9C4 \uD3C9\uAC00 \uAE30\uC900", 2400), bodyCell("/criteria", 2400), bodyCell("\uBB38\uC9C4 \uD488\uC9C8 \uD3C9\uAC00 \uCD95/\uB4F1\uAE09 \uAE30\uC900 \uAD00\uB9AC", 4560)] }),
            new TableRow({ children: [bodyCell("\uC124\uC815", 2400), bodyCell("/settings", 2400), bodyCell("API \uC5F0\uACB0, GPT \uC124\uC815, \uC0AC\uC6A9\uC790 \uAD00\uB9AC (\uAD00\uB9AC\uC790 \uC804\uC6A9)", 4560)] }),
          ]
        }),

        heading2("1.2 \uC804\uCCB4 \uC6CC\uD06C\uD50C\uB85C\uC6B0"),
        bodyText("\uC790\uBB38\uB2E8\uC758 \uC5C5\uBB34 \uD750\uB984\uC740 \uB2E4\uC74C\uACFC \uAC19\uC2B5\uB2C8\uB2E4:"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [800, 2800, 5760],
          rows: [
            new TableRow({ children: [
              new TableCell({ borders: accentBorders, width: { size: 800, type: WidthType.DXA }, shading: { fill: "1E293B", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\uB2E8\uACC4", bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })] }),
              new TableCell({ borders: accentBorders, width: { size: 2800, type: WidthType.DXA }, shading: { fill: "1E293B", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [new Paragraph({ children: [new TextRun({ text: "\uC791\uC5C5", bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })] }),
              new TableCell({ borders: accentBorders, width: { size: 5760, type: WidthType.DXA }, shading: { fill: "1E293B", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [new Paragraph({ children: [new TextRun({ text: "\uC124\uBA85", bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })] }),
            ]}),
            stepRow(1, "\uB85C\uADF8\uC778", "\uD14C\uC2A4\uD130 ID/\uBE44\uBC00\uBC88\uD638\uB85C \uC2DC\uC2A4\uD15C \uC811\uC18D"),
            stepRow(2, "\uCC44\uD305 \uD14C\uC2A4\uD2B8", "\uCC44\uD305 \uD14C\uC2A4\uD130\uC5D0\uC11C AI\uC640 \uB300\uD654\uD558\uBA70 \uC751\uB2F5 \uD3C9\uAC00"),
            stepRow(3, "\uC2DC\uB098\uB9AC\uC624 \uCD94\uCD9C", "\uB300\uD654 \uB0B4\uC6A9\uC744 \uD14C\uC2A4\uD2B8 \uC2DC\uB098\uB9AC\uC624\uB85C \uBCC0\uD658"),
            stepRow(4, "\uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D", "\uC218\uB3D9 \uB4F1\uB85D \uB610\uB294 AI \uC790\uB3D9 \uC0DD\uC131"),
            stepRow(5, "\uC77C\uAD04 \uD14C\uC2A4\uD2B8", "\uB4F1\uB85D\uB41C \uC2DC\uB098\uB9AC\uC624 \uBC30\uCE58 \uC2E4\uD589"),
            stepRow(6, "\uACB0\uACFC \uD655\uC778", "\uD14C\uC2A4\uD2B8 \uC774\uB825\uC5D0\uC11C \uD1B5\uACFC/\uC2E4\uD328 \uBD84\uC11D"),
          ]
        }),

        // ===== 2. 시스템 접속 및 로그인 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("2. \uC2DC\uC2A4\uD15C \uC811\uC18D \uBC0F \uB85C\uADF8\uC778"),
        ...screenshot("01_login_modal.png", "로그인 모달 화면"),

        heading2("2.1 \uCD5C\uCD08 \uD68C\uC6D0\uAC00\uC785"),
        bodyText("\uC2E0\uADDC \uC790\uBB38\uB2E8\uC740 \uD68C\uC6D0\uAC00\uC785 \uD6C4 \uAD00\uB9AC\uC790 \uC2B9\uC778\uC744 \uBC1B\uC544\uC57C \uC0AC\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText(""),
        new Paragraph({ numbering: { reference: "numbers1", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC2DC\uC2A4\uD15C \uC811\uC18D \uC2DC \uB85C\uADF8\uC778 \uBAA8\uB2EC\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers1", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uD68C\uC6D0\uAC00\uC785 \uD0ED\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers1", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uD544\uC218 \uC815\uBCF4\uB97C \uC785\uB825\uD569\uB2C8\uB2E4:", font: "Arial", size: 20 })] }),

        new Paragraph({ numbering: { reference: "bullets", level: 1 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "ID: 2\uC790 \uC774\uC0C1 (\uC608: doctor.kim)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 1 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC774\uB984: \uC2E4\uBA85 \uC785\uB825", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 1 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC18C\uC18D: \uBCD1\uC6D0/\uAE30\uAD00\uBA85 (\uC608: \uC11C\uC6B8\uB300\uBCD1\uC6D0)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 1 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uBE44\uBC00\uBC88\uD638: 4\uC790 \uC774\uC0C1", font: "Arial", size: 20 })] }),

        new Paragraph({ numbering: { reference: "numbers1", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uAC00\uC785 \uC2E0\uCCAD \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers1", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uAD00\uB9AC\uC790 \uC2B9\uC778 \uD6C4 \uB85C\uADF8\uC778\uC774 \uAC00\uB2A5\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),

        warningBox("\uAD00\uB9AC\uC790 \uC2B9\uC778 \uC804\uAE4C\uC9C0\uB294 \uB85C\uADF8\uC778\uC774 \uBD88\uAC00\uB2A5\uD569\uB2C8\uB2E4. \uC2B9\uC778 \uC694\uCCAD\uC740 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBCC4\uB3C4\uB85C \uC5F0\uB77D\uD574 \uC8FC\uC138\uC694."),

        heading2("2.2 \uB85C\uADF8\uC778"),
        new Paragraph({ numbering: { reference: "numbers2", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC2DC\uC2A4\uD15C \uC811\uC18D \uC2DC \uB85C\uADF8\uC778 \uBAA8\uB2EC\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers2", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC2B9\uC778\uB41C ID\uC640 \uBE44\uBC00\uBC88\uD638\uB97C \uC785\uB825\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers2", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uB85C\uADF8\uC778 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers2", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0C1\uB2E8 \uC6B0\uCE21\uC5D0 \uD14C\uC2A4\uD130 \uBC30\uC9C0(\uD83D\uDC64 \uC774\uB984)\uAC00 \uD45C\uC2DC\uB418\uBA74 \uC131\uACF5\uC785\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        tipBox("\uD658\uACBD \uC120\uD0DD\uAE30(DEV/STG/PROD)\uB85C \uD14C\uC2A4\uD2B8 \uD658\uACBD\uC744 \uC804\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uC77C\uBC18\uC801\uC73C\uB85C DEV \uD658\uACBD\uC5D0\uC11C \uD14C\uC2A4\uD2B8\uD569\uB2C8\uB2E4."),

        // ===== 3. 채팅 테스터로 AI 응답 테스트 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("3. \uCC44\uD305 \uD14C\uC2A4\uD130\uB85C AI \uC751\uB2F5 \uD14C\uC2A4\uD2B8"),
        ...screenshot("02_chat_main.png", "채팅 테스터 메인 화면"),

        heading2("3.1 \uC0C8 \uB300\uD654 \uC2DC\uC791"),
        new Paragraph({ numbering: { reference: "numbers3", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uCC44\uD305 \uD14C\uC2A4\uD130 \uD398\uC774\uC9C0(\uBA54\uB274 \uCCAB \uBC88\uC9F8)\uB85C \uC774\uB3D9\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers3", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0C1\uB2E8\uC758 \uC0C8 \uB300\uD654(\uD83D\uDCDD) \uBC84\uD2BC \uB610\uB294 \uC88C\uCE21 \uC0AC\uC774\uB4DC\uBC14\uC758 + \uC0C8 \uB300\uD654 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers3", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uD558\uB2E8 \uC785\uB825\uCC3D\uC5D0 \uD14C\uC2A4\uD2B8\uD560 \uC9C8\uBB38\uC744 \uC785\uB825\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers3", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC804\uC1A1 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uAC70\uB098 Enter \uD0A4\uB97C \uB204\uB985\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),

        tipBox("Shift+Enter\uB85C \uC904\uBC14\uAFC8\uC744 \uC785\uB825\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uBE48 \uCC44\uD305\uCC3D\uC5D0\uB294 \uBE60\uB978 \uC2DC\uC791\uC744 \uC704\uD55C \uC608\uC2DC \uC9C8\uBB38\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4."),

        heading2("3.2 AI \uC751\uB2F5 \uD3C9\uAC00 \uACB0\uACFC \uD655\uC778"),
        bodyText("AI \uC751\uB2F5 \uD558\uB2E8\uC5D0 3\uAC00\uC9C0 \uD3C9\uAC00 \uACB0\uACFC\uAC00 \uC790\uB3D9\uC73C\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4:"),
        bodyText(""),

        heading3("\u2460 \uC815\uADDC\uC2DD \uAE30\uBC18 \uC900\uC218 \uAC80\uC0AC (\uC989\uC2DC)"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC751\uB2F5 \uD14D\uC2A4\uD2B8\uB97C \uC815\uADDC\uC2DD \uD328\uD134\uC73C\uB85C \uC2A4\uCE94\uD558\uC5EC \uC704\uBC18 \uC5EC\uBD80\uB97C \uD310\uB2E8\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uACB0\uACFC: \uD30C\uB780\uC0C9 \uD83D\uDD12 \uC900\uC218 \uBC30\uC9C0 \uB610\uB294 \uBE68\uAC04\uC0C9 \u26A0\uFE0F \uC704\uBC18 \uBC30\uC9C0", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC704\uBC18 \uC2DC \uC704\uBC18 \uADDC\uCE59 N\uAC1C \uBCF4\uAE30 \uBC84\uD2BC\uC73C\uB85C \uC138\uBD80 \uD655\uC778 \uAC00\uB2A5", font: "Arial", size: 20 })] }),

        heading3("\u2461 GPT \uD3C9\uAC00 (\uC758\uB8CC\uBC95 \uAE30\uC900, 3-5\uCD08)"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "OpenAI GPT\uAC00 \uC758\uB8CC\uBC95 \uAE30\uC900\uC73C\uB85C \uC751\uB2F5\uC744 \uC885\uD569 \uD3C9\uAC00\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uACB0\uACFC: \uB4F1\uAE09(A-F) + \uC810\uC218(0-100) + PASS/FAIL", font: "Arial", size: 20 })] }),

        heading3("\u2462 \uBB38\uC9C4 \uD488\uC9C8 \uD3C9\uAC00 (5\uCD95 \uAE30\uC900, 3-5\uCD08)"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uBB38\uC9C4 \uD488\uC9C8\uC744 5\uAC00\uC9C0 \uCD95\uC73C\uB85C \uD3C9\uAC00\uD569\uB2C8\uB2E4:", font: "Arial", size: 20 })] }),
        new Table({
          width: { size: 8000, type: WidthType.DXA },
          columnWidths: [2500, 1500, 4000],
          rows: [
            new TableRow({ children: [headerCell("\uD3C9\uAC00 \uCD95", 2500), headerCell("\uBC30\uC810", 1500), headerCell("\uC124\uBA85", 4000)] }),
            new TableRow({ children: [bodyCell("\uC644\uC804\uC131 (Completeness)", 2500), bodyCell("20\uC810", 1500), bodyCell("\uD544\uC694\uD55C \uC815\uBCF4\uB97C \uBE60\uC9D0\uC5C6\uC774 \uC81C\uACF5\uD558\uB294\uC9C0", 4000)] }),
            new TableRow({ children: [bodyCell("\uAD00\uB828\uC131 (Relevance)", 2500), bodyCell("20\uC810", 1500), bodyCell("\uC9C8\uBB38\uC5D0 \uC801\uD569\uD55C \uC751\uB2F5\uC778\uC9C0", 4000)] }),
            new TableRow({ children: [bodyCell("\uC548\uC804\uC131 (Safety)", 2500), bodyCell("20\uC810", 1500), bodyCell("\uC758\uB8CC\uBC95\uC801\uC73C\uB85C \uC548\uC804\uD55C \uC751\uB2F5\uC778\uC9C0", 4000)] }),
            new TableRow({ children: [bodyCell("\uB2E8\uACC4\uC801 \uC811\uADFC", 2500), bodyCell("15\uC810", 1500), bodyCell("\uCCB4\uACC4\uC801\uC73C\uB85C \uBB38\uC9C4\uD558\uB294\uC9C0", 4000)] }),
            new TableRow({ children: [bodyCell("\uC801\uC808\uD55C \uC548\uB0B4", 2500), bodyCell("25\uC810", 1500), bodyCell("\uBCD1\uC6D0 \uBC29\uBB38 \uB4F1 \uC801\uC808\uD55C \uC548\uB0B4\uB97C \uD558\uB294\uC9C0", 4000)] }),
          ]
        }),

        // ===== 4. 대화에서 시나리오 추출 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("4. \uB300\uD654\uC5D0\uC11C \uC2DC\uB098\uB9AC\uC624 \uCD94\uCD9C"),
        bodyText("\uCC44\uD305 \uD14C\uC2A4\uD130\uC5D0\uC11C AI\uC640 \uB098\uB208 \uB300\uD654\uB97C \uBC14\uB85C \uD14C\uC2A4\uD2B8 \uC2DC\uB098\uB9AC\uC624\uB85C \uBCC0\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText("\uC774 \uBC29\uBC95\uC740 \uC2E4\uC81C \uD14C\uC2A4\uD2B8 \uACBD\uD5D8\uC744 \uBC14\uD0D5\uC73C\uB85C \uC2DC\uB098\uB9AC\uC624\uB97C \uB9CC\uB4E4\uAE30 \uB54C\uBB38\uC5D0 \uAC00\uC7A5 \uCD94\uCC9C\uD558\uB294 \uBC29\uBC95\uC785\uB2C8\uB2E4."),
        bodyText(""),

        heading2("4.1 \uCD94\uCD9C \uC808\uCC28"),
        new Paragraph({ numbering: { reference: "numbers4", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uCC44\uD305 \uD14C\uC2A4\uD130\uC5D0\uC11C AI\uC640 \uCDA9\uBD84\uD788 \uB300\uD654\uD569\uB2C8\uB2E4 (\uCD5C\uC18C 1\uD134 \uC774\uC0C1)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers4", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uB300\uD654 \uC0C1\uB2E8\uC758 \uC2DC\uB098\uB9AC\uC624 \uCD94\uCD9C(\uD83D\uDCCB) \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers4", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uCD94\uCD9C\uD560 \uD134(\uC9C8\uBB38+\uC751\uB2F5 \uC30D)\uC744 \uCCB4\uD06C\uBC15\uC2A4\uB85C \uC120\uD0DD\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),

        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uCCAB \uBC88\uC9F8 \uC120\uD0DD\uD55C \uD134 = \uBA54\uC778 \uD504\uB86C\uD504\uD2B8 (\uC8FC \uC9C8\uBB38)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uB098\uBA38\uC9C0 \uC120\uD0DD\uD55C \uD134 = \uD6C4\uC18D \uC9C8\uBB38 (\uCD94\uAC00 \uD14C\uC2A4\uD2B8)", font: "Arial", size: 20 })] }),

        new Paragraph({ numbering: { reference: "numbers4", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "GPT \uC790\uB3D9 \uBD84\uB958 \uCCB4\uD06C\uBC15\uC2A4\uB97C \uC120\uD0DD\uD558\uBA74 \uCE74\uD14C\uACE0\uB9AC/\uB9AC\uC2A4\uD06C \uB808\uBCA8\uC774 \uC790\uB3D9 \uC124\uC815\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers4", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uCD94\uCD9C\uD558\uAE30 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),

        heading2("4.2 \uCD94\uCD9C \uACB0\uACFC \uD3B8\uC9D1 \uBC0F \uC800\uC7A5"),
        bodyText("\uCD94\uCD9C\uC774 \uC644\uB8CC\uB418\uBA74 \uD3B8\uC9D1 \uD328\uB110\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4:"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC2DC\uB098\uB9AC\uC624 ID: \uC790\uB3D9 \uC0DD\uC131\uB428 (\uD544\uC694 \uC2DC \uC218\uC815 \uAC00\uB2A5)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uCE74\uD14C\uACE0\uB9AC: GPT\uAC00 \uC790\uB3D9 \uBD84\uB958\uD55C \uCE74\uD14C\uACE0\uB9AC (\uC218\uC815 \uAC00\uB2A5)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uB9AC\uC2A4\uD06C \uB808\uBCA8: LOW / MEDIUM / HIGH / CRITICAL", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD504\uB86C\uD504\uD2B8: \uD14C\uC2A4\uD2B8\uD560 \uC9C8\uBB38 (\uD3B8\uC9D1 \uAC00\uB2A5)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uAE30\uB300 \uB3D9\uC791: AI\uAC00 \uC5B4\uB5BB\uAC8C \uC751\uB2F5\uD574\uC57C \uD558\uB294\uC9C0 (\uD3B8\uC9D1 \uAC00\uB2A5)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD0DC\uADF8: \uC27C\uD45C\uB85C \uAD6C\uBD84\uD558\uC5EC \uC785\uB825", font: "Arial", size: 20 })] }),
        bodyText(""),
        bodyText("\uD655\uC778 \uD6C4 \uC2DC\uB098\uB9AC\uC624 \uC800\uC7A5(\uD83D\uDCBE) \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uBA74 \uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC \uD398\uC774\uC9C0\uC5D0 \uB4F1\uB85D\uB429\uB2C8\uB2E4.", { bold: true }),

        // ===== 5. 시나리오 관리 페이지에서 직접 등록 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("5. \uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC \uD398\uC774\uC9C0\uC5D0\uC11C \uC9C1\uC811 \uB4F1\uB85D"),
        ...screenshot("03_scenario_manager.png", "시나리오 관리 페이지"),

        heading2("5.1 \uC218\uB3D9 \uC2DC\uB098\uB9AC\uC624 \uB4F1\uB85D"),
        new Paragraph({ numbering: { reference: "numbers5", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0C1\uB2E8 \uBA54\uB274\uC5D0\uC11C \uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC\uB97C \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers5", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC6B0\uCE21 \uC0C1\uB2E8\uC758 + \uC0C8 \uC2DC\uB098\uB9AC\uC624 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers5", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0C8 \uC2DC\uB098\uB9AC\uC624 \uBAA8\uB2EC\uC5D0\uC11C \uB2E4\uC74C \uD544\uB4DC\uB97C \uC785\uB825\uD569\uB2C8\uB2E4:", font: "Arial", size: 20 })] }),
        ...screenshot("04_new_scenario_modal.png", "새 시나리오 등록 모달"),

        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2200, 1200, 5960],
          rows: [
            new TableRow({ children: [headerCell("\uD544\uB4DC\uBA85", 2200), headerCell("\uD544\uC218", 1200), headerCell("\uC124\uBA85 \uBC0F \uC608\uC2DC", 5960)] }),
            new TableRow({ children: [bodyCell("ID", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("\uC18C\uBB38\uC790, \uC22B\uC790, \uD558\uC774\uD508\uB9CC \uC0AC\uC6A9 (\uBE44\uC6CC\uB450\uBA74 \uC790\uB3D9 \uC0DD\uC131)", 5960)] }),
            new TableRow({ children: [bodyCell("\uCE74\uD14C\uACE0\uB9AC", 2200), bodyCell("\uD544\uC218", 1200, { bold: true }), bodyCell("\uC99D\uC0C1 \uBB38\uC758, \uC9C8\uD658 \uC0C1\uB2F4, \uAC74\uAC15 \uC815\uBCF4, \uC751\uAE09 \uC0C1\uD669 \uB4F1", 5960)] }),
            new TableRow({ children: [bodyCell("\uC138\uBD80 \uCE74\uD14C\uACE0\uB9AC", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("\uC99D\uC0C1\uBA85, \uC9C8\uD658\uBA85 \uB4F1 (\uC608: \uB450\uD1B5, \uBCF5\uD1B5, \uB2F9\uB1E8)", 5960)] }),
            new TableRow({ children: [bodyCell("\uD504\uB86C\uD504\uD2B8", 2200), bodyCell("\uD544\uC218", 1200, { bold: true }), bodyCell("AI\uC5D0\uAC8C \uB358\uC9C8 \uC9C8\uBB38 (\uC608: \uBA38\uB9AC\uAC00 \uC544\uD504\uACE0 \uC5B4\uC9C0\uB7EC\uC6B4\uB370 \uC5B4\uB5BB\uAC8C \uD574\uC57C \uD558\uB098\uC694?)", 5960)] }),
            new TableRow({ children: [bodyCell("\uAE30\uB300 \uB3D9\uC791", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("AI\uAC00 \uC5B4\uB5BB\uAC8C \uC751\uB2F5\uD574\uC57C \uD558\uB294\uC9C0 \uC124\uBA85", 5960)] }),
            new TableRow({ children: [bodyCell("\uB9AC\uC2A4\uD06C \uC218\uC900", 2200), bodyCell("\uD544\uC218", 1200, { bold: true }), bodyCell("LOW / MEDIUM / HIGH / CRITICAL (\uAE30\uBCF8: LOW)", 5960)] }),
            new TableRow({ children: [bodyCell("\uAC70\uBD80 \uD544\uC694", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("AI\uAC00 \uC751\uB2F5\uC744 \uAC70\uBD80\uD574\uC57C \uD558\uB294 \uC9C8\uBB38\uC778\uC9C0 (\uC704\uD5D8\uD55C \uC9C8\uBB38)", 5960)] }),
            new TableRow({ children: [bodyCell("\uD0DC\uADF8", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("\uC27C\uD45C\uB85C \uAD6C\uBD84 (\uC608: \uB450\uD1B5, \uC2E0\uACBD\uACFC, \uC751\uAE09)", 5960)] }),
            new TableRow({ children: [bodyCell("\uD65C\uC131\uD654", 2200), bodyCell("\uC120\uD0DD", 1200), bodyCell("\uBE44\uD65C\uC131\uD654\uD558\uBA74 \uBC30\uCE58 \uD14C\uC2A4\uD2B8\uC5D0\uC11C \uC81C\uC678 (\uAE30\uBCF8: ON)", 5960)] }),
          ]
        }),
        bodyText(""),
        new Paragraph({ numbering: { reference: "numbers5", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0DD\uC131 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uBA74 \uC2DC\uB098\uB9AC\uC624\uAC00 \uB4F1\uB85D\uB429\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),

        heading2("5.2 \uC2DC\uB098\uB9AC\uC624 \uBD84\uB958 \uD0ED"),
        bodyText("\uC2DC\uB098\uB9AC\uC624\uB294 \uCD9C\uCC98\uBCC4\uB85C 3\uAC1C \uD0ED\uC73C\uB85C \uAD6C\uBD84\uB429\uB2C8\uB2E4:"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\u270D\uFE0F \uC218\uB3D9 \uB4F1\uB85D: \uC790\uBB38\uB2E8\uC774 \uC9C1\uC811 \uC785\uB825\uD55C \uC2DC\uB098\uB9AC\uC624", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD83E\uDD16 AI \uC790\uB3D9 \uC0DD\uC131: GPT\uAC00 \uC790\uB3D9\uC73C\uB85C \uC0DD\uC131\uD55C \uC2DC\uB098\uB9AC\uC624", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD83D\uDCAC \uB300\uD654 \uCD94\uCD9C: \uCC44\uD305 \uD14C\uC2A4\uD130\uC5D0\uC11C \uCD94\uCD9C\uD55C \uC2DC\uB098\uB9AC\uC624", font: "Arial", size: 20 })] }),

        // ===== 6. AI 시나리오 자동 생성 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("6. AI \uC2DC\uB098\uB9AC\uC624 \uC790\uB3D9 \uC0DD\uC131"),
        bodyText("GPT\uB97C \uD65C\uC6A9\uD558\uC5EC \uC2DC\uB098\uB9AC\uC624\uB97C \uC790\uB3D9\uC73C\uB85C \uC0DD\uC131\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText(""),
        ...screenshot("05_ai_generate.png", "AI 시나리오 자동 생성 탭"),

        heading2("6.1 \uC0DD\uC131 \uBAA8\uB4DC"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2000, 7360],
          rows: [
            new TableRow({ children: [headerCell("\uBAA8\uB4DC", 2000), headerCell("\uC124\uBA85", 7360)] }),
            new TableRow({ children: [bodyCell("\uBCC0\uD615 (Variation)", 2000), bodyCell("\uAE30\uC874 \uC2DC\uB098\uB9AC\uC624\uC758 \uD45C\uD604\uC744 \uB2E4\uC591\uD558\uAC8C \uBCC0\uD615\uD569\uB2C8\uB2E4. \uC6D0\uBCF8 \uC2DC\uB098\uB9AC\uC624 \uC120\uD0DD \uD544\uC694.", 7360)] }),
            new TableRow({ children: [bodyCell("\uD655\uC7A5 (Expand)", 2000), bodyCell("\uAC19\uC740 \uCE74\uD14C\uACE0\uB9AC\uC5D0\uC11C \uC0C8\uB85C\uC6B4 \uAC01\uB3C4\uB85C \uD655\uC7A5\uD569\uB2C8\uB2E4. \uC6D0\uBCF8 \uC2DC\uB098\uB9AC\uC624 \uC120\uD0DD \uD544\uC694.", 7360)] }),
            new TableRow({ children: [bodyCell("\uC2E0\uADDC (New)", 2000), bodyCell("\uCC98\uC74C\uBD80\uD130 \uC0C8\uB85C\uC6B4 \uC2DC\uB098\uB9AC\uC624\uB97C \uC0DD\uC131\uD569\uB2C8\uB2E4. \uCE74\uD14C\uACE0\uB9AC\uB9CC \uC120\uD0DD.", 7360)] }),
          ]
        }),

        heading2("6.2 \uC0DD\uC131 \uC808\uCC28"),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC \uD398\uC774\uC9C0\uC5D0\uC11C AI \uC790\uB3D9 \uC0DD\uC131(\uD83E\uDD16) \uD0ED\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0DD\uC131 \uBAA8\uB4DC\uB97C \uC120\uD0DD\uD569\uB2C8\uB2E4 (\uBCC0\uD615/\uD655\uC7A5/\uC2E0\uADDC)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0DD\uC131 \uAC1C\uC218\uB97C \uC124\uC815\uD569\uB2C8\uB2E4 (\uCD5C\uB300 10\uAC1C)", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uBCC0\uD615/\uD655\uC7A5 \uBAA8\uB4DC\uC77C \uACBD\uC6B0, \uC6D0\uBCF8 \uC2DC\uB098\uB9AC\uC624\uB97C \uCCB4\uD06C\uBC15\uC2A4\uB85C \uC120\uD0DD\uD569\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC2DC\uB098\uB9AC\uC624 \uC0DD\uC131(\uD83E\uDD16) \uBC84\uD2BC\uC744 \uD074\uB9AD\uD569\uB2C8\uB2E4", font: "Arial", size: 20, bold: true })] }),
        new Paragraph({ numbering: { reference: "numbers6", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC0DD\uC131\uB41C \uC2DC\uB098\uB9AC\uC624\uAC00 \uBAA9\uB85D\uC5D0 \uCD94\uAC00\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),

        tipBox("\uC0DD\uC131\uB41C \uC2DC\uB098\uB9AC\uC624\uB294 \uBC18\uB4DC\uC2DC \uAC80\uD1A0 \uD6C4 \uD544\uC694 \uC2DC \uC218\uC815\uD574 \uC8FC\uC138\uC694. \uD655\uC778 \uC5C6\uC774 \uBC14\uB85C \uBC30\uCE58 \uD14C\uC2A4\uD2B8\uC5D0 \uC0AC\uC6A9\uD558\uBA74 \uBD80\uC815\uD655\uD55C \uACB0\uACFC\uAC00 \uB098\uC62C \uC218 \uC788\uC2B5\uB2C8\uB2E4."),

        // ===== 7. 일괄 테스트 실행 =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("7. \uC77C\uAD04 \uD14C\uC2A4\uD2B8 \uC2E4\uD589"),
        bodyText("\uB4F1\uB85D\uB41C \uC2DC\uB098\uB9AC\uC624\uB4E4\uC744 \uD55C\uAEBC\uBC88\uC5D0 \uC2E4\uD589\uD558\uC5EC \uACB0\uACFC\uB97C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText(""),

        heading2("7.1 \uC2E4\uD589 \uBC29\uBC95"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uAC1C\uBCC4 \uC2E4\uD589: \uC2DC\uB098\uB9AC\uC624 \uCE74\uB4DC\uC758 \uC2E4\uD589 \uBC84\uD2BC \uD074\uB9AD", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 60, after: 60 },
          children: [new TextRun({ text: "\uC77C\uAD04 \uC2E4\uD589: \uCCB4\uD06C\uBC15\uC2A4\uB85C \uC2DC\uB098\uB9AC\uC624 \uC120\uD0DD \u2192 \u25B6 \uC120\uD0DD \uC77C\uAD04 \uC2E4\uD589 \uBC84\uD2BC \uD074\uB9AD", font: "Arial", size: 20, bold: true })] }),

        heading2("7.2 \uC2E4\uD589 \uACB0\uACFC"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC2E4\uD589 \uC911 \uC9C4\uD589\uB960\uC774 \uC2E4\uC2DC\uAC04\uC73C\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC644\uB8CC \uC2DC \uD1B5\uACFC/\uC2E4\uD328/\uC624\uB958 \uAC74\uC218\uC640 \uD1B5\uACFC\uC728\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uAC01 \uC2DC\uB098\uB9AC\uC624 \uCE74\uB4DC\uC5D0 \u2705 PASS / \u274C FAIL \uBC30\uC9C0\uAC00 \uD45C\uC2DC\uB429\uB2C8\uB2E4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC774\uB825 \uBCF4\uAE30 \uBC84\uD2BC\uC73C\uB85C \uD14C\uC2A4\uD2B8 \uC774\uB825 \uD398\uC774\uC9C0\uC5D0\uC11C \uC0C1\uC138 \uACB0\uACFC\uB97C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4", font: "Arial", size: 20 })] }),

        // ===== 8. 테스트 결과 확인 =====
        heading1("8. \uD14C\uC2A4\uD2B8 \uACB0\uACFC \uD655\uC778"),
        ...screenshot("06_history.png", "테스트 이력 페이지"),
        bodyText("\uC0C1\uB2E8 \uBA54\uB274\uC5D0\uC11C \uD14C\uC2A4\uD2B8 \uC774\uB825\uC744 \uD074\uB9AD\uD558\uBA74 \uBAA8\uB4E0 \uBC30\uCE58 \uD14C\uC2A4\uD2B8 \uACB0\uACFC\uB97C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText(""),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uBC30\uCE58 \uC2E4\uD589 \uBAA9\uB85D: \uC2E4\uD589 \uC2DC\uAC04, \uD1B5\uACFC\uC728, \uD658\uACBD \uC815\uBCF4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uAC1C\uBCC4 \uACB0\uACFC: \uAC01 \uC2DC\uB098\uB9AC\uC624\uBCC4 \uC810\uC218, \uB4F1\uAE09, \uC704\uBC18 \uC0C1\uC138", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC7AC\uD3C9\uAC00: \uD604\uC7AC \uAC00\uC774\uB4DC\uB77C\uC778 \uBC84\uC804\uC73C\uB85C \uC7AC\uD3C9\uAC00 \uAC00\uB2A5 (\uD83D\uDD04 \uC7AC\uD3C9\uAC00 \uBC84\uD2BC)", font: "Arial", size: 20 })] }),

        // ===== 9. 평가 기준 관리 =====
        heading1("9. \uD3C9\uAC00 \uAE30\uC900 \uAD00\uB9AC"),
        bodyText("\uC0C1\uB2E8 \uBA54\uB274\uC758 \uBC95\uB960 \uD3C9\uAC00 \uAE30\uC900\uACFC \uBB38\uC9C4 \uD3C9\uAC00 \uAE30\uC900 \uD398\uC774\uC9C0\uC5D0\uC11C \uD3C9\uAC00 \uAE30\uC900\uC744 \uAD00\uB9AC\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4."),
        bodyText(""),
        heading2("9.1 \uBC95\uB960 \uD3C9\uAC00 \uAE30\uC900 (/guidelines)"),
        ...screenshot("07_guidelines.png", "법률 평가 기준 페이지"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uACE0\uC815 \uBB38\uAD6C: \uC0C1\uB2E8 \uACE0\uC9C0\uBB38, \uB9D0\uBBF8 \uBB38\uAD6C, \uBE44\uC758\uB8CC \uACE0\uC9C0, \uC751\uAE09 \uC548\uB0B4", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uAE08\uC9C0 \uD45C\uD604: \uBCD1\uBA85 \uB2E8\uC815, \uCC98\uBC29 \uC9C0\uC2DC, \uAC80\uC0AC/\uC2DC\uC220 \uC9C0\uC2DC, \uC751\uAE09 \uBD80\uC815", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD5C8\uC6A9 \uD45C\uD604: \uC548\uC804\uD55C \uD45C\uD604 \uD328\uD134", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD68C\uC0C9\uC9C0\uB300: \uC704\uD5D8 \u2192 \uC548\uC804 \uD45C\uD604 \uBCC0\uD658 \uB9E4\uD551", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC751\uAE09 \uD0A4\uC6CC\uB4DC: 119/\uC751\uAE09 \uC548\uB0B4 \uD2B8\uB9AC\uAC70 \uD0A4\uC6CC\uB4DC", font: "Arial", size: 20 })] }),

        heading2("9.2 \uBB38\uC9C4 \uD3C9\uAC00 \uAE30\uC900 (/criteria)"),
        ...screenshot("08_criteria.png", "문진 평가 기준 페이지"),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uD3C9\uAC00 \uCD95(Axis): \uBB38\uC9C4 \uD488\uC9C8 \uD3C9\uAC00 \uD56D\uBAA9\uBCC4 \uC810\uC218 \uBC0F \uBC30\uC810 \uAD00\uB9AC", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uB4F1\uAE09 \uC784\uACC4\uAC12: A/B/C/D \uB4F1\uAE09 \uAE30\uC900 \uC810\uC218 \uC124\uC815", font: "Arial", size: 20 })] }),
        new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { before: 40, after: 40 },
          children: [new TextRun({ text: "\uC758\uB8CC\uBC95 \uACBD\uACC4 \uADDC\uCE59: \uC758\uB8CC \uD589\uC704 \uACBD\uACC4\uC5D0 \uB300\uD55C \uADDC\uCE59 \uAD00\uB9AC", font: "Arial", size: 20 })] }),

        // ===== 부록 A =====
        new Paragraph({ children: [new PageBreak()] }),
        heading1("\uBD80\uB85D A. \uD654\uBA74 \uAD6C\uC131 \uC694\uC18C \uC694\uC57D"),
        bodyText(""),
        heading2("\uCC44\uD305 \uD14C\uC2A4\uD130 \uD398\uC774\uC9C0 \uC8FC\uC694 \uBC84\uD2BC"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [3000, 6360],
          rows: [
            new TableRow({ children: [headerCell("\uBC84\uD2BC / \uC694\uC18C", 3000), headerCell("\uAE30\uB2A5", 6360)] }),
            new TableRow({ children: [bodyCell("\uD83D\uDCDD \uC0C8 \uB300\uD654", 3000), bodyCell("\uC0C8\uB85C\uC6B4 \uB300\uD654 \uC2DC\uC791", 6360)] }),
            new TableRow({ children: [bodyCell("\uD83D\uDCBE \uB0B4\uBCF4\uB0B4\uAE30", 3000), bodyCell("\uB300\uD654 \uB0B4\uC6A9 \uB0B4\uBCF4\uB0B4\uAE30", 6360)] }),
            new TableRow({ children: [bodyCell("\uD83D\uDCCB \uC2DC\uB098\uB9AC\uC624 \uCD94\uCD9C", 3000), bodyCell("\uD604\uC7AC \uB300\uD654\uB97C \uD14C\uC2A4\uD2B8 \uC2DC\uB098\uB9AC\uC624\uB85C \uBCC0\uD658", 6360)] }),
            new TableRow({ children: [bodyCell("\u2630 \uB300\uD654 \uBAA9\uB85D", 3000), bodyCell("\uC88C\uCE21 \uC0AC\uC774\uB4DC\uBC14 \uD1A0\uAE00 (\uC774\uC804 \uB300\uD654 \uBAA9\uB85D)", 6360)] }),
            new TableRow({ children: [bodyCell("\uC804\uC1A1 \uBC84\uD2BC / Enter", 3000), bodyCell("\uBA54\uC2DC\uC9C0 \uC804\uC1A1", 6360)] }),
            new TableRow({ children: [bodyCell("DEV / STG / PROD", 3000), bodyCell("\uD14C\uC2A4\uD2B8 \uD658\uACBD \uC804\uD658", 6360)] }),
          ]
        }),
        bodyText(""),
        heading2("\uC2DC\uB098\uB9AC\uC624 \uAD00\uB9AC \uD398\uC774\uC9C0 \uC8FC\uC694 \uBC84\uD2BC"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [3000, 6360],
          rows: [
            new TableRow({ children: [headerCell("\uBC84\uD2BC / \uC694\uC18C", 3000), headerCell("\uAE30\uB2A5", 6360)] }),
            new TableRow({ children: [bodyCell("+ \uC0C8 \uC2DC\uB098\uB9AC\uC624", 3000), bodyCell("\uC218\uB3D9 \uC2DC\uB098\uB9AC\uC624 \uC0DD\uC131 \uBAA8\uB2EC \uC5F4\uAE30", 6360)] }),
            new TableRow({ children: [bodyCell("\uB0B4\uBCF4\uB0B4\uAE30 / \uAC00\uC838\uC624\uAE30", 3000), bodyCell("JSON \uD615\uC2DD\uC73C\uB85C \uC2DC\uB098\uB9AC\uC624 \uC77C\uAD04 \uB0B4\uBCF4\uB0B4\uAE30/\uAC00\uC838\uC624\uAE30", 6360)] }),
            new TableRow({ children: [bodyCell("\u25B6 \uC120\uD0DD \uC77C\uAD04 \uC2E4\uD589", 3000), bodyCell("\uCCB4\uD06C\uBC15\uC2A4\uB85C \uC120\uD0DD\uD55C \uC2DC\uB098\uB9AC\uC624 \uBC30\uCE58 \uD14C\uC2A4\uD2B8", 6360)] }),
            new TableRow({ children: [bodyCell("\uC218\uC815 / \uC2E4\uD589 / \uBCF5\uC81C / \uC0AD\uC81C", 3000), bodyCell("\uAC1C\uBCC4 \uC2DC\uB098\uB9AC\uC624 \uCE74\uB4DC \uC561\uC158 \uBC84\uD2BC (hover \uC2DC \uD45C\uC2DC)", 6360)] }),
            new TableRow({ children: [bodyCell("\uD83E\uDD16 \uC2DC\uB098\uB9AC\uC624 \uC0DD\uC131", 3000), bodyCell("AI \uC790\uB3D9 \uC0DD\uC131 \uD0ED\uC5D0\uC11C GPT \uAE30\uBC18 \uC2DC\uB098\uB9AC\uC624 \uC0DD\uC131", 6360)] }),
          ]
        }),
        bodyText(""),
        bodyText(""),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 400 },
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "E2E8F0", space: 12 } },
          children: [new TextRun({ text: "\u2014 \uBB38\uC11C \uB05D \u2014", font: "Arial", size: 20, color: "94A3B8", italics: true })]
        }),
      ]
    }
  ]
});

Packer.toBuffer(doc).then(buffer => {
  const outName = "/자문단_시나리오_등록_가이드.docx";
  fs.writeFileSync(__dirname + outName, buffer);
  console.log("Document created successfully!");
});
