"""Chunk Indonesian regulations (UU/PP/PM) by structure: one chunk per Pasal, long Pasal by ayat.

A regulation is split into parts:
  preamble   title, Menimbang, Mengingat, Menetapkan
  body       BAB / Bagian / Paragraf / Pasal, up to "Ditetapkan/Disahkan di ..."
  lampiran   attachments after the signature block (if any)
  penjelasan elucidation: "I. UMUM" free text, then "II. PASAL DEMI PASAL"
The signature block between the body and the next part is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maritime_rag.chunk import Chunk
from maritime_rag.cleaning import Line, join_lines
from maritime_rag.manifest import DocMeta
from maritime_rag.pasal_splitter import (
    HeaderSelection,
    PasalNum,
    TokenCounter,
    select_pasal_headers,
    split_pasal,
    window_lines,
)

BAB = re.compile(r"^BAB\s+(?P<num>[IVXLC1l]+[A-Z]?)(?:\s+(?P<title>[A-Z][A-Z ,/&-]+))?$")
BAGIAN = re.compile(r"^Bagian\s+(?P<num>Ke[a-z]+(?:\s+[A-Z])?)$")
PARAGRAF = re.compile(r"^Paragraf\s+(?P<num>\d+[A-Z]?)$")
CLOSING = re.compile(r"^(Ditetapkan|Disahkan|Diundangkan)\s+di\s+\S+", re.IGNORECASE)
PENJELASAN = re.compile(r"^(P\s*E\s*N\s*J\s*E\s*\S{1,4}\s*A\s*S\s*A\s*N|I\s*\.\s*UMUM)$")
LAMPIRAN = re.compile(r"^LAMPIRAN\b")
DOC_END = re.compile(r"^TAMBAHAN LEMBARAN NEGARA")
INSTRUCTION = re.compile(
    r"^[0-9SOlILZ](?:\s?[0-9SOlILZrt]){0,2}\s?\.?\s*(Ketentuan|Di\s*antara|Diantara|Judul|Penjelasan|Lampiran|Pasal|BAB|Bab|Bagian|Paragraf|Setelah)\b"
)
INSTRUCTION_VERB = re.compile(r"\b(diubah|disisipkan|dihapus|ditambah|ditambahkan)\b", re.IGNORECASE)
ANGKA_LABEL = re.compile(r"^Ang\S{1,4}?\s*\d{1,3}$")  # also OCR'd "Ang]<a2"
SUB_LABEL = re.compile(r"^(Ayat|Huruf|Angka)\s*\S{1,5}$")
PASAL_MENTION = re.compile(r"Pas\s?al\s?(\d[0-9OSlI]*[A-Z]?)")  # OCR: "Pasal 2O8", "Pasal 7S"


def _mention_num(raw: str) -> PasalNum:
    digits = re.match(r"\d[0-9OSlI]*", raw)[0]
    return PasalNum(int(digits.translate(str.maketrans("OSlI", "0511"))), raw[len(digits) :])


@dataclass
class Context:
    bab: str | None = None
    bab_title: str | None = None
    bagian: str | None = None


@dataclass
class Unit:
    pasal: PasalNum | None
    lines: list[Line]
    context: Context
    instruction: list[Line] = field(default_factory=list)  # amendment instruction preceding the Pasal


@dataclass
class ParseReport:
    doc_id: str
    n_pasal: dict[str, int] = field(default_factory=dict)  # per part
    rejected_headers: list[str] = field(default_factory=list)
    repaired_headers: list[str] = field(default_factory=list)
    missing_pasal: list[int] = field(default_factory=list)
    instruction_mismatches: list[str] = field(default_factory=list)
    dropped_trivial: int = 0
    notes: list[str] = field(default_factory=list)


def _is_instruction(lines: list[Line], i: int) -> bool:
    if not INSTRUCTION.match(lines[i].text):
        return False
    window = " ".join(ln.text for ln in lines[i : i + 3])
    return bool(INSTRUCTION_VERB.search(window))


def split_units(
    lines: list[Line], allow_roman: bool, detect_instructions: bool
) -> tuple[list[Line], list[Unit], HeaderSelection]:
    """Split a part into leading free text and Pasal units, tracking BAB/Bagian context."""
    selection = select_pasal_headers([ln.text for ln in lines], allow_roman=allow_roman)
    ctx = Context()
    leading: list[Line] = []
    units: list[Unit] = []
    current: Unit | None = None
    title_target: str | None = None  # "bab" | "bagian" while collecting a heading title
    pending: list[Line] = []  # amendment instruction awaiting its Pasal

    def flush_pending_as_unit() -> None:
        if pending:
            m = PASAL_MENTION.search(" ".join(ln.text for ln in pending))
            num = _mention_num(m[1]) if m else None
            units.append(Unit(num, [], Context(**vars(ctx)), list(pending)))
            pending.clear()

    for i, line in enumerate(lines):
        text = line.text
        if i in selection.accepted:
            num = selection.accepted[i]
            header = Line(f"Pasal {num.label}", line.page)  # canonical form of OCR'd "Pasa171"
            current = Unit(num, [header], Context(**vars(ctx)), list(pending))
            units.append(current)
            pending.clear()
            title_target = None
        elif m := BAB.match(text):
            current, title_target = None, "bab"
            ctx = Context(bab=m["num"].replace("l", "I").replace("1", "I"), bab_title=m["title"])
            if m["title"]:
                title_target = None
        elif m := BAGIAN.match(text):
            current, title_target = None, "bagian"
            ctx = Context(ctx.bab, ctx.bab_title, m["num"])
        elif PARAGRAF.match(text):
            current, title_target = None, None
        elif detect_instructions and _is_instruction(lines, i):
            current, title_target = None, None
            flush_pending_as_unit()
            pending.append(line)
        elif current is not None:
            current.lines.append(line)
        elif title_target == "bab":
            ctx.bab_title = f"{ctx.bab_title} {text}".strip() if ctx.bab_title else text
        elif title_target == "bagian":
            ctx.bagian = f"{ctx.bagian} {text}"
            title_target = None
        elif pending:
            pending.append(line)
        elif not units:
            leading.append(line)
    flush_pending_as_unit()
    return leading, units, selection


def _find(pattern: re.Pattern[str], lines: list[Line], start: int, stop: int | None = None) -> int | None:
    for i in range(start, len(lines) if stop is None else stop):
        if pattern.match(lines[i].text):
            return i
    return None


def segment_parts(lines: list[Line], allow_roman: bool) -> dict[str, tuple[int, int]]:
    """Return part name -> (start, end) line ranges."""
    selection = select_pasal_headers([ln.text for ln in lines], allow_roman=allow_roman)
    first_header = min(selection.accepted, default=len(lines))
    first_struct = _find(BAB, lines, 0, first_header)
    body_start = min(first_header, first_struct if first_struct is not None else first_header)
    closing = _find(CLOSING, lines, body_start)
    body_end = closing if closing is not None else len(lines)
    parts = {"preamble": (0, body_start), "body": (body_start, body_end)}
    if closing is None:
        return parts
    starts = {
        "penjelasan": _find(PENJELASAN, lines, closing),
        "lampiran": _find(LAMPIRAN, lines, closing),
    }
    ordered = sorted((s, name) for name, s in starts.items() if s is not None)
    for k, (s, name) in enumerate(ordered):
        end = ordered[k + 1][0] if k + 1 < len(ordered) else len(lines)
        doc_end = _find(DOC_END, lines, s, end)
        parts[name] = (s, doc_end if doc_end is not None else end)
    return parts


class RegulationChunker:
    def __init__(self, cfg: dict[str, Any], count_tokens: TokenCounter) -> None:
        self.max_tokens: int = cfg["max_tokens"]
        self.overlap: int = cfg["window_overlap_tokens"]
        self.drop_trivial: bool = cfg["drop_trivial_penjelasan"]
        self.trivial = re.compile(cfg["trivial_penjelasan_line_pattern"], re.IGNORECASE)
        self.count_tokens = count_tokens

    def chunk(self, meta: DocMeta, lines: list[Line]) -> tuple[list[Chunk], ParseReport]:
        report = ParseReport(meta.doc_id)
        allow_roman = meta.is_amendment
        parts = segment_parts(lines, allow_roman)
        if "penjelasan" not in parts and meta.doc_type in {"UU", "PP"}:
            report.notes.append("no Penjelasan section found")
        chunks: list[Chunk] = []
        for part, (start, end) in parts.items():
            part_lines = lines[start:end]
            if part in {"preamble", "lampiran"}:
                chunks += self._free_text(meta, part, part_lines, Context(), label=None)
                continue
            leading, units, selection = split_units(
                part_lines, allow_roman, detect_instructions=part == "body" and meta.is_amendment
            )
            for i, why in selection.rejected:
                report.rejected_headers.append(f"{part} p{part_lines[i].page}: {part_lines[i].text!r} ({why})")
            for i, how in selection.repaired:
                report.repaired_headers.append(f"{part} p{part_lines[i].page}: {part_lines[i].text!r} {how}")
            report.n_pasal[part] = sum(1 for u in units if u.lines)
            if leading:
                label = "Penjelasan Umum" if part == "penjelasan" else None
                chunks += self._free_text(meta, part, leading, Context(), label=label)
            for unit in units:
                chunks += self._unit_chunks(meta, part, unit, report)
            if part == "body":
                self._check_sequence(meta, units, report)
        for i, c in enumerate(chunks):
            c.chunk_id = f"{meta.doc_id}-{i:04d}"
            c.n_tokens = self.count_tokens(c.text)
        return chunks, report

    def _check_sequence(self, meta: DocMeta, units: list[Unit], report: ParseReport) -> None:
        nums = [u.pasal for u in units if u.pasal and not u.pasal.is_roman and u.lines]
        if meta.is_amendment:
            for u in units:
                if not (u.instruction and u.lines and u.pasal) or u.pasal.is_roman:
                    continue
                instr = " ".join(ln.text for ln in u.instruction)
                mentioned = [_mention_num(m).number for m in PASAL_MENTION.findall(instr)]
                if mentioned and not min(mentioned) <= u.pasal.number <= max(mentioned):
                    report.instruction_mismatches.append(f"Pasal {u.pasal.label} after: {instr[:90]!r}")
            return
        present = {n.number for n in nums}
        if present:
            report.missing_pasal = [n for n in range(1, max(present) + 1) if n not in present]

    def _base_chunk(self, meta: DocMeta, part: str, lines: list[Line], ctx: Context, **kw: Any) -> Chunk:
        text = join_lines([ln.text for ln in lines])
        crumbs = [f"{meta.citation_name} tentang {meta.title}"]
        if part == "penjelasan":
            crumbs.append("Penjelasan")
        elif part != "body":
            crumbs.append(part.capitalize())
        if ctx.bab:
            crumbs.append(f"BAB {ctx.bab}" + (f" {ctx.bab_title}" if ctx.bab_title else ""))
        if ctx.bagian:
            crumbs.append(f"Bagian {ctx.bagian}")
        if kw.get("pasal"):
            ayat = kw.get("ayat")
            ayat_txt = f" ayat ({ayat.replace('-', ')-(')})" if ayat else ""
            crumbs.append(f"Pasal {kw['pasal']}{ayat_txt}")
        elif kw.get("section"):
            crumbs.append(kw["section"])
        return Chunk(
            chunk_id="",
            doc_id=meta.doc_id,
            doc_type=meta.doc_type,
            title=meta.title,
            number=meta.number,
            year=meta.year,
            status=meta.status,
            part=part,
            text=text,
            heading=" > ".join(crumbs),
            page_start=lines[0].page,
            page_end=lines[-1].page,
            bab=ctx.bab,
            bab_title=ctx.bab_title,
            bagian=ctx.bagian,
            amends=list(meta.amends),
            **kw,
        )

    def _free_text(
        self, meta: DocMeta, part: str, lines: list[Line], ctx: Context, label: str | None
    ) -> list[Chunk]:
        windows = window_lines(lines, self.count_tokens, self.max_tokens, self.overlap)
        return [self._base_chunk(meta, part, w, ctx, section=label) for w in windows]

    def _unit_chunks(self, meta: DocMeta, part: str, unit: Unit, report: ParseReport) -> list[Chunk]:
        pasal = unit.pasal.label if unit.pasal else None
        if not unit.lines:  # standalone amendment instruction, e.g. "5. Pasal 20 dihapus."
            return [self._base_chunk(meta, part, unit.instruction, unit.context, pasal=pasal)]
        if part == "penjelasan":
            # "Angka 63" labels the next amendment item (UU 66/2024), not this Pasal
            unit.lines = [ln for ln in unit.lines if not ANGKA_LABEL.match(ln.text)]
            content = [ln.text for ln in unit.lines[1:] if not SUB_LABEL.match(ln.text)]
            if self.drop_trivial and all(self.trivial.match(t) for t in content):
                report.dropped_trivial += 1
                return []
        budget = self.max_tokens
        if unit.instruction:
            budget -= self.count_tokens(join_lines([ln.text for ln in unit.instruction]))
        pieces = split_pasal(unit.lines, self.count_tokens, max(budget, self.max_tokens // 2))
        out = []
        for k, piece in enumerate(pieces):
            lines = (unit.instruction + piece.lines) if k == 0 else piece.lines
            out.append(self._base_chunk(meta, part, lines, unit.context, pasal=pasal, ayat=piece.ayat))
        return out
