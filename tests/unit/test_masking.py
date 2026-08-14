"""PII masking: both directions matter.

The false-positive half of this file is as important as the true-positive half. A
masker that eats unit numbers and carpet areas makes the assistant useless, and
that failure is quieter than a leak because nothing looks broken.
"""

from __future__ import annotations

import pytest

from core.masking import mask_text, masking_service


@pytest.mark.parametrize(
    "text,token_prefix",
    [
        ("My PAN is ABCDE1234F", "PAN"),
        ("Aadhaar 1234 5678 9012", "AADHAAR"),
        ("mail me at rakesh.menon@example.com", "EMAIL"),
        ("call me on +91 98765 43210", "PHONE"),
        ("my account number is 123456789012", "BANK_ACCOUNT"),
        ("IFSC HDFC0001234", "IFSC"),
    ],
)
def test_identifiers_are_masked(text: str, token_prefix: str) -> None:
    result = mask_text(text)
    assert token_prefix in " ".join(result.token_map)
    original = text.split()[-1]
    assert original not in result.masked or not original[0].isalnum()


@pytest.mark.parametrize(
    "text",
    [
        "Unit BW-AUR-A-1204 on the twelfth floor",
        "carpet area is 1245 sqft",
        "the all-in price is 8500000",
        "pincode 560066",
        "ticket TKT-0042 was raised on 2026-07-14",
        "booking BK-9901 for project PRJ-AUR",
    ],
)
def test_domain_identifiers_survive(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text, f"masker damaged a domain identifier: {result.token_map}"


def test_round_trip_restores_original() -> None:
    text = "PAN ABCDE1234F, phone +91 98765 43210, email a.b@example.com"
    result = mask_text(text)
    assert result.restore(result.masked) == text


def test_repeated_identifier_gets_one_token() -> None:
    """Two mentions of the same PAN must not become two different tokens."""
    result = mask_text("PAN ABCDE1234F and again ABCDE1234F")
    assert len(result.token_map) == 1
    assert result.masked.count(next(iter(result.token_map))) == 2


def test_contains_pii_flag() -> None:
    assert masking_service.contains_pii("PAN ABCDE1234F") is True
    assert masking_service.contains_pii("Tower B slab 7 is 60% complete") is False
