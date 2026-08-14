"""PII masking, applied at intake before any model call and before any log write.

Design notes worth keeping in mind if you edit the patterns:

* Masking runs *before* classification, so the models never see raw identifiers.
  The reversible map lives in memory for the lifetime of one request and is never
  persisted — restoring a PAN into a stored draft would defeat the point.
* False positives are as harmful as misses here. Unit numbers ("A-1204"),
  pincodes ("560066"), areas ("1245 sqft") and money ("8500000") must survive
  untouched or every property answer turns into `[BANK_ACCOUNT_1] sqft`. The
  patterns are therefore deliberately narrow and ordered most-specific-first.
* Bank account numbers have no checkable structure, so a bare 9-18 digit run is
  only masked when a keyword ("a/c", "account") sits next to it, or when its
  length cannot be confused with a phone (10), an Aadhaar (12) or a pincode (6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Ordered most specific to least. Each entry is (label, compiled pattern).
_PAN = re.compile(r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])")

_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+\.[\w.]{2,}(?![\w.])")

_PHONE_PATTERNS = (
    re.compile(r"(?<![\d+])\+?91[\s-]?[6-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)[6-9]\d{4}[\s-]\d{5}(?!\d)"),
    re.compile(r"(?<!\d)[6-9]\d{2}[\s-]\d{3}[\s-]\d{4}(?!\d)"),
    re.compile(r"(?<![\d+])[6-9]\d{9}(?!\d)"),
)

# "a/c 123456789012345" style — keyword adjacency makes a bare digit run safe to mask.
_BANK_KEYWORD = re.compile(
    r"(?i)\b(?:a/?c(?:count)?|acct|bank\s+account|account\s+(?:no\.?|number))"
    r"\s*(?:no\.?|number|#|:)?\s*(?P<num>\d{9,18})(?!\d)"
)
# Lengths that cannot be a phone (10), Aadhaar (12) or pincode (6).
_BANK_STANDALONE = re.compile(r"(?<!\d)(?:\d{11}|\d{13,18})(?!\d)")

_IFSC = re.compile(r"(?<![A-Z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Z0-9])")

_LABELS = {
    "PAN": "PAN",
    "AADHAAR": "AADHAAR",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
    "BANK_ACCOUNT": "BANK_ACCOUNT",
    "IFSC": "IFSC",
}


@dataclass
class MaskResult:
    """Masked text plus the map needed to restore it inside one request."""

    masked: str
    token_map: dict[str, str] = field(default_factory=dict)

    @property
    def found_types(self) -> set[str]:
        return {t.split("_")[0] if not t.startswith("BANK") else "BANK" for t in self.token_map}

    def restore(self, text: str) -> str:
        """Substitute originals back in. Used only for human-facing review views."""
        out = text
        for token, original in self.token_map.items():
            out = out.replace(token, original)
        return out


class MaskingService:
    """Stateless masker. One instance is safe to share across requests."""

    def mask(self, text: str) -> MaskResult:
        """Replace every recognised identifier with a stable placeholder token.

        Tokens are numbered per type and repeated occurrences of the same value
        reuse the same token, so "the PAN I sent earlier" still resolves.
        """
        if not text:
            return MaskResult(masked=text or "", token_map={})

        token_map: dict[str, str] = {}
        reverse: dict[str, str] = {}
        counters: dict[str, int] = {}

        def token_for(label: str, value: str) -> str:
            key = f"{label}:{_normalise(value)}"
            if key in reverse:
                return reverse[key]
            counters[label] = counters.get(label, 0) + 1
            tok = f"[{label}_{counters[label]}]"
            reverse[key] = tok
            token_map[tok] = value
            return tok

        out = text

        # 1. PAN and IFSC: alphanumeric shapes, no overlap risk with digit runs.
        out = _PAN.sub(lambda m: token_for(_LABELS["PAN"], m.group(0)), out)
        out = _IFSC.sub(lambda m: token_for(_LABELS["IFSC"], m.group(0)), out)

        # 2. Email before phone: an address can contain digit runs.
        out = _EMAIL.sub(lambda m: token_for(_LABELS["EMAIL"], m.group(0)), out)

        # 3. Keyword-anchored bank accounts before Aadhaar, because "a/c 2345 6789 0123"
        #    is an account number even though it also matches the Aadhaar shape.
        out = _BANK_KEYWORD.sub(
            lambda m: m.group(0).replace(
                m.group("num"), token_for(_LABELS["BANK_ACCOUNT"], m.group("num"))
            ),
            out,
        )

        # 4. Aadhaar (12 digits, optionally grouped).
        out = _AADHAAR.sub(lambda m: token_for(_LABELS["AADHAAR"], m.group(0)), out)

        # 5. Phones, longest form first.
        for pattern in _PHONE_PATTERNS:
            out = pattern.sub(lambda m: token_for(_LABELS["PHONE"], m.group(0)), out)

        # 6. Remaining unambiguous account-length digit runs.
        out = _BANK_STANDALONE.sub(lambda m: token_for(_LABELS["BANK_ACCOUNT"], m.group(0)), out)

        return MaskResult(masked=out, token_map=token_map)

    def contains_pii(self, text: str) -> bool:
        """True when the text still holds anything the masker recognises.

        Used as a test and log-time invariant: nothing that fails this should
        reach a prompt, a trace row or the audit viewer.
        """
        return bool(self.mask(text).token_map)


def _normalise(value: str) -> str:
    return re.sub(r"[\s-]", "", value).upper()


#: Module-level singleton; masking has no per-request state of its own.
masking_service = MaskingService()


def mask_text(text: str) -> MaskResult:
    """Convenience wrapper so callers do not import the class."""
    return masking_service.mask(text)
