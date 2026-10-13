"""Detect Pasal headers and split long Pasal by ayat, tolerating OCR noise.

Header candidates are lines like "Pasal 15A". OCR produces variants ("Pasa171", "Pasal 1O0",
"Pasal I 1O", "Fasal 104"), and wrapped cross-references can also put "Pasal 12" alone on a
line. Real headers increase monotonically, so the accepted set is the longest increasing
subsequence of candidates; out-of-order candidates are rejected and reported.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from maritime_rag.cleaning import CONNECTOR_END, LIST_ITEM, Line, join_lines

TokenCounter = Callable[[str], int]

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_OCR_DIGITS = str.maketrans(
    {"O": "0", "o": "0", "I": "1", "l": "1", "L": "1", "|": "1", "!": "1", "S": "5", "Z": "2", "T": "7"}
)
_DIGITISH = r"[0-9OoIlL|!SZT]"
# OCR readings of an inserted-Pasal suffix as a digit: "Pasal 268" for "Pasal 26B"
_SUFFIX_MISREAD = {"8": "B", "4": "A"}
PASAL_HEADER = re.compile(
    rf"^[PF]\s?a\s?s\s?a\s?[l1I!|]\s*(?P<num>{_DIGITISH}(?:\s?{_DIGITISH}){{0,3}})\s?(?P<suffix>[A-Z])?\s*$"
)


@dataclass(frozen=True, order=True)
class PasalNum:
    """Sortable Pasal number: arabic 15A -> (15, "A"); roman I/II use is_roman."""

    number: int
    suffix: str = ""
    is_roman: bool = False

    @property
    def label(self) -> str:
        if self.is_roman:
            return next(k for k, v in ROMAN.items() if v == self.number)
        return f"{self.number}{self.suffix}"


def parse_pasal_header(text: str, allow_roman: bool = False) -> PasalNum | None:
    """Parse a standalone Pasal header line; None if the line is not a header."""
    m = PASAL_HEADER.match(re.sub(r"\s+", " ", text.strip()))
    if not m:
        return None
    raw = m["num"].replace(" ", "")
    suffix = m["suffix"] or ""
    if allow_roman and raw + suffix in ROMAN:
        return PasalNum(ROMAN[raw + suffix], is_roman=True)
    digits = raw.translate(_OCR_DIGITS)
    if not digits.isdigit() or not 0 < int(digits) < 1000:
        return None
    return PasalNum(int(digits), suffix)


def _longest_increasing(keys: Sequence[PasalNum]) -> list[int]:
    """Indices of a longest strictly increasing subsequence (patience sorting)."""
    tails: list[PasalNum] = []
    tail_idx: list[int] = []
    prev = [-1] * len(keys)
    for i, k in enumerate(keys):
        pos = bisect_left(tails, k)
        if pos < len(tails) and tails[pos] == k:
            continue  # keep the earlier of two equal headers; the later one may be repairable
        if pos == len(tails):
            tails.append(k)
            tail_idx.append(i)
        else:
            tails[pos] = k
            tail_idx[pos] = i
        prev[i] = tail_idx[pos - 1] if pos else -1
    out, i = [], tail_idx[-1] if tail_idx else -1
    while i != -1:
        out.append(i)
        i = prev[i]
    return out[::-1]


def _repair(num: PasalNum, prev: PasalNum | None, nxt: PasalNum | None) -> PasalNum | None:
    """Re-read an out-of-sequence header so it fits between its accepted neighbours, if it can."""
    if prev is None or nxt is None:
        return None
    digits = str(num.number)
    if not num.suffix and len(digits) > 1 and digits[-1] in _SUFFIX_MISREAD:
        alt = PasalNum(int(digits[:-1]), _SUFFIX_MISREAD[digits[-1]])
        if prev < alt < nxt:
            return alt
    if not prev.suffix and not nxt.suffix and nxt.number - prev.number == 2:
        return PasalNum(prev.number + 1)  # the only number that can sit in the gap
    return None


@dataclass(frozen=True)
class HeaderSelection:
    accepted: dict[int, PasalNum]  # line index -> number
    rejected: list[tuple[int, str]]  # (line index, reason)
    repaired: list[tuple[int, str]]  # (line index, "read as Pasal X")
    overridden: list[tuple[int, str]]  # (line index, what the manual override did)


def _keep_increasing(group: list[tuple[int, PasalNum]], pinned: set[int]) -> set[int]:
    """Positions in group to keep: all pinned ones, plus the longest increasing run between pins."""
    keep = set(pinned)
    bounds = [-1, *sorted(pinned), len(group)]
    for a, b in zip(bounds, bounds[1:]):
        lo = group[a][1] if a >= 0 else None
        hi = group[b][1] if b < len(group) else None
        seg = [j for j in range(a + 1, b) if (lo is None or group[j][1] > lo) and (hi is None or group[j][1] < hi)]
        keep |= {seg[k] for k in _longest_increasing([group[j][1] for j in seg])}
    return keep


def select_pasal_headers(
    lines: Sequence[str], allow_roman: bool = False, forced: dict[int, PasalNum | None] | None = None
) -> HeaderSelection:
    """Choose the real Pasal headers among candidate lines.

    Roman headers (Pasal I, II in amending regulations) split the sequence into groups;
    within each group the arabic headers must strictly increase. `forced` pins manual
    overrides: line index -> Pasal number (always accepted) or None (never a header).
    """
    forced = forced or {}
    accepted: dict[int, PasalNum] = {}
    rejected: list[tuple[int, str]] = []
    repaired: list[tuple[int, str]] = []
    overridden: list[tuple[int, str]] = []
    groups: list[list[tuple[int, PasalNum]]] = [[]]
    pinned: list[set[int]] = [set()]
    last_roman = 0
    for i, text in enumerate(lines):
        if i in forced:
            pin = forced[i]
            if pin is None:
                overridden.append((i, "not a Pasal header"))
            else:
                overridden.append((i, f"read as Pasal {pin.label}"))
                pinned[-1].add(len(groups[-1]))
                groups[-1].append((i, pin))
            continue
        num = parse_pasal_header(text, allow_roman)
        if num is None:
            continue
        if i > 0 and CONNECTOR_END.search(lines[i - 1].strip()):
            rejected.append((i, "follows an unfinished sentence (cross-reference)"))
            continue
        if num.is_roman:
            if num.number == last_roman + 1:
                accepted[i] = num
                last_roman = num.number
                groups.append([])
                pinned.append(set())
            else:
                rejected.append((i, f"roman Pasal {num.label} out of order"))
            continue
        groups[-1].append((i, num))
    for group, pins in zip(groups, pinned):
        keep = _keep_increasing(group, pins)
        prev: PasalNum | None = None
        for j, (i, num) in enumerate(group):
            if j in keep:
                accepted[i] = prev = num
                continue
            nxt = next((group[k][1] for k in range(j + 1, len(group)) if k in keep), None)
            fixed = _repair(num, prev, nxt)
            if fixed is not None:
                accepted[i] = prev = fixed
                repaired.append((i, f"Pasal {num.label} read as Pasal {fixed.label}"))
            else:
                rejected.append((i, f"Pasal {num.label} breaks the increasing sequence"))
    return HeaderSelection(dict(sorted(accepted.items())), sorted(rejected), sorted(repaired), sorted(overridden))


# --- ayat splitting -------------------------------------------------------------------------

_DIGIT_CLASS = {"0": "[0Oo]", "1": "[1lI|!]", "2": "[2Z]", "5": "[5S]"}
_SENTENCE_REF_END = re.compile(r"\b(ayat|pada|dalam|dan|atau)$", re.IGNORECASE)


def _ayat_patterns(n: int) -> tuple[re.Pattern[str], re.Pattern[str]]:
    digits = r"\s?".join(_DIGIT_CLASS.get(c, c) for c in str(n))
    strict = re.compile(rf"^(?:Ayat\s*)?\(\s?{str(n)}\s?\)")
    # OCR variants: "(21" "l2l" "(2l" "{2)" -- substitute brackets must be followed by a space
    loose = re.compile(rf"^(?:Ayat\s*)?[(\[{{lI|]\s?{digits}\s?[)\]}}lI1|]\s")
    return strict, loose


def find_ayat_starts(lines: Sequence[str]) -> list[tuple[int, int]]:
    """Return (line index, ayat number) for each ayat marker, matched sequentially from (1)."""
    starts: list[tuple[int, int]] = []
    expected = 1
    for i, text in enumerate(lines):
        text = text.strip()
        if i > 0 and _SENTENCE_REF_END.search(lines[i - 1].strip()):
            continue
        strict, loose = _ayat_patterns(expected)
        if strict.match(text) or loose.match(text):
            starts.append((i, expected))
            expected += 1
            continue
        # tolerate one marker lost to OCR if the following one is clean
        if starts and _ayat_patterns(expected + 1)[0].match(text):
            starts.append((i, expected + 1))
            expected += 2
    return starts


@dataclass(frozen=True)
class Piece:
    lines: list[Line]
    ayat: str | None  # "2" or "1-3"; None when not split by ayat

    @property
    def text(self) -> str:
        return join_lines([ln.text for ln in self.lines])


def _ayat_label(first: str | None, last: str | None) -> str | None:
    if first is None:
        return None
    return first if first == last else f"{first}-{last}"


def window_lines(
    lines: list[Line], count_tokens: TokenCounter, max_tokens: int, overlap_tokens: int = 0
) -> list[list[Line]]:
    """Greedy line windows under max_tokens, with roughly overlap_tokens of carried-over lines."""
    if not lines:
        return []
    costs = [count_tokens(ln.text) + 1 for ln in lines]
    windows: list[list[Line]] = []
    start = 0
    while start < len(lines):
        end, total = start, 0
        while end < len(lines) and (end == start or total + costs[end] <= max_tokens):
            total += costs[end]
            end += 1
        windows.append(lines[start:end])
        if end >= len(lines):
            break
        back, carried = end, 0
        while back - 1 > start and carried + costs[back - 1] <= overlap_tokens:
            back -= 1
            carried += costs[back]
        start = back
    return windows


def _blocks_by(lines: list[Line], starts: list[int]) -> list[list[Line]]:
    bounds = [0] + [s for s in starts if s > 0] + [len(lines)]
    return [lines[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]


def _split_oversized(block: list[Line], count_tokens: TokenCounter, max_tokens: int) -> list[list[Line]]:
    """Split a block by list items (huruf/angka), packing items; fall back to line windows."""
    item_starts = [i for i, ln in enumerate(block) if LIST_ITEM.match(ln.text.strip())]
    items = _blocks_by(block, item_starts) if len(item_starts) >= 2 else [block]
    packed: list[list[Line]] = []
    for group in _pack(items, count_tokens, max_tokens):
        if count_tokens(join_lines([ln.text for ln in group])) <= max_tokens:
            packed.append(group)
        else:
            packed.extend(window_lines(group, count_tokens, max_tokens))
    return packed


def _pack(blocks: list[list[Line]], count_tokens: TokenCounter, max_tokens: int) -> list[list[Line]]:
    groups: list[list[Line]] = []
    cur: list[Line] = []
    for block in blocks:
        candidate = cur + block
        if cur and count_tokens(join_lines([ln.text for ln in candidate])) > max_tokens:
            groups.append(cur)
            cur = list(block)
        else:
            cur = candidate
    if cur:
        groups.append(cur)
    return groups


def split_pasal(lines: list[Line], count_tokens: TokenCounter, max_tokens: int) -> list[Piece]:
    """Split one Pasal into pieces under max_tokens: by ayat first, then list items, then windows."""
    text = join_lines([ln.text for ln in lines])
    if count_tokens(text) <= max_tokens:
        return [Piece(lines, None)]

    starts = find_ayat_starts([ln.text for ln in lines])
    if len(starts) < 2:
        return [Piece(chunk, None) for chunk in _split_oversized(lines, count_tokens, max_tokens)]

    # the header line ("Pasal 5") and any intro text stay with ayat (1)
    blocks = _blocks_by(lines, [i for i, _ in starts])
    labels = [str(n) for _, n in starts]
    if starts[0][0] > 0 and len(blocks) > len(labels):
        blocks = [blocks[0] + blocks[1]] + blocks[2:]

    pieces: list[Piece] = []
    cur: list[Line] = []
    cur_labels: list[str] = []

    def flush() -> None:
        if cur:
            pieces.append(Piece(list(cur), _ayat_label(cur_labels[0], cur_labels[-1])))
            cur.clear()
            cur_labels.clear()

    for block, label in zip(blocks, labels):
        block_text = join_lines([ln.text for ln in block])
        if count_tokens(block_text) > max_tokens:
            flush()
            pieces.extend(Piece(part, label) for part in _split_oversized(block, count_tokens, max_tokens))
            continue
        if cur and count_tokens(join_lines([ln.text for ln in cur + block])) > max_tokens:
            flush()
        cur.extend(block)
        cur_labels.append(label)
    flush()
    return pieces
