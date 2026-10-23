"""Redaction — keep secrets/PII out of observations, traces, logs, and screenshots.

Applied at the *source* (the surface's perception) so sensitive data like the
synthetic SSN never reaches the model, the trace, the evidence store, or a
screenshot. Declared-sensitive input values can also be masked by exact match.
"""
import re

DEFAULT_PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

# Injected into a live page to scrub PII text nodes BEFORE a screenshot is captured.
REDACT_DOM_JS = r"""
(() => {
  const re = /\b\d{3}-\d{2}-\d{4}\b/g;
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walk.nextNode()) nodes.push(walk.currentNode);
  for (const n of nodes) {
    if (re.test(n.nodeValue)) n.nodeValue = n.nodeValue.replace(re, '[REDACTED]');
  }
})();
"""


class Redactor:
    def __init__(self, sensitive_values: list[str] | None = None, patterns: dict | None = None):
        self.patterns = patterns if patterns is not None else DEFAULT_PATTERNS
        self.sensitive_values = [v for v in (sensitive_values or []) if v]

    def redact(self, text: str | None) -> str | None:
        if not text:
            return text
        out = text
        for value in self.sensitive_values:
            out = out.replace(value, "[REDACTED]")
        for name, pattern in self.patterns.items():
            out = pattern.sub(f"[REDACTED:{name}]", out)
        return out

    def contains_pii(self, text: str | None) -> bool:
        if not text:
            return False
        return any(p.search(text) for p in self.patterns.values())
