"""Gradio UI of the demo: ask, see the cited answer, the sources with their version status, and open
any source's full text. A second tab shows the Phase 4 evaluation headline and figures."""

from __future__ import annotations

from html import escape
from typing import Any

import gradio as gr

from maritime_rag.answer.providers import ProviderError
from maritime_rag.config import resolve
from maritime_rag.demo.service import DemoService, InvalidQuestion, eval_headline

SOURCE_HEADERS = ["#", "source", "status", "cited", "how it got here"]
REASONS = {
    "no_hits": "no matching passage was retrieved",
    "gate": "retrieval score below the gate",
    "model_not_found": "the model found no answer in the retrieved passages",
    "no_valid_citation": "the answer had no citation that matches a retrieved passage",
    "truncated": "the model's answer was cut off by its output limit",
}


def format_answer(res: dict[str, Any]) -> tuple[str, str, list[list[Any]], str, list[tuple[str, str]]]:
    """(answer markdown, warnings markdown, sources table, stats line, source choices)."""
    if res["refused"]:
        answer = f"**{escape(res['answer'])}**\n\n_Refused: {REASONS.get(res['refusal_reason'], res['refusal_reason'])}._"
    else:
        answer = res["answer"] + (f"\n\n_{res['disclaimer']}_" if res["disclaimer"] else "")
    warnings = "\n".join(f"- ⚠ {escape(w)}" for w in res["warnings"]) if res["warnings"] else ""
    table = [[s["n"], f"{s['where']} ({s['file_pages']})", s["status"], "yes" if s["cited"] else "", s["origin"]]
             for s in res["sources"]]
    lat = res["latency_s"]
    parts = [f"LLM `{res['llm']['model']}`" + ("" if res["llm"]["called"] else " (not called)"),
             f"retrieval {lat.get('retrieve_s', 0):.2f} s", ]
    if "rerank_s" in lat:
        parts.append(f"rerank {lat['rerank_s']:.2f} s")
    if "generate_s" in lat:
        parts.append(f"generate {lat['generate_s']:.1f} s")
    if res["tokens"]:
        parts.append(f"{res['tokens']['prompt']} + {res['tokens']['output']} tokens")
    if res["cost_usd"] is not None:
        parts.append(f"~${res['cost_usd']:.5f}")
    c = res["citations"]
    parts.append(f"citations {c['valid']} valid / {c['invalid']} invalid")
    choices = [(f"{s['n']}. {s['where']}", s["chunk_id"]) for s in res["sources"]]
    return answer, warnings, table, " · ".join(parts), choices


def build_ui(service: DemoService, eval_report: str | None = None, figures: list[str] | None = None) -> gr.Blocks:
    with gr.Blocks(title="Maritime regulation RAG") as demo:
        gr.Markdown(
            "# Maritime regulation RAG\n"
            "Questions about Indonesian maritime and logistics regulations (UU, PP, Permenhub) and the UNCTAD "
            "*Review of Maritime Transport 2025*, answered **only** from those documents, with a citation "
            "(document, Pasal/ayat, page) for every claim. Amended or repealed provisions are labelled. "
            "**Not legal advice.**")
        with gr.Tab("Ask"):
            with gr.Row():
                question = gr.Textbox(label="Question (Indonesian or English)", lines=2, scale=4,
                                      max_length=service.cfg.max_question_chars)
                with gr.Column(scale=1, min_width=200):
                    llm = gr.Dropdown(service.cfg.llms, value=service.cfg.default_llm, label="LLM")
                    rerank = gr.Checkbox(value=service.cfg.rerank_default, label="bge reranker")
                    ask = gr.Button("Ask", variant="primary")
            gr.Examples(examples=[[e] for e in service.cfg.examples], inputs=[question], label="Examples")
            answer = gr.Markdown(label="Answer")
            warnings = gr.Markdown()
            stats = gr.Markdown()
            sources = gr.Dataframe(headers=SOURCE_HEADERS, label="Sources given to the model", interactive=False,
                                   wrap=True)
            with gr.Accordion("Open a source", open=False):
                pick = gr.Dropdown(choices=[], label="Source")
                source_text = gr.Markdown()

            def on_ask(q: str, model: str, use_rerank: bool):
                try:
                    a, w, t, s, choices = format_answer(service.ask(q, model, use_rerank))
                except InvalidQuestion as e:
                    return f"**{escape(str(e))}**", "", [], "", gr.Dropdown(choices=[], value=None), ""
                except ProviderError as e:
                    return (f"**The LLM could not be reached:** {escape(str(e))}", "", [], "",
                            gr.Dropdown(choices=[], value=None), "")
                return a, w, t, s, gr.Dropdown(choices=choices, value=None), ""

            def on_pick(chunk_id: str | None) -> str:
                if not chunk_id:
                    return ""
                src = service.source(chunk_id)
                return f"**{escape(src['where'])}** ({escape(src['file'])}, {src['pages']})\n\n{escape(src['text'])}"

            outputs = [answer, warnings, sources, stats, pick, source_text]
            ask.click(on_ask, [question, llm, rerank], outputs)
            question.submit(on_ask, [question, llm, rerank], outputs)
            pick.change(on_pick, [pick], [source_text])
        with gr.Tab("Evaluation"):
            lines = eval_headline(eval_report) if eval_report else []
            gr.Markdown("## Phase 4 evaluation (54 questions)\n\n"
                        + ("\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) if lines else "_No report yet._")
                        + "\n\nFull report: `reports/eval.md`.")
            for f in figures or []:
                p = resolve(f)
                if p.exists():
                    gr.HTML(p.read_text(encoding="utf-8"))
    return demo
