"""Playwright web Surface: perceive via the accessibility tree, act on the page.

Perception is accessibility-first (roles + names) because that's more stable than
CSS *and* it generalizes to desktop accessibility trees later. Discovery-time
resolution tries strategies in priority order and reports which ones uniquely
located the element, so the compiler can store resilient fallbacks.
"""
import re

from playwright.sync_api import sync_playwright

from cua.schema import (
    CssStrategy,
    ElementVisible,
    LabelStrategy,
    PlaceholderStrategy,
    RoleStrategy,
    TextAbsent,
    TextPresent,
    TextStrategy,
    UrlMatches,
    ValueEquals,
)

from .base import ActResult, LocatorError, Perception, Surface

# Roles tried (in order) when resolving an element by its accessible name.
ROLE_PRIORITY = [
    "textbox", "button", "link", "combobox", "checkbox",
    "radio", "option", "heading", "cell",
]


class PlaywrightWebSurface(Surface):
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self.page = None

    # ---- lifecycle ----
    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self.page = self._browser.new_page()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def navigate(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")

    def current_url(self) -> str:
        return self.page.url

    def settle(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

    def observe(self) -> Perception:
        return Perception(url=self.page.url, tree=self._ax_text(), title=self.page.title())

    def _ax_text(self) -> str:
        """Accessibility tree as compact text. Prefer aria_snapshot; fall back to a manual walk."""
        try:
            return self.page.locator("body").aria_snapshot()
        except Exception:
            snap = self.page.accessibility.snapshot() or {}
            lines: list[str] = []

            def walk(node: dict, depth: int = 0) -> None:
                role = node.get("role")
                name = node.get("name")
                if role and role not in ("generic", "none", "InlineTextBox"):
                    pad = "  " * depth
                    lines.append(f'{pad}- {role} "{name}"' if name else f"{pad}- {role}")
                for child in node.get("children", []) or []:
                    walk(child, depth + 1)

            walk(snap)
            return "\n".join(lines)

    # ---- discovery-time ----
    def _strategies_for(self, description: str):
        """Return (primary_locator, [strategies that uniquely resolve it])."""
        page = self.page
        found = []
        primary = None

        for role in ROLE_PRIORITY:
            loc = page.get_by_role(role, name=description)
            try:
                if loc.count() == 1:
                    found.append(RoleStrategy(role=role, name=description))
                    primary = primary or loc
            except Exception:
                pass

        for loc, strat in (
            (page.get_by_placeholder(description), PlaceholderStrategy(placeholder=description)),
            (page.get_by_label(description), LabelStrategy(label=description)),
        ):
            try:
                if loc.count() == 1:
                    found.append(strat)
                    primary = primary or loc
            except Exception:
                pass

        if primary is None:
            loc = page.get_by_text(description)
            try:
                if loc.count() >= 1:
                    found.append(TextStrategy(text=description))
                    primary = loc.first
            except Exception:
                pass

        if primary is None:
            raise LocatorError(f"could not locate '{description}' on {page.url}")
        return primary, found

    def do_click(self, description: str) -> ActResult:
        loc, strategies = self._strategies_for(description)
        loc.click()
        return ActResult(strategies=strategies)

    def do_type(self, description: str, text: str) -> ActResult:
        loc, strategies = self._strategies_for(description)
        loc.fill(text)
        return ActResult(strategies=strategies)

    def do_select(self, description: str, value: str) -> ActResult:
        loc, strategies = self._strategies_for(description)
        loc.select_option(value)
        return ActResult(strategies=strategies)

    def do_read(self, description: str) -> ActResult:
        value, strategies = self.read_labeled_value(description)
        return ActResult(strategies=strategies, value=value)

    def read_labeled_value(self, target_text: str):
        """Read a value shown next to a label cell, and ALWAYS anchor on the label.

        Legacy table pattern:  <td>Savings</td><td>$4,210.55</td>
          * If target_text is the LABEL ("Savings")   -> value = following sibling, anchor on label.
          * If target_text is the VALUE ("$4,210.55") -> value = itself, anchor on the PRECEDING label.
        Either way the returned strategy targets the stable label, so replay works for any member.
        """
        page = self.page
        try:
            cells = page.locator("td", has_text=re.compile(rf"^\s*{re.escape(target_text)}\s*$"))
            if cells.count() >= 1:
                first = cells.first
                # Case 1: target is a LABEL -> value is the following sibling cell.
                nxt = first.locator("xpath=following-sibling::td[1]")
                if nxt.count() >= 1:
                    val = nxt.first.inner_text().strip()
                    if val:
                        return val, [TextStrategy(text=target_text, exact=True)]
                # Case 2: target is the VALUE -> anchor on the preceding-sibling label.
                prev = first.locator("xpath=preceding-sibling::td[1]")
                if prev.count() >= 1:
                    label = prev.first.inner_text().strip()
                    if label:
                        return first.inner_text().strip(), [TextStrategy(text=label, exact=True)]
        except Exception:
            pass
        loc, strategies = self._strategies_for(target_text)
        return loc.inner_text().strip(), strategies

    # ---- replay-time ----
    def _loc_from_strategy(self, strat):
        page = self.page
        if isinstance(strat, RoleStrategy):
            if strat.name:
                return page.get_by_role(strat.role, name=strat.name, exact=strat.exact)
            return page.get_by_role(strat.role)
        if isinstance(strat, PlaceholderStrategy):
            return page.get_by_placeholder(strat.placeholder)
        if isinstance(strat, LabelStrategy):
            return page.get_by_label(strat.label)
        if isinstance(strat, TextStrategy):
            return page.get_by_text(strat.text, exact=strat.exact)
        if isinstance(strat, CssStrategy):
            return page.locator(strat.selector)
        raise LocatorError(f"unsupported strategy for resolve: {type(strat).__name__}")

    def resolve(self, target):
        last = None
        for strat in target.strategies:
            try:
                loc = self._loc_from_strategy(strat)
                if loc.count() >= 1:
                    loc = loc.first
                    if self._passes_expect(loc, target.expect):
                        return loc
            except Exception as e:  # noqa: BLE001 - try the next fallback
                last = e
        raise LocatorError(f"no strategy resolved '{target.description}' on {self.page.url}: {last}")

    def _passes_expect(self, loc, expect) -> bool:
        if expect is None:
            return True
        try:
            if expect.visible and not loc.is_visible():
                return False
            if expect.editable is not None and loc.is_editable() != expect.editable:
                return False
            if expect.text_contains and expect.text_contains not in loc.inner_text():
                return False
        except Exception:
            return False
        return True

    def read_target(self, target) -> str:
        return self.resolve(target).inner_text().strip()

    def check(self, checkpoint) -> bool:
        page = self.page
        body = page.locator("body").inner_text()
        if isinstance(checkpoint, UrlMatches):
            return re.search(checkpoint.pattern, page.url) is not None
        if isinstance(checkpoint, TextPresent):
            return checkpoint.text in body
        if isinstance(checkpoint, TextAbsent):
            return checkpoint.text not in body
        if isinstance(checkpoint, ElementVisible):
            try:
                return self.resolve(checkpoint.target).is_visible()
            except LocatorError:
                return False
        if isinstance(checkpoint, ValueEquals):
            try:
                return self.read_target(checkpoint.target) == checkpoint.equals
            except LocatorError:
                return False
        return False

    def screenshot(self, path: str) -> None:
        self.page.screenshot(path=path, full_page=True)
