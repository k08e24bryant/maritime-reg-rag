"""Phase 4 Step 5: figures render without CSS, the headline is traceable to eval.json, all sections exist."""

from __future__ import annotations

import xml.dom.minidom

import pytest

from maritime_rag.config import load_config, resolve
from maritime_rag.eval.figures import llm_chart, retriever_chart
from maritime_rag.eval.report import build, figures, get_path, render

ECFG = load_config("configs/eval.yaml")
LLMS = ECFG["answers"]["llms"]
INPUTS = [resolve(ECFG["report"][k]) for k in ("retrieval_json", "answers_json", "judge_json")] + [
    resolve(ECFG["paths"]["chunks_file"]), resolve(ECFG["answers"]["contexts"])]


def test_figures_are_valid_svg_with_light_attributes_and_dark_override() -> None:
    rows = [{"name": "a", "label": "A", "n": 44, "hit@5": {"mean": 0.8, "ci95": [0.7, 0.9]},
             "mrr@10": {"mean": 0.6, "ci95": [0.5, 0.7]}}]
    groups = [{"criterion": "Correctness", "labels": ["correct", "partial", "wrong"],
               "rows": [{"name": "m", "counts": {"correct": 40, "partial": 2, "wrong": 2}, "note": "judged by x"}]}]
    for svg in (retriever_chart(rows, "a"), llm_chart(groups)):
        xml.dom.minidom.parseString(svg.encode())
        assert "@media (prefers-color-scheme: dark)" in svg and 'fill="transparent"' not in svg
        assert '<title>' in svg and 'font-family="' in svg
    assert 'fill="#184f95"' in llm_chart(groups) and "40 / 2 / 2 of 44" in llm_chart(groups)
    assert 'class="series" fill="#2a78d6"' in retriever_chart(rows, "a")


@pytest.mark.skipif(not all(p.exists() for p in INPUTS), reason="needs the Step 2-4 results and chunks.jsonl")
def test_report_from_the_committed_results() -> None:
    r = build("configs/eval.yaml")
    assert len(r["headline"]) == 5
    for h in r["headline"]:
        for path, value in h["values"].items():
            assert get_path(r, path) == value  # every headline number is stored under its eval.json path
    assert r["retrieval"]["selected"]["name"] == "hybrid_rerank" and r["gate"]["enabled_in_evaluation"] is False
    assert r["agreement"]["criteria"]["superseded_mentioned"]["flagged"]
    assert not r["agreement"]["criteria"]["correctness"]["flagged"]
    md = render(r, LLMS)
    for section in ("## Headline results", "## 1. Retrieval", "## 2. Score gate", "## 3. Answers", "## 4. LLM comparison",
                    "## 5. Per slice", "## 6. Cost and latency", "## 7. Post-hoc changes", "## 8. Findings",
                    "## 9. Limitations", "## 10. Future work"):
        assert section in md, section
    assert "superseded_mentioned ⚠" in md and "**F07**" in md and "**F24**" in md
    assert set(figures(r, LLMS)) == {"retrievers.svg", "llm_comparison.svg"}
