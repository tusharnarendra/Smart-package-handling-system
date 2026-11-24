import fs from "node:fs/promises";
import path from "node:path";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";
const spec = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const workbook = Workbook.create();
const widths = [19, 27, 28, 38, 25, 22, 22, 24, 23, 23, 23, 22, 24, 22, 24, 28, 24, 22, 24, 72, 22, 26, 26, 18, 23];
const numericColumns = [5,6,7,12,14,16,18,20,22,23];
for (const input of spec.sheets) {
  const sheet = workbook.worksheets.add(input.name);
  const rows = [input.headers, ...input.rows];
  const area = sheet.getRangeByIndexes(0, 0, rows.length, input.headers.length);
  area.values = rows;
  area.format.font = { name: "Malgun Gothic", size: 11 };
  area.format.verticalAlignment = "center";
  area.format.rowHeight = 33;
  area.format.wrapText = true;
  area.format.borders = {insideVertical: {style: "thin", color: "#E1E7ED"}};
  sheet.showGridLines = false;
  for (let c = 0; c < widths.length; c++) {
    sheet.getRangeByIndexes(0, c, rows.length, 1).format.columnWidth = widths[c];
  }
  const header = sheet.getRangeByIndexes(0, 0, 1, input.headers.length);
  header.format.fill = "#203C59";
  header.format.font = {name: "Malgun Gothic", size: 11, bold: true, color: "#FFFFFF"};
  header.format.horizontalAlignment = "center";
  header.format.rowHeight = 76;
  header.format.borders = {preset: "inside", style: "thin", color: "#FFFFFF"};
  if (input.rows.length) {
    sheet.getRangeByIndexes(1, 1, input.rows.length, 1).format.horizontalAlignment = "center";
    sheet.getRangeByIndexes(1, 3, input.rows.length, 7).format.horizontalAlignment = "center";
    sheet.getRangeByIndexes(1, 0, input.rows.length, 1).setNumberFormat("0.000");
    sheet.getRangeByIndexes(1, 1, input.rows.length, 1).setNumberFormat("@");
    for (const c of numericColumns) {
      sheet.getRangeByIndexes(1, c, input.rows.length, 1).setNumberFormat("0");
    }
    for (let r = 1; r < rows.length; r++) {
      if (r % 2 === 0) sheet.getRangeByIndexes(r, 0, 1, input.headers.length).format.fill = "#F2F5F8";
      // Bound widths; grow only the rows with longer wrapped observations.
      const visualLength = [...String(rows[r][19])].reduce((n, ch) => n + (ch.charCodeAt(0) > 255 ? 2 : 1), 0);
      sheet.getRangeByIndexes(r, 0, 1, input.headers.length).format.rowHeight = Math.max(33, Math.ceil(visualLength / 66) * 17 + 8);
    }
  }
  const table = sheet.tables.add(`A1:Y${rows.length}`, true, input.name === "English" ? "EnglishSensorData" : "KoreanSensorData");
  table.showFilterButton = true;
  sheet.freezePanes.freezeRows(1);
}
workbook.recalculate();
const checked = await workbook.inspect({kind:"table", range:"English!A1:C4", include:"values", tableMaxRows:4, tableMaxCols:3, maxChars:1200});
console.log(checked.ndjson);
const errors = await workbook.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!",options:{useRegex:true,maxResults:5},maxChars:600});
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(spec.output);
if (spec.preview) {
  for (const [index, sheet] of spec.sheets.entries()) {
    for (const [part, range] of [["left","A1:E6"],["light","F1:K6"],["sensors","L1:S6"],["notes","T1:Y6"]]) {
      const preview = await workbook.render({sheetName:sheet.name, range, scale:1.4, format:"png"});
      await fs.writeFile(path.join(path.dirname(spec.output), "preview_"+index+"_"+part+".png"), new Uint8Array(await preview.arrayBuffer()));
    }
  }
}
