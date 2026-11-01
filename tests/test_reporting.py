from __future__ import annotations

import json

from openpyxl import load_workbook

from evalrx.analysis import analyze_run
from evalrx.calibration import export_calibration, import_calibration, select_calibration_offline
from evalrx.compare import compare_run
from evalrx.jsonl import read_jsonl
from evalrx.normalize import prepare_dataset
from evalrx.reporting import build_report
from evalrx.workbook import build_review_workbook


def test_portable_report_and_review_round_trip(dataset_config):
    config = dataset_config
    calls = prepare_dataset(config)
    select_calibration_offline(config, "test", calls)
    csv_path, _ = export_calibration(config, "test", calls)
    analyze_run(config, "test", calls)
    compare_run(config, "test")
    report, schemas = build_report(config, "test")
    text = report.read_text()
    assert "# EvalRX Call Evaluation" in text
    assert "2 transcript calls and 2 audio recordings" in text
    assert len(json.loads(schemas.read_text())) == 4
    # Reviewer text must survive export without becoming a spreadsheet formula.
    csv_path.write_text(csv_path.read_text().replace("pending", "=1+1", 1))
    output = build_review_workbook(config, "test")
    workbook = load_workbook(output)
    assert workbook.sheetnames == [
        "README",
        "Rubric",
        "Calibration",
        "All Calls",
        "Audio Review",
        "Failure Patterns",
        "Run Metadata",
    ]
    calibration = workbook["Calibration"]
    assert calibration.max_row == 1 + 21 * len(calls)
    assert calibration["N2"].value == "=1+1"
    assert calibration["N2"].data_type == "s"
    calibration["N2"] = "pending"
    calibration["K3"] = 2
    calibration["M3"] = "Reviewed synthetic evidence."
    calibration["N3"] = "in_progress"
    calibration["O3"] = "Test reviewer"
    assert str(calibration.data_validations.dataValidation[0].sqref) == "K2:K85"
    assert workbook["All Calls"].max_row == 5
    assert workbook["Audio Review"].max_row == 3
    assert workbook["Rubric"].max_row == 19
    assert not any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
    workbook.save(output)
    workbook.close()
    labels = read_jsonl(import_calibration(config, "test", output))
    reviewed = next(label for label in labels if label["reviewer"] == "Test reviewer")
    assert reviewed["review_status"] == "in_progress"
    assert reviewed["agent_performance_scores"]["identity_and_authorization"] == 2
