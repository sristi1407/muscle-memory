"""Evidence store: per-run JSONL logs, per-step screenshots, and a failure snapshot."""
from .recorder import EvidenceRecorder, NullRecorder

__all__ = ["EvidenceRecorder", "NullRecorder"]
