"""P1 discovery: the observe->decide->act loop that produces a success trace."""
from .discovery import SYSTEM_PROMPT, DiscoveryAgent, render_observation
from .trace import DiscoveryTrace, TraceStep

__all__ = ["DiscoveryAgent", "DiscoveryTrace", "TraceStep", "SYSTEM_PROMPT", "render_observation"]
