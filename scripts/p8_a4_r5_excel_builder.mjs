import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, "..");
const reportsDir = path.join(root, "reports");
const outputPath = path.join(reportsDir, "p8_a4_human_review_template.xlsx");
const previewDir = path.join(reportsDir, "p8_a4_r5_preview");

const guideRows = [
  ["research_usefulness", 1, "基本无用"],
  ["research_usefulness", 2, "信息有限，帮助较小"],
  ["research_usefulness", 3, "有一定研究帮助"],
  ["research_usefulness", 4, "明显帮助推进研究"],
  ["research_usefulness", 5, "显著减少研究工作量"],
  ["exploration_quality", 1, "无探索价值"],
  ["exploration_quality", 2, "重复常识"],
  ["exploration_quality", 3, "提供部分研究方向"],
  ["exploration_quality", 4, "发现较好的研究角度"],
  ["exploration_quality", 5, "产生重要研究线索"],
  ["actionability", 1, "无明确下一步"],
  ["actionability", 2, "建议模糊"],
  ["actionability", 3, "提供方向"],
  ["actionability", 4, "提供明确行动步骤"],
  ["actionability", 5, "可直接指导后续研究"],
  ["noise_rate", 0, "几乎无噪音"],
  ["noise_rate", 0.25, "少量无关内容"],
  ["noise_rate", 0.5, "约半数内容价值有限"],
  ["noise_rate", 0.75, "大量无关内容"],
  ["noise_rate", 1, "几乎全部无效"],
];

async function latestRun() {
  const entries = await fs.readdir(path.join(reportsDir, "harness_evaluation_runs"), {
    withFileTypes: true,
  });
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const runRoot = path.join(reportsDir, "harness_evaluation_runs", entry.name);
    const manifestPath = path.join(runRoot, "manifest.json");
    try {
      const stat = await fs.stat(manifestPath);
      candidates.push({ runRoot, manifestPath, mtime: stat.mtimeMs });
    } catch {
      // Ignore incomplete directories without a manifest.
    }
  }
  if (!candidates.length) throw new Error("No retained Harness evaluation run found");
  candidates.sort((a, b) => b.mtime - a.mtime);
  const selected = candidates[0];
  return {
    runRoot: selected.runRoot,
    manifest: JSON.parse(await fs.readFile(selected.manifestPath, "utf8")),
  };
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

function styleTitle(range) {
  range.format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
}

function styleHeader(range) {
  range.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#B4C7E7" },
  };
}

function styleBody(range) {
  range.format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#D9E2F3" },
  };
}

