"""Surface abstraction: how we perceive and act on a target application.

A Surface hides *how* we touch a UI (Playwright web today; legacy-web or desktop
later) behind one interface. There are deliberately two acting paths:

  * discovery-time — act by the accessible *description* the LLM emits, and report
    back the locator strategies that worked, so the compiler can bake a resilient
    Target into the artifact.
  * replay-time — resolve a compiled Target's ordered strategies, with the
    post-resolution expect() self-check, and evaluate Checkpoints.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from cua.schema import Checkpoint, LocatorStrategy, Target


class LocatorError(RuntimeError):
    """Raised when no strategy can resolve an element."""


@dataclass
class Perception:
    """What the agent sees on the current screen."""

    url: str
    tree: str                      # accessibility-tree text (roles + names) for the LLM
    title: str | None = None

    def render(self) -> str:
        head = f"URL: {self.url}"
        if self.title:
            head += f"\nTITLE: {self.title}"
        return f"{head}\n{self.tree}"


@dataclass
class ActResult:
    """Outcome of one discovery-time action."""

    strategies: list[LocatorStrategy] = field(default_factory=list)
    value: str | None = None       # for read actions


class Surface(ABC):
    """Perceive/act interface. Implementations own a live session."""

    # ---- lifecycle ----
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def navigate(self, url: str) -> None: ...

    @abstractmethod
    def observe(self) -> Perception: ...

    # ---- discovery-time: act by description, report strategies for the compiler ----
    @abstractmethod
    def do_click(self, description: str) -> ActResult: ...

    @abstractmethod
    def do_type(self, description: str, text: str) -> ActResult: ...

    @abstractmethod
    def do_select(self, description: str, value: str) -> ActResult: ...

    @abstractmethod
    def do_read(self, description: str) -> ActResult: ...

    # ---- replay-time: resolve a compiled Target + evaluate checkpoints ----
    @abstractmethod
    def resolve(self, target: Target): ...

    @abstractmethod
    def read_target(self, target: Target) -> str: ...

    @abstractmethod
    def check(self, checkpoint: Checkpoint) -> bool: ...

    # ---- replay-time acting on a compiled Target ----
    @abstractmethod
    def type_into(self, target: Target, text: str) -> None: ...

    @abstractmethod
    def click_target(self, target: Target) -> None: ...

    @abstractmethod
    def select_in(self, target: Target, value: str) -> None: ...

    @abstractmethod
    def read_value(self, target: Target) -> str: ...

    @abstractmethod
    def screenshot(self, path: str) -> None: ...

    @abstractmethod
    def current_url(self) -> str: ...

    def settle(self) -> None:
        """Wait for the page to be ready after an action. No-op by default."""
        return None

    def reload(self) -> None:
        """Reload the current page."""
        self.navigate(self.current_url())

    # ---- context manager sugar ----
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()
