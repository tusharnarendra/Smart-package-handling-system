"""Language-separated sensor data exports and a formatted Excel companion."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

from sensor_data import EHEAD, NUMERIC_COLUMNS

def encode_csv(headers, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")

def create_readable_workbook(path, khead, korean_rows, english_data, preview=False):
    config_path = Path(__file__).with_name("excel_runtime.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # Shared copy: resolve the builder relative to this file, not the working directory.
    builder = Path(config["builder"])
    if not builder.is_absolute():
        builder = config_path.parent / builder
    # Transfer structured, already parsed values. Do not let Excel infer times,
    # formula strings, or round milliseconds when opening CSV.
    def typed(rows):
        result = []
        for source in rows:
            row = list(source)
            row[0] = float(row[0])
            for i in NUMERIC_COLUMNS:
                if row[i] is not None: row[i] = int(row[i])
            result.append(row)
        return result
    request = {"output": str(path), "sheets": [
        {"name": "한국어", "headers": khead, "rows": typed(korean_rows)},
        {"name": "English", "headers": EHEAD, "rows": typed(english_data)}],
        "preview": preview}
    with tempfile.TemporaryDirectory(prefix="sensor_excel_") as tmp:
        request_path = Path(tmp) / "request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([config["node"], str(builder), str(request_path)],
                                capture_output=True, text=True, encoding="utf-8", timeout=180,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:] or result.stdout[-1500:])
    if not Path(path).is_file(): raise RuntimeError("Excel file was not created.")
    return str(path)
