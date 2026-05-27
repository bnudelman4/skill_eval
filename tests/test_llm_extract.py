"""C: LLM extraction of an untouched skill artifact -> Ledger. Offline (mock LLM)."""

import json

from openpyxl import Workbook

from finskill_eval.extract.llm_extract import (
    extract_ledger,
    parse_extractor_json,
    xlsx_to_text,
)


def _artifact(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Raw Data"
    ws.append(["Metric", "Q1 FY24\n(Dec 2023)", "FY2024 Total"])
    ws.append(["Revenue", 119575, 391035])   # displayed in $ millions
    ws.append(["Gross Profit", 54855, 180683])
    wb.save(path)


def test_xlsx_to_text_includes_values_and_sheet_names(tmp_path):
    f = tmp_path / "a.xlsx"
    _artifact(f)
    txt = xlsx_to_text(f)
    assert "Raw Data" in txt
    assert "391035" in txt and "Revenue" in txt


def test_parse_extractor_json_tolerates_code_fences():
    raw = "Here you go:\n```json\n[{\"metric\":\"revenue\",\"period\":\"FY2024\",\"value\":391035000000,\"unit\":\"USD\",\"kind\":\"direct\"}]\n```"
    recs = parse_extractor_json(raw)
    assert recs[0]["metric"] == "revenue"
    assert recs[0]["value"] == 391035000000


def test_extract_ledger_builds_absolute_cells(tmp_path):
    f = tmp_path / "a.xlsx"
    _artifact(f)

    def fake_llm(prompt: str) -> str:
        # the extractor LLM is told to emit ABSOLUTE values + canonical names
        return json.dumps([
            {"metric": "revenue", "period": "FY2024", "value": 391035000000,
             "unit": "USD", "kind": "direct"},
            {"metric": "gross_profit", "period": "FY2024", "value": 180683000000,
             "unit": "USD", "kind": "direct"},
            {"metric": "gross_margin", "period": "FY2024", "value": 46.21,
             "unit": "percent", "kind": "derived"},
        ])

    led = extract_ledger(f, skill="tearsheet", ticker="AAPL", llm=fake_llm)
    by = {c.canonical_label: c for c in led.cells}
    assert by["revenue"].value == 391035000000          # absolute, no scaling
    assert by["gross_profit"].value == 180683000000
    gm = by["gross_margin"]
    assert gm.kind == "derived" and gm.formula == "gross_margin"
    # wired to its inputs so recompute can check it
    assert len(gm.inputs) == 2


def test_extract_ledger_empty_on_no_records(tmp_path):
    f = tmp_path / "a.xlsx"
    _artifact(f)
    led = extract_ledger(f, skill="tearsheet", ticker="AAPL", llm=lambda p: "[]")
    assert led.cells == []
