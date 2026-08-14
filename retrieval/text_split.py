"""Pure markdown splitting primitives.

Deliberately free of pydantic and settings imports so this logic can be tested on
its own — it is where the subtle bugs live. `chunker.py` wraps these functions and
attaches document metadata.

Two invariants the tests hold this to:
  1. No emitted chunk exceeds the hard token ceiling.
  2. A markdown table or a numbered checklist is never split mid-structure. A
     severity matrix cut in half retrieves as two useless fragments, and the
     deterministic priority code that quotes it would cite a partial table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TARGET_MIN_TOKENS = 400
TARGET_MAX_TOKENS = 700
OVERLAP_RATIO = 0.15

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def estimate_tokens(text: str) -> int:
    """Approximate token count without a tokenizer dependency.

    Words times 1.3 plus punctuation tracks BPE closely enough for a chunk-size
    budget, and being slightly pessimistic is the safe direction: it makes chunks
    a little smaller than the ceiling rather than a little larger.
    """
    words = len(text.split())
    punctuation = sum(text.count(c) for c in ".,;:|()[]{}/-")
    return int(words * 1.3 + punctuation * 0.3) + 1


@dataclass
class Block:
    """An atomic unit of text. `atomic=True` means never split this internally."""

    text: str
    kind: str  # "prose" | "table" | "list" | "code"
    atomic: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass
class Section:
    heading: str | None
    level: int
    blocks: list[Block] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(b.tokens for b in self.blocks)


def strip_frontmatter(raw: str) -> tuple[str, str]:
    """Return (frontmatter_text, body). Frontmatter is the leading --- block."""
    if not raw.startswith("---"):
        return "", raw
    parts = raw.split("\n---", 2)
    if len(parts) < 2:
        return "", raw
    fm = parts[0][3:].strip("\n")
    body = parts[1]
    if len(parts) > 2:
        body = parts[1] + "\n---" + parts[2]
    return fm, body.lstrip("\n")


def to_blocks(text: str) -> list[Block]:
    """Group lines into blocks, marking tables, lists and code fences atomic."""
    lines = text.split("\n")
    blocks: list[Block] = []
    buf: list[str] = []
    mode = "prose"
    in_fence = False

    def flush() -> None:
        nonlocal buf, mode
        if buf and any(line.strip() for line in buf):
            blocks.append(
                Block(
                    text="\n".join(buf).strip("\n"),
                    kind=mode,
                    atomic=mode in {"table", "list", "code"},
                )
            )
        buf = []
        mode = "prose"

    for line in lines:
        fence = line.strip().startswith("```")
        if fence:
            if in_fence:
                buf.append(line)
                in_fence = False
                mode = "code"
                flush()
            else:
                flush()
                in_fence = True
                mode = "code"
                buf.append(line)
            continue
        if in_fence:
            buf.append(line)
            continue

        is_table = bool(_TABLE_ROW.match(line))
        is_list = bool(_LIST_ITEM.match(line))
        blank = not line.strip()

        if blank:
            # A blank line ends prose, but not a list: checklists commonly have
            # blank lines between items and must stay one block.
            if mode == "list":
                buf.append(line)
            else:
                flush()
            continue

        want = "table" if is_table else "list" if is_list else "prose"
        if want != mode and buf:
            # A continuation line indented under a list item belongs to the list.
            if not (mode == "list" and want == "prose" and line.startswith(("  ", "\t"))):
                flush()
        if want != "prose" or mode == "prose":
            mode = want if want != "prose" else mode
        if mode == "prose" and want == "prose":
            mode = "prose"
        elif want != "prose":
            mode = want
        buf.append(line)

    flush()
    return blocks


def split_sections(body: str) -> list[Section]:
    """Split markdown into heading-scoped sections, preserving heading text."""
    sections: list[Section] = []
    current = Section(heading=None, level=0)
    pending: list[str] = []

    def close() -> None:
        nonlocal pending, current
        if pending:
            current.blocks.extend(to_blocks("\n".join(pending)))
            pending = []
        if current.blocks or current.heading:
            sections.append(current)

    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            close()
            current = Section(heading=m.group(2).strip(), level=len(m.group(1)))
            pending = []
        else:
            pending.append(line)
    close()
    return [s for s in sections if s.blocks]


def _tail_overlap(blocks: list[Block], budget_tokens: int) -> list[Block]:
    """Pick trailing non-atomic blocks to repeat as overlap for the next chunk."""
    out: list[Block] = []
    used = 0
    for block in reversed(blocks):
        if block.atomic:
            break
        if used + block.tokens > budget_tokens:
            break
        out.insert(0, block)
        used += block.tokens
    return out


def split_atomic_table(block: Block, max_tokens: int) -> list[Block]:
    """Last resort for a table larger than the ceiling: repeat the header.

    A header-less table fragment is unusable, so the header and separator rows are
    carried into every part.
    """
    lines = block.text.split("\n")
    header = lines[:2] if len(lines) > 2 else lines
    rows = lines[2:] if len(lines) > 2 else []
    parts: list[Block] = []
    buf: list[str] = []
    for row in rows:
        candidate = "\n".join(header + buf + [row])
        if buf and estimate_tokens(candidate) > max_tokens:
            parts.append(Block("\n".join(header + buf), "table", atomic=True))
            buf = [row]
        else:
            buf.append(row)
    if buf:
        parts.append(Block("\n".join(header + buf), "table", atomic=True))
    return parts or [block]


def pack(
    sections: list[Section],
    min_tokens: int = TARGET_MIN_TOKENS,
    max_tokens: int = TARGET_MAX_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[tuple[str | None, str]]:
    """Pack sections into (section_heading, chunk_text) pairs.

    Small sections are merged with their neighbours under the same top heading so
    a one-line section does not become a one-line chunk with no context. Large
    sections are split on block boundaries with an overlap tail.
    """
    out: list[tuple[str | None, str]] = []
    overlap_budget = int(max_tokens * overlap_ratio)

    for section in sections:
        blocks: list[Block] = []
        for block in section.blocks:
            if block.atomic and block.tokens > max_tokens and block.kind == "table":
                blocks.extend(split_atomic_table(block, max_tokens))
            else:
                blocks.append(block)

        heading_text = f"{'#' * max(1, section.level)} {section.heading}" if section.heading else ""
        buf: list[Block] = []
        buf_tokens = estimate_tokens(heading_text)

        def emit(current: list[Block]) -> None:
            if not current:
                return
            text = "\n\n".join([heading_text] + [b.text for b in current]).strip()
            out.append((section.heading, text))

        for block in blocks:
            if block.tokens > max_tokens and not block.atomic:
                # Oversized prose: split on sentence boundaries.
                sentences = re.split(r"(?<=[.!?])\s+", block.text)
                sub: list[str] = []
                for sentence in sentences:
                    if sub and estimate_tokens(" ".join(sub + [sentence])) > max_tokens:
                        blocks_append = Block(" ".join(sub), "prose")
                        if buf_tokens + blocks_append.tokens > max_tokens and buf:
                            emit(buf)
                            buf = _tail_overlap(buf, overlap_budget)
                            buf_tokens = estimate_tokens(heading_text) + sum(b.tokens for b in buf)
                        buf.append(blocks_append)
                        buf_tokens += blocks_append.tokens
                        sub = [sentence]
                    else:
                        sub.append(sentence)
                if sub:
                    block = Block(" ".join(sub), "prose")
                else:
                    continue

            if buf and buf_tokens + block.tokens > max_tokens:
                emit(buf)
                buf = _tail_overlap(buf, overlap_budget)
                buf_tokens = estimate_tokens(heading_text) + sum(b.tokens for b in buf)
            buf.append(block)
            buf_tokens += block.tokens

        if buf:
            # Merge a runt tail into the previous chunk of the same section when
            # that keeps us under the ceiling.
            text = "\n\n".join([heading_text] + [b.text for b in buf]).strip()
            if (
                out
                and estimate_tokens(text) < min_tokens // 3
                and out[-1][0] == section.heading
                and estimate_tokens(out[-1][1] + text) <= max_tokens
            ):
                out[-1] = (section.heading, out[-1][1] + "\n\n" + "\n\n".join(b.text for b in buf))
            else:
                emit(buf)
    return out


def find_injection_patterns(text: str) -> list[str]:
    """Flag instruction-like content in ingested documents (architecture 6.4).

    Detection is for review and labelling only. The defence is architectural:
    document text is never treated as instructions, and access control sits below
    the model. This just makes an attempt visible.
    """
    # Grouped by attack shape rather than listed flat, because the groups are what
    # you extend when a new phrasing appears. The first version of this list only
    # covered "ignore previous instructions" and scored 0.3 recall on the eval set —
    # it missed uppercase variants, the word "prior", chat-template markers, and
    # role-prefix spoofing. Every pattern below is checked against the benign corpus
    # in tests/security/test_injection.py, because a detector that flags ordinary
    # engineer prose is worse than useless: it trains people to ignore the flag.
    patterns = [
        # --- instruction override -----------------------------------------
        r"ignore\s+(?:all\s+)?(?:of\s+)?(?:your\s+|the\s+|any\s+)?"
        r"(?:previous|prior|earlier|above|preceding|foregoing)\s+"
        r"(?:instructions?|rules?|prompts?|directions?|guidance)",
        r"disregard\s+(?:all\s+)?(?:of\s+)?(?:your\s+|the\s+|any\s+)?"
        r"(?:previous|prior|earlier|above|preceding)\s*"
        r"(?:instructions?|rules?|prompts?|directions?|guidance)?",
        r"forget\s+(?:all\s+)?(?:your|the|any|everything)\s*"
        r"(?:previous|prior|earlier)?\s*(?:instructions?|rules?|prompts?|training)",
        r"(?:override|bypass|ignore)\s+(?:the\s+)?"
        r"(?:risk|tier|policy|policies|approval|disclosure|guardrails?|restrictions?|safety)",
        r"new\s+instructions?\s*[:\-]",
        r"updated\s+instructions?\s*[:\-]",
        r"instead\s+of\s+(?:your|the)\s+(?:instructions|rules)",

        # --- role and template spoofing -----------------------------------
        # Chat-template markers have no legitimate reason to appear in a site report
        # or a policy document, so they are flagged on sight.
        r"<\|\s*(?:im_start|im_end|system|user|assistant|endoftext)\s*\|>",
        r"#{2,}\s*(?:system|instruction|prompt)\s*#{2,}",
        r"\[/?inst\]",
        r"<</?sys>>",
        r"\{\{\s*system\s*\}\}",
        # A line that opens by claiming to be the system or the assistant.
        r"(?:^|\n)\s*(?:system|assistant|developer|admin)\s*[:>]",
        r"system\s+(?:note|prompt|message|override|instruction)\s*[:\-]",
        r"(?:note|message|instruction)\s+(?:to|for)\s+the\s+(?:ai|assistant|model|bot|llm)\s*[:\-]?",
        r"\bassistant\s*,\s*(?:please\s+)?(?:disregard|ignore|forget|approve|confirm|skip)",

        # --- persona and mode switching -----------------------------------
        r"developer\s+mode",
        r"(?:you\s+are|act\s+as|pretend\s+to\s+be|behave\s+as)\s+"
        r"(?:now\s+)?(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken|dan\b|different\s+ai)",
        r"you\s+(?:are|must|should|will)\s+now\s+"
        r"(?:act|behave|respond|operate|be|ignore|in\s+)",
        r"as\s+an\s+ai(?:\s+assistant|\s+model|\s+language\s+model)?\s*[,:]?\s*you\s+"
        r"(?:must|should|can|are)",

        # --- process subversion -------------------------------------------
        r"skip\s+(?:the\s+)?(?:human\s+)?(?:approval|review|verification|citations?|checks?)",
        r"(?:without|no need for)\s+(?:human\s+)?(?:approval|review)",
        r"do\s+not\s+(?:cite|mention|disclose|log|record|escalate)",
        r"reveal\s+(?:the\s+|your\s+)?(?:system\s+)?(?:prompt|instructions|cost\s+sheet|margin)",
        r"(?:tell|show|give)\s+(?:me|the\s+customer)\s+the\s+(?:internal|confidential)\s+"
        r"(?:margin|cost|price|rate)",
        r"list\s+all\s+(?:customer|customers|bookings|records|units|leads)",
        r"disclose\s+the\s+.{0,40}date",
        r"(?:approve|confirm|grant)\s+(?:this\s+|the\s+)?"
        r"(?:refund|payment|extension|waiver|discount)",
    ]

    found: list[str] = []
    low = text.lower()
    for pattern in patterns:
        match = re.search(pattern, low, re.I)
        if match:
            # The matched text, not the regex: the reviewer needs to see what
            # tripped the flag in order to judge whether it is a real attempt.
            found.append(match.group(0).strip()[:80])
    return found
