"""The policy gate — an allowlist enforced on actions.

Every navigation is checked against the capability's allowlist (domain, then route
prefix). Anything off-allowlist raises PolicyViolation, so an agent can't wander
off the sanctioned application. Risky steps can also be flagged as needing approval.
"""
from urllib.parse import urlparse


class PolicyViolation(RuntimeError):
    """An action tried to go outside the allowlist."""


class PolicyGate:
    def __init__(self, allowlist_domains=None, allowlist_routes=None, approval_required=None):
        self.allowlist_domains = list(allowlist_domains or [])
        self.allowlist_routes = list(allowlist_routes or [])
        self.approval_required = set(approval_required or [])

    @classmethod
    def from_capability(cls, cap) -> "PolicyGate":
        p = cap.policy
        return cls(p.allowlist_domains, p.allowlist_routes, p.approval_required)

    def check_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if self.allowlist_domains and host not in self.allowlist_domains:
            raise PolicyViolation(f"blocked: domain '{host}' not in allowlist {self.allowlist_domains}")
        path = parsed.path or "/"
        if self.allowlist_routes and not any(path.startswith(r) for r in self.allowlist_routes):
            raise PolicyViolation(f"blocked: route '{path}' not in allowlist {self.allowlist_routes}")
        return True

    def requires_approval(self, step_id: str) -> bool:
        return step_id in self.approval_required