async function build() {
  const { runRoot, manifest } = await latestRun();
  if (manifest.case_count !== 20 || manifest.completeness?.raw_output_exists !== true) {
    throw new Error("Latest retained run is not a complete 20-case raw-output run");
  }
  const caseRows = [];
  for (const manifestCase of manifest.cases) {
    const caseRoot = path.join(runRoot, "case_" + manifestCase.case_id);
    const input = await readJson(path.join(caseRoot, "input.json"));
    const prompt = await fs.readFile(path.join(caseRoot, "prompt.txt"), "utf8");
    const output = await fs.readFile(path.join(caseRoot, "harness_output.txt"), "utf8");
    if (!prompt.trim() || !output.trim()) {
      throw new Error("Missing readable evidence for " + manifestCase.case_id);
    }
    caseRows.push([
      input.case_id,
      input.task_type,
      input.category + " / " + input.task_type,
      prompt,
      output,
      null, null, null, null,
      "", "", "",
    ]);
  }

  const workbook = Workbook.create();
  const review = workbook.worksheets.add("Human Review");
  const guide = workbook.worksheets.add("Scoring Guide");
  review.showGridLines = false;
  guide.showGridLines = false;

  review.mergeCells("A1:L1");
  review.getRange("A1").values = [["P8-A4 Human Review — Harness Exploration Assistant"]];
  styleTitle(review.getRange("A1:L1"));
  review.getRange("A1:L1").format.rowHeight = 28;
  review.mergeCells("A2:L2");
  review.getRange("A2").values = [[
    "Evidence source: " + manifest.run_id + ". Complete 20-case retained run. " +
    "Fill only the yellow reviewer cells. Do not score automatically; Excel is not raw evidence storage.",
  ]];
  review.getRange("A2:L2").format = {
    fill: "#EAF2F8",
    font: { italic: true, color: "#404040" },
    wrapText: true,
    verticalAlignment: "center",
  };
  review.getRange("A2:L2").format.rowHeight = 32;

  const headers = [
    "case_id", "task_type", "scenario", "prompt", "harness_output",
    "research_usefulness", "exploration_quality", "actionability", "noise_rate",
    "reviewer_id", "review_time", "review_notes",
  ];
  review.getRange("A4:L4").values = [headers];
  styleHeader(review.getRange("A4:L4"));
  review.getRange("A5:L24").values = caseRows;
  styleBody(review.getRange("A5:L24"));
  review.getRange("F5:L24").format = {
    fill: "#FFF2CC",
    font: { color: "#0000FF" },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#D9E2F3" },
  };
  review.getRange("F5:H24").format.numberFormat = "0";
  review.getRange("I5:I24").format.numberFormat = "0.00";
  review.getRange("A5:C24").format.font = { color: "#404040" };
  review.getRange("A5:C24").format.horizontalAlignment = "left";
  review.getRange("F5:I24").format.horizontalAlignment = "center";
  review.getRange("K5:K24").format.numberFormat = "@";
  review.getRange("D5:E24").format.rowHeight = 120;
  review.getRange("F5:L24").format.rowHeight = 42;
  review.getRange("A:A").format.columnWidth = 28;
  review.getRange("B:B").format.columnWidth = 22;
  review.getRange("C:C").format.columnWidth = 28;
  review.getRange("D:D").format.columnWidth = 62;
  review.getRange("E:E").format.columnWidth = 76;
  review.getRange("F:I").format.columnWidth = 18;
  review.getRange("J:J").format.columnWidth = 20;
  review.getRange("K:K").format.columnWidth = 22;
  review.getRange("L:L").format.columnWidth = 38;
  review.freezePanes.freezeRows(4);
  review.freezePanes.freezeColumns(2);
  review.tables.add("A4:L24", true, "HumanReviewTable");
  review.dataValidations.add({
    range: "F5:H24",
    rule: { type: "whole", operator: "between", formula1: 1, formula2: 5 },
  });
  review.dataValidations.add({
    range: "I5:I24",
    rule: { type: "decimal", operator: "between", formula1: 0, formula2: 1 },
  });

  guide.mergeCells("A1:C1");
  guide.getRange("A1").values = [["P8-A4 Human Review Scoring Guide"]];
  styleTitle(guide.getRange("A1:C1"));
  guide.mergeCells("A2:C2");
  guide.getRange("A2").values = [[
    "Reviewer-owned scores only. Do not infer or auto-fill scores. noise_rate is a decimal from 0 to 1.",
  ]];
  guide.getRange("A2:C2").format = {
    fill: "#EAF2F8", wrapText: true, font: { italic: true, color: "#404040" },
  };
  guide.getRange("A4:C4").values = [["metric", "score", "definition"]];
  styleHeader(guide.getRange("A4:C4"));
  guide.getRange("A5:C24").values = guideRows;
  styleBody(guide.getRange("A5:C24"));
  guide.getRange("B5:B24").format.horizontalAlignment = "center";
  guide.getRange("A:A").format.columnWidth = 26;
  guide.getRange("B:B").format.columnWidth = 12;
  guide.getRange("C:C").format.columnWidth = 46;
  guide.getRange("A5:A24").format.font = { bold: true, color: "#404040" };
  guide.getRange("A5:C24").format.rowHeight = 26;
  guide.freezePanes.freezeRows(4);
  guide.tables.add("A4:C24", true, "ScoringGuideTable");

  await fs.mkdir(previewDir, { recursive: true });
  const reviewPreview = await workbook.render({
    sheetName: "Human Review", range: "A1:L12", scale: 1, format: "png",
  });
  await fs.writeFile(path.join(previewDir, "human_review.png"),
    new Uint8Array(await reviewPreview.arrayBuffer()));
  const guidePreview = await workbook.render({
    sheetName: "Scoring Guide", range: "A1:C24", scale: 1, format: "png",
  });
  await fs.writeFile(path.join(previewDir, "scoring_guide.png"),
    new Uint8Array(await guidePreview.arrayBuffer()));

  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  console.log(JSON.stringify({
    outputPath,
    sourceRunId: manifest.run_id,
    caseCount: caseRows.length,
    sheets: ["Human Review", "Scoring Guide"],
  }, null, 2));
}

await build();
