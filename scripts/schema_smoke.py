"""Smoke test: hand-build the target Capability + a ReplayResult and print them.

This validates the schema and shows the *exact* artifact shape the compiler will
produce later. Run after `pip install -e .`:

    python scripts/schema_smoke.py
"""
from cua.schema import (
    Capability, Metadata, Surface, Contract, IOField,
    Step, Target, Locator, LocatorKind, CapabilityPolicy, Provenance,
    ActionType, ReplayResult, Outcome,
)

cap = Capability(
    metadata=Metadata(id="member.lookup_savings", app="MidStates Core", surface=Surface.WEB_LEGACY),
    goal="Look up a member by ID and read their savings balance.",
    contract=Contract(
        inputs=[IOField(name="member_id", description="Member ID to look up")],
        outputs=[IOField(name="savings_balance", description="Savings balance on the detail screen")],
        success_condition="Member detail screen shows a savings balance.",
    ),
    steps=[
        Step(index=0, action=ActionType.NAVIGATE, url="http://127.0.0.1:5001/members"),
        Step(
            index=1, action=ActionType.TYPE, text_template="{member_id}",
            target=Target(
                description="Member ID",
                locators=[
                    Locator(kind=LocatorKind.PLACEHOLDER, value="Member ID"),
                    Locator(kind=LocatorKind.ROLE, role="textbox", value="Member ID"),
                ],
            ),
        ),
        Step(
            index=2, action=ActionType.CLICK,
            target=Target(
                description="Search",
                locators=[Locator(kind=LocatorKind.ROLE, role="button", value="Search")],
            ),
        ),
        Step(
            index=3, action=ActionType.READ, output_key="savings_balance",
            target=Target(
                description="Savings balance",
                locators=[Locator(kind=LocatorKind.TEXT, value="Savings")],
                expect_text="Savings",
            ),
        ),
    ],
    policy=CapabilityPolicy(allowlist_domains=["127.0.0.1"]),
    provenance=Provenance(discovery_run_id="demo-0001", model="nvidia/Nemotron-3-Ultra-550b-a55b"),
)

print("=== CAPABILITY ===")
print(cap.model_dump_json(indent=2))

# Round-trip check: JSON -> back into a Capability.
Capability.model_validate_json(cap.model_dump_json())
print("\n[ok] Capability round-trips through JSON.")

res = ReplayResult(
    outcome=Outcome.BUSINESS_OUTCOME,
    capability_id=cap.metadata.id,
    capability_version=cap.metadata.version,
    run_id="replay-0002",
    business_outcome="member_not_found",
)
print("\n=== EXAMPLE REPLAY RESULT (business outcome) ===")
print(res.model_dump_json(indent=2))
