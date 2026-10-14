"""Static SVG figures for reports/eval.md (no plotting dependency).

Both figures carry their own light/dark styles (prefers-color-scheme), a <title> per mark as the
hover tooltip, and direct labels, so no value is shown by colour alone. Colours follow the
dataviz reference palette: one series hue for the retriever chart; a validated ordinal blue ramp
(light #184f95/#3987e5/#86b6ef, dark #cde2fb/#6da7ec/#256abf) for ordered judge labels.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

# Light colours are written as presentation attributes on every element, so renderers without CSS
# (PDF tools, document converters) still draw the chart; the <style> only overrides them for dark mode.
LIGHT = {
    "surface": {"fill": "#fcfcfb"}, "ink": {"fill": "#0b0b0b"}, "ink2": {"fill": "#52514e"}, "ink3": {"fill": "#8a8984"},
    "grid": {"stroke": "#e4e3df", "stroke-width": "1"}, "axis": {"stroke": "#b9b8b2", "stroke-width": "1"},
    "series": {"fill": "#2a78d6", "stroke": "#fcfcfb", "stroke-width": "2"}, "ci": {"stroke": "#2a78d6", "stroke-width": "2"},
    "o1": {"fill": "#184f95"}, "o2": {"fill": "#3987e5"}, "o3": {"fill": "#86b6ef"},
    "on1": {"fill": "#ffffff"}, "on2": {"fill": "#ffffff"}, "on3": {"fill": "#0b0b0b"}, "sel": {"fill": "#f0efec"},
}
FONT = "system-ui, -apple-system, Segoe UI, sans-serif"
STYLE = """
<style>
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; } .ink { fill: #f0efec; } .ink2 { fill: #c3c2b7; } .ink3 { fill: #8f8e86; }
    .grid { stroke: #2f2f2d; } .axis { stroke: #55544f; }
    .series { fill: #3987e5; stroke: #1a1a19; } .ci { stroke: #3987e5; }
    .o1 { fill: #cde2fb; } .o2 { fill: #6da7ec; } .o3 { fill: #256abf; }
    .on1 { fill: #0b0b0b; } .on2 { fill: #0b0b0b; } .on3 { fill: #ffffff; }
    .sel { fill: #262624; }
  }
</style>"""


def _with_light(markup: str) -> str:
    """Add the light-mode presentation attributes for each class="..." (and the font on <text>)."""
    def add(m: re.Match) -> str:
        cls = m[1]
        return f'class="{cls}"' + "".join(f' {k}="{v}"' for k, v in LIGHT.get(cls, {}).items())
    markup = re.sub(r'class="([\w-]+)"', add, markup)
    return markup.replace("<text ", f'<text font-family="{FONT}" ')


def _svg(width: int, height: int, title: str, desc: str, body: list[str]) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">',
        f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>',
        STYLE,
        _with_light(f'<rect class="surface" x="0" y="0" width="{width}" height="{height}" rx="8"/>'),
        *(_with_light(b) for b in body),
        "</svg>",
    ]) + "\n"


def retriever_chart(rows: list[dict[str, Any]], selected: str) -> str:
    """Dot + 95% CI per configuration, two panels (Hit@5, MRR@10) on a shared 0-1 scale.

    rows: [{"name", "label", "hit@5": {"mean", "ci95": [lo, hi]}, "mrr@10": {...}}] in display order."""
    left, top, row_h, panel_w, gap = 250, 74, 40, 250, 40
    width = left + 2 * panel_w + gap + 30
    height = top + row_h * len(rows) + 46
    body = [
        f'<text class="ink" x="20" y="28" font-size="16" font-weight="600">Retrieval on {rows[0]["n"]} in-scope '
        'questions (mean, 95% bootstrap CI)</text>',
        '<text class="ink2" x="20" y="48" font-size="12">Overlapping intervals: not distinguishable at this n. '
        'Highlighted row: selected by the pre-registered rule.</text>',
    ]
    for i, r in enumerate(rows):
        y = top + i * row_h + row_h / 2
        if r["name"] == selected:
            body.append(f'<rect class="sel" x="12" y="{y - row_h / 2 + 2}" width="{width - 24}" height="{row_h - 4}" rx="4"/>')
        weight = "600" if r["name"] == selected else "400"
        label = r["label"] + ("  (selected)" if r["name"] == selected else "")
        body.append(f'<text class="ink" x="20" y="{y + 4}" font-size="12" font-weight="{weight}">{escape(label)}</text>')
    for p, (metric, title) in enumerate((("hit@5", "Hit@5"), ("mrr@10", "MRR@10"))):
        x0 = left + p * (panel_w + gap)
        body.append(f'<text class="ink2" x="{x0}" y="{top - 8}" font-size="12" font-weight="600">{title}</text>')
        for t in (0, 0.25, 0.5, 0.75, 1.0):
            x = x0 + t * panel_w
            body.append(f'<line class="grid" x1="{x}" y1="{top}" x2="{x}" y2="{top + row_h * len(rows)}"/>')
            body.append(f'<text class="ink3" x="{x}" y="{top + row_h * len(rows) + 16}" font-size="11" '
                        f'text-anchor="middle">{t:g}</text>')
        for i, r in enumerate(rows):
            y = top + i * row_h + row_h / 2
            m = r[metric]
            lo, hi = m["ci95"]
            xs = [x0 + v * panel_w for v in (lo, m["mean"], hi)]
            tip = f'{r["label"]}: {title} {m["mean"]:.3f} (95% CI {lo:.2f}-{hi:.2f})'
            body += [
                f'<g><title>{escape(tip)}</title>',
                f'<line class="ci" x1="{xs[0]:.1f}" y1="{y}" x2="{xs[2]:.1f}" y2="{y}" stroke-linecap="round"/>',
                f'<rect x="{xs[0] - 4:.1f}" y="{y - 12}" width="{xs[2] - xs[0] + 8:.1f}" height="24" fill="#000000" fill-opacity="0"/>',
                f'<circle class="series" cx="{xs[1]:.1f}" cy="{y}" r="5"/>',
                "</g>",
                f'<text class="ink2" x="{min(xs[2] + 8, x0 + panel_w + 4):.1f}" y="{y + 4}" font-size="11">{m["mean"]:.2f}</text>',
            ]
    return _svg(width, height, "Retriever comparison", "Hit@5 and MRR@10 with 95% CIs per retrieval configuration.", body)


def llm_chart(groups: list[dict[str, Any]]) -> str:
    """100% stacked bars of ordered judge labels, one row per LLM, one group per criterion.

    groups: [{"criterion", "labels": [best, mid, worst], "rows": [{"name", "counts": {label: n}, "note"}]}]"""
    left, top, bar_h, row_gap, group_gap, bar_w = 210, 92, 26, 12, 34, 470
    rows_total = sum(len(g["rows"]) for g in groups)
    height = top + rows_total * (bar_h + row_gap) + len(groups) * group_gap + 30
    width = left + bar_w + 130
    body = [
        '<text class="ink" x="20" y="28" font-size="16" font-weight="600">LLM comparison: cross-judged answers '
        '(each LLM graded by the other)</text>',
        '<text class="ink2" x="20" y="48" font-size="12">In-scope answers, share of each label; counts at right (best / middle / worst). '
        'Judge vs manual labels: see reports/eval.md.</text>',
    ]
    lx = 20
    for k, name in enumerate(("best (correct / supported)", "middle (partial / partly)", "worst (wrong / unsupported)"), 1):
        body += [f'<rect class="o{k}" x="{lx}" y="62" width="12" height="12" rx="2"/>',
                 f'<text class="ink2" x="{lx + 18}" y="72" font-size="11">{name}</text>']
        lx += 190
    y = top
    for g in groups:
        body.append(f'<text class="ink2" x="20" y="{y + 4}" font-size="12" font-weight="600">{escape(g["criterion"])}</text>')
        y += 14
        for r in g["rows"]:
            total = sum(r["counts"].get(lab, 0) for lab in g["labels"]) or 1
            body.append(f'<text class="ink" x="20" y="{y + bar_h / 2 + 4}" font-size="12">{escape(r["name"])}</text>')
            if r.get("note"):
                body.append(f'<text class="ink3" x="20" y="{y + bar_h / 2 + 17}" font-size="10">{escape(r["note"])}</text>')
            x = left
            for k, lab in enumerate(g["labels"], 1):
                n = r["counts"].get(lab, 0)
                w = bar_w * n / total
                if n:
                    seg = max(w - 2, 1)  # 2px surface gap between segments
                    tip = f'{r["name"]}, {g["criterion"]}: {lab} {n}/{total} ({n / total:.0%})'
                    body += [f'<g><title>{escape(tip)}</title>',
                             f'<rect class="o{k}" x="{x:.1f}" y="{y}" width="{seg:.1f}" height="{bar_h}" rx="4"/></g>']
                    if w >= 34:
                        body.append(f'<text class="on{k}" x="{x + seg / 2:.1f}" y="{y + bar_h / 2 + 4}" font-size="11" '
                                    f'text-anchor="middle">{n}</text>')
                x += w
            counts = " / ".join(str(r["counts"].get(lab, 0)) for lab in g["labels"])
            body.append(f'<text class="ink2" x="{left + bar_w + 8}" y="{y + bar_h / 2 + 4}" font-size="11">'
                        f'{counts} of {total}</text>')
            y += bar_h + row_gap
        y += group_gap - 14
    return _svg(width, int(y + 10), "LLM comparison", "Judge labels per LLM as 100% stacked bars.", body)
