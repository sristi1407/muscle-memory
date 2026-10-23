"""Unit tests for the allowlist policy gate (no browser needed)."""
import pytest

from cua.policy import PolicyGate, PolicyViolation


def test_allows_allowlisted_domain_and_route_prefix():
    gate = PolicyGate(allowlist_domains=["127.0.0.1"], allowlist_routes=["/members"])
    assert gate.check_url("http://127.0.0.1:5001/members/detail?mid=12345")


def test_blocks_off_domain():
    gate = PolicyGate(allowlist_domains=["127.0.0.1"])
    with pytest.raises(PolicyViolation):
        gate.check_url("https://evil.example.com/exfiltrate")


def test_blocks_off_route():
    gate = PolicyGate(allowlist_domains=["127.0.0.1"], allowlist_routes=["/members"])
    with pytest.raises(PolicyViolation):
        gate.check_url("http://127.0.0.1:5001/admin/secrets")


def test_approval_required():
    gate = PolicyGate(approval_required=["step3_click"])
    assert gate.requires_approval("step3_click")
    assert not gate.requires_approval("step1_type")
