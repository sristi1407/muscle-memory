"""Smoke test: hand-build the target Capability (cua.v1) + a ReplayResult and print them.

Validates the full schema — discriminated unions, parameterization, error rules —
and shows the exact artifact the compiler will produce. Run after `pip install -e .`:

    python scripts/schema_smoke.py
"""
from cua.schema import (
    CapabilityArtifact, Metadata, Surface, Contract, ParamSpec, OutputSpec,
    Step, Target, Expect, RoleStrategy, PlaceholderStrategy, TextStrategy,
    ParamValue, TextPresent, ErrorRule, ErrorClass, Policy, Provenance, ActionType,
    ReplayResult, Status, BusinessOutcome,
)

cap = CapabilityArtifact(
    id="member.lookup_savings",
    name="Look up member savings balance",
    description="Open member lookup, search by ID, and read the savings balance from the detail screen.",
    metadata=Metadata(app="MidStates Core", surface=Surface.WEB_LEGACY, author="Sristi Prasad"),
    contract=Contract(
        inputs=[ParamSpec(name="member_id", description="Member ID to look up", example="1XXXX")],
        outputs=[OutputSpec(name="savings_balance", description="Savings balance on the detail screen")],
        success=TextPresent(text="Savings", description="Detail screen shows the balances table"),
    ),
    steps=[
        Step(id="open_lookup", index=0, action=ActionType.NAVIGATE, url="http://127.0.0.1:5001/members"),
        Step(
            id="type_member_id", index=1, action=ActionType.TYPE,
            target=Target(
                description="Member ID search box",
                strategies=[
                    RoleStrategy(role="textbox", name="Member ID"),
                    PlaceholderStrategy(placeholder="Member ID"),
                ],
                expect=Expect(role="textbox", editable=True),
            ),
            value=ParamValue(param="member_id"),
        ),
        Step(
            id="click_search", index=2, action=ActionType.CLICK,
            target=Target(
                description="Search button",
                strategies=[RoleStrategy(role="button", name="Search")],
            ),
            error_rules=[
                ErrorRule(
                    when=TextPresent(text="No record found"),
                    classify=ErrorClass.BUSINESS,
                    outcome="member_not_found",
                    message="No member exists for the given ID.",
                ),
            ],
        ),
        Step(
            id="read_savings", index=3, action=ActionType.READ, output="savings_balance",
            target=Target(
                description="Savings balance cell",
                strategies=[TextStrategy(text="Savings")],
                expect=Expect(text_contains="Savings"),
            ),
            checkpoint=TextPresent(text="Member Detail"),
        ),
    ],
    policy=Policy(
        allowlist_domains=["127.0.0.1"],
        allowlist_routes=["/members", "/members/lookup", "/members/detail"],
    ),
    provenance=Provenance(discovery_run_id="demo-0001", model="nvidia/Nemotron-3-Ultra-550b-a55b"),
)

print("=== CAPABILITY ARTIFACT (cua.v1) ===")
print(cap.model_dump_json(indent=2))

# Round-trip: JSON -> back into a validated artifact (exercises the discriminated unions).
CapabilityArtifact.model_validate_json(cap.model_dump_json())
print("\n[ok] Capability round-trips through JSON.")

res = ReplayResult(
    status=Status.BUSINESS_OUTCOME,
    capability_id=cap.id,
    capability_version=cap.version,
    run_id="replay-0002",
    business_outcome=BusinessOutcome(code="member_not_found", message="No member exists for the given ID."),
)
print("\n=== EXAMPLE REPLAY RESULT (business outcome) ===")
print(res.model_dump_json(indent=2))
