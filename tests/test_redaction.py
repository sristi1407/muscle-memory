"""Unit tests for the redaction layer (no browser needed)."""
from cua.policy import Redactor

SSN = "412-55-9832"


def test_redacts_ssn_pattern():
    out = Redactor().redact(f"Tax ID (SSN) {SSN} shown on detail")
    assert SSN not in out
    assert "[REDACTED:SSN]" in out


def test_redacts_declared_sensitive_values():
    out = Redactor(sensitive_values=["s3cr3t-token"]).redact("auth=s3cr3t-token ok")
    assert "s3cr3t-token" not in out
    assert "[REDACTED]" in out


def test_leaves_non_pii_untouched():
    text = "Savings $4,210.55  Member ID 12345"
    assert Redactor().redact(text) == text


def test_contains_pii():
    r = Redactor()
    assert r.contains_pii(f"ssn {SSN}")
    assert not r.contains_pii("nothing sensitive here")


def test_none_and_empty_are_safe():
    r = Redactor()
    assert r.redact(None) is None
    assert r.redact("") == ""
