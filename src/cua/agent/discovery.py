"""P1 — the discovery agent loop.

observe (accessibility tree) -> LLM decides ONE act() -> execute on the surface
-> record (action + the strategies that worked) -> repeat until finish.

The LLM drives with concrete input *values* (it's accomplishing a real goal for a
real member); the compiler later maps those values back to named params. The loop
is model-agnostic: hand it a NemotronLLM for real discovery or a MockLLM for a
deterministic, no-key run.
"""
from cua.llm import ACT_TOOL, LLM
from cua.schema import ActionType
from cua.surface import Surface

from .trace import DiscoveryTrace, TraceStep

SYSTEM_PROMPT = (
    "You are a careful automation agent operating a legacy web application through its "
    "accessibility tree. Accomplish the GOAL by emitting exactly ONE act() tool call per turn.\n"
    "Rules:\n"
    "- Use the exact accessible names from the observation as `target`.\n"
    "- To enter a value, use action='type' with the value from INPUTS.\n"
    "- To capture a requested result, use action='read' with an output_key naming it.\n"
    "- Only act on elements present in the current observation; never invent names.\n"
    "- Confirm you are on the expected screen before finishing.\n"
    "- When the GOAL is fully accomplished, call act(action='finish')."
)


def render_observation(goal: str, inputs: dict[str, str], perception) -> str:
    lines = [f"GOAL: {goal}"]
    if inputs:
        lines.append("INPUTS: " + ", ".join(f"{k}={v}" for k, v in inputs.items()))
    lines.append(perception.render())
    return "\n".join(lines)


class DiscoveryAgent:
    def __init__(self, surface: Surface, llm: LLM, max_steps: int = 12):
        self.surface = surface
        self.llm = llm
        self.max_steps = max_steps

    def discover(self, goal: str, start_url: str, inputs: dict[str, str] | None = None,
                 app: str | None = None) -> DiscoveryTrace:
        inputs = inputs or {}
        self.llm.start(SYSTEM_PROMPT, [ACT_TOOL])
        self.surface.navigate(start_url)

        steps: list[TraceStep] = []
        outputs: dict[str, str] = {}
        success = False

        for i in range(self.max_steps):
            perc = self.surface.observe()
            action = self.llm.next_action(render_observation(goal, inputs, perc))

            if action.action == ActionType.FINISH:
                success = True
                break

            try:
                strategies, value, result_text = self._execute(action)
                self.surface.settle()
            except Exception as e:  # noqa: BLE001 - surface failures feed back to the model
                strategies, value, result_text = [], None, f"ERROR: {e}"

            if action.action == ActionType.READ and action.output_key and value is not None:
                outputs[action.output_key] = value

            steps.append(TraceStep(
                index=i,
                action=action,
                strategies=strategies,
                url_before=perc.url,
                url_after=self.surface.current_url(),
                observation=perc.tree,
                read_value=value,
                note=result_text if result_text.startswith("ERROR") else None,
            ))
            self.llm.record_result(result_text)

        return DiscoveryTrace(
            goal=goal, app=app, model=getattr(self.llm, "model", "mock"),
            start_url=start_url, inputs=inputs,
            steps=steps, outputs=outputs, success=success,
        )

    def _execute(self, action):
        a = action.action
        s = self.surface
        if a == ActionType.NAVIGATE:
            s.navigate(action.url or "")
            return [], None, f"Navigated to {action.url}"
        if a == ActionType.TYPE:
            r = s.do_type(action.target, action.text or "")
            return r.strategies, None, f"Typed into '{action.target}'"
        if a == ActionType.CLICK:
            r = s.do_click(action.target)
            return r.strategies, None, f"Clicked '{action.target}'"
        if a == ActionType.SELECT:
            r = s.do_select(action.target, action.text or "")
            return r.strategies, None, f"Selected '{action.text}' in '{action.target}'"
        if a == ActionType.READ:
            r = s.do_read(action.target)
            return r.strategies, r.value, f"Read '{action.target}' = {r.value!r}"
        return [], None, f"ERROR: unknown action {a}"
