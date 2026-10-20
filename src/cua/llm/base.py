"""The LLM boundary — a provider-agnostic seam for the discovery brain.

The agent loop talks to this interface, never to a vendor SDK. That's what makes
the model a *driver*: Claude, Nemotron, or a deterministic mock all satisfy the
same contract, so swapping one is a config change, not a rewrite.

Conversation state (message history, tool-call protocol) lives *inside* the
implementation, so the agent loop stays simple: start(), then next_action() /
record_result() each turn.
"""
from abc import ABC, abstractmethod

from cua.schema import Action


class LLMError(RuntimeError):
    """The model failed to produce a usable action."""


class LLM(ABC):
    @abstractmethod
    def start(self, system: str, tools: list[dict]) -> None:
        """Begin a fresh discovery conversation with a system prompt + tool schema."""

    @abstractmethod
    def next_action(self, observation: str) -> Action:
        """Given the current screen observation, decide the next Action."""

    def record_result(self, text: str) -> None:
        """Feed the result of the last action back to the model. No-op for stateless mocks."""
        return None
