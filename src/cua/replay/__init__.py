"""P3 replay: execute a Capability deterministically, with no LLM in the loop."""
from .engine import ReplayEngine, resolve_value

__all__ = ["ReplayEngine", "resolve_value"]
