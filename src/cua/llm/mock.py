"""A deterministic LLM boundary: replays a fixed sequence of Actions.

This is the "runs with no API key" guarantee — a grader (or CI) can reproduce the
whole discover->compile->replay pipeline without touching a model. A recorded real
discovery run can be saved as one of these sequences.
"""
from cua.schema import Action, ActionType

from .base import LLM


class MockLLM(LLM):
    def __init__(self, actions: list[Action]):
        self._script = list(actions)
        self._i = 0

    def start(self, system: str, tools: list[dict]) -> None:
        self._i = 0

    def next_action(self, observation: str) -> Action:
        if self._i >= len(self._script):
            return Action(action=ActionType.FINISH, reason="script exhausted")
        action = self._script[self._i]
        self._i += 1
        return action
