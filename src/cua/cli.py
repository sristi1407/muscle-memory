"""Command line: discover a capability from a goal, then replay it.

  muscle-memory discover --goal "Look up member 12345 and read their savings balance." \
      --start http://127.0.0.1:5001/members --input member_id=12345 --id member.lookup_savings
  muscle-memory replay capabilities/member.lookup_savings.json --param member_id=67890
  muscle-memory replay capabilities/member.lookup_savings.json --param member_id=12345 --console
  muscle-memory scenario timeout

(`python -m cua ...` works too.) Replay exits 0 on success, 2 on a business outcome,
1 on failure, so a calling script can branch on the three-way result.
"""
import argparse
import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

EXIT = {"success": 0, "business_outcome": 2, "failure": 1}


def _pairs(items: list[str] | None, flag: str) -> dict[str, str]:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            sys.exit(f"{flag} expects key=value, got '{item}'")
        out[key] = value
    return out


def _sample_llm(inputs: dict[str, str]):
    """The recorded decision sequence for the sample goal, so discovery runs with no key."""
    from cua.llm import MockLLM
    from cua.schema import Action, ActionType

    return MockLLM([
        Action(action=ActionType.TYPE, target="Member ID", text=inputs.get("member_id", "12345"),
               reason="enter the member id"),
        Action(action=ActionType.CLICK, target="Search", reason="submit the search"),
        Action(action=ActionType.READ, target="Savings", output_key="savings_balance",
               reason="read the savings balance from the detail screen"),
        Action(action=ActionType.FINISH, reason="balance captured; goal complete"),
    ])


def cmd_discover(args) -> int:
    from cua.agent import DiscoveryAgent
    from cua.compiler import attach_lookup_error_rules, compile_trace, save_capability
    from cua.llm import NANO, SUPER, ULTRA, NemotronLLM
    from cua.surface import PlaywrightWebSurface

    inputs = _pairs(args.input, "--input")
    if args.mock or not os.environ.get("NEBIUS_API_KEY"):
        if not args.mock:
            print("[no NEBIUS_API_KEY: using the recorded decision sequence for the sample goal]")
        llm = _sample_llm(inputs)
    else:
        llm = NemotronLLM(model={"ultra": ULTRA, "super": SUPER, "nano": NANO}[args.model])
    print(f"[discovery model: {getattr(llm, 'model', 'mock')}]")

    with PlaywrightWebSurface(headless=not args.headful) as surface:
        trace = DiscoveryAgent(surface, llm, max_steps=args.max_steps,
                               evidence_root=args.evidence).discover(
            args.goal, args.start, inputs, app=args.app)

    print(f"evidence -> {trace.evidence_ref}")
    if not trace.success:
        print(f"discovery did not reach the goal in {args.max_steps} steps; no capability saved")
        return 1

    cap = compile_trace(trace, capability_id=args.id, name=args.name, description=args.goal)
    if not args.no_app_rules:
        attach_lookup_error_rules(cap)  # what we know about MockCore: not-found, notices, session expiry
    path = save_capability(cap, args.out)
    print(f"discovered {len(cap.steps)} steps; outputs {trace.outputs}")
    print(f"capability -> {path}")
    return 0


def cmd_replay(args) -> int:
    from cua.compiler import load_capability
    from cua.escalation import ControlChannel, OperatorConsole
    from cua.replay import ReplayEngine
    from cua.surface import PlaywrightWebSurface

    cap = load_capability(args.artifact)
    params = _pairs(args.param, "--param")
    missing = [p.name for p in cap.contract.inputs if p.required and p.name not in params]
    if missing:
        sys.exit(f"missing required --param for: {', '.join(missing)}")

    channel = ControlChannel() if args.console else None
    console = OperatorConsole(channel, port=args.console_port).start() if channel else None
    if console:
        print(f"operator console -> {console.url}  (a human can take over here if replay gets stuck)")
    try:
        with PlaywrightWebSurface(headless=not args.headful) as surface:
            res = ReplayEngine(surface, evidence_root=args.evidence, control=channel).replay(cap, params)
    finally:
        if console:
            console.stop()

    if args.json:
        print(res.model_dump_json(indent=2))
    else:
        print(f"{res.status.value.upper()}  {res.capability_id} v{res.capability_version}  run {res.run_id}")
        if res.outputs:
            print(f"  outputs: {json.dumps(res.outputs)}")
        if res.business_outcome:
            print(f"  business outcome: {res.business_outcome.code} — {res.business_outcome.message}")
        if res.failure:
            f = res.failure
            print(f"  failed at {f.step_id}: {f.code or f.error_class} — {f.observed}")
            print(f"  failure snapshot: {f.evidence_ref}")
        for iv in res.interventions:
            print(f"  handoff {iv.id}: {iv.reason} -> {iv.resolution.value} by {iv.operator} "
                  f"({len(iv.actions)} human actions)")
        if res.evidence:
            print(f"  evidence: {res.evidence.log_ref}")
    return EXIT[res.status.value]


def cmd_scenario(args) -> int:
    req = urllib.request.Request(
        f"{args.mockcore}/__control", data=json.dumps({"scenario": args.name}).encode(),
        headers={"content-type": "application/json"}, method="POST",
    )
    print(urllib.request.urlopen(req, timeout=5).read().decode().strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="muscle-memory",
                                description="Discover once with an LLM, replay free and deterministically.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="drive the app with Nemotron to reach a goal; save a capability")
    d.add_argument("--goal", required=True, help="what to accomplish, in plain language")
    d.add_argument("--start", required=True, help="URL to start from")
    d.add_argument("--input", action="append", metavar="NAME=VALUE",
                   help="a concrete input value for this run; becomes a typed capability input")
    d.add_argument("--id", required=True, help="capability id, e.g. member.lookup_savings")
    d.add_argument("--name", help="human-readable capability name")
    d.add_argument("--app", default="MidStates Core", help="application name for the metadata")
    d.add_argument("--out", default="capabilities", help="directory to save the capability in")
    d.add_argument("--evidence", default="evidence/_runs", help="where to write the run's evidence")
    d.add_argument("--model", choices=["ultra", "super", "nano"], default="ultra")
    d.add_argument("--max-steps", type=int, default=12)
    d.add_argument("--mock", action="store_true",
                   help="use the recorded decisions for the sample goal instead of a live model")
    d.add_argument("--no-app-rules", action="store_true",
                   help="don't attach MockCore's known error rules (not-found, notices, session expiry)")
    d.add_argument("--headful", action="store_true", help="show the browser")
    d.set_defaults(func=cmd_discover)

    r = sub.add_parser("replay", help="run a saved capability with new inputs — no LLM involved")
    r.add_argument("artifact", help="path to a capability JSON file")
    r.add_argument("--param", action="append", metavar="NAME=VALUE", help="a capability input")
    r.add_argument("--console", action="store_true",
                   help="start the operator console so a human can take over if replay gets stuck")
    r.add_argument("--console-port", type=int, default=5050)
    r.add_argument("--evidence", default="evidence/_runs", help="where to write the run's evidence")
    r.add_argument("--json", action="store_true", help="print the full ReplayResult a calling agent gets")
    r.add_argument("--headful", action="store_true", help="show the browser")
    r.set_defaults(func=cmd_replay)

    s = sub.add_parser("scenario", help="switch MockCore's injected runtime condition (demo helper)")
    s.add_argument("name", choices=["normal", "slow", "interstitial", "timeout", "validation", "permission"])
    s.add_argument("--mockcore", default="http://127.0.0.1:5001")
    s.set_defaults(func=cmd_scenario)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
