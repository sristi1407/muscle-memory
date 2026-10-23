"""Unit tests for the evidence recorder (no browser needed)."""
import json
import os

from cua.evidence import EvidenceRecorder, NullRecorder
from cua.policy import Redactor
from cua.surface import Perception

SSN = "412-55-9832"


class FakeSurface:
    """Just enough surface for the recorder: writes a fake PNG and returns a raw tree."""

    def __init__(self, fail_screenshot: bool = False):
        self.fail_screenshot = fail_screenshot

    def screenshot(self, path: str) -> None:
        if self.fail_screenshot:
            raise RuntimeError("browser crashed")
        with open(path, "wb") as f:
            f.write(b"\x89PNG fake")

    def observe(self) -> Perception:
        # Deliberately UNredacted, to prove the recorder scrubs on its own.
        return Perception(url="http://127.0.0.1:5001/members/detail",
                          tree=f'- cell "Tax ID (SSN)"\n- cell "{SSN}"', title="Member Detail")


def read_log(rec: EvidenceRecorder) -> list[dict]:
    with open(rec.log_path) as f:
        return [json.loads(line) for line in f]


def test_events_are_ordered_jsonl(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "replay", "abc123")
    rec.event("run_start", capability_id="member.lookup_savings")
    rec.event("step_result", step_id="s1", status="ok")
    events = read_log(rec)
    assert [e["event"] for e in events] == ["run_start", "step_result"]
    assert [e["seq"] for e in events] == [1, 2]
    assert all("ts" in e for e in events)
    assert rec.dir.endswith("replay-abc123")


def test_pii_never_reaches_the_log(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "discovery")
    rec.event("decision", observation=f'cell "{SSN}"', nested={"list": [f"ssn {SSN}"]})
    raw = open(rec.log_path).read()
    assert SSN not in raw
    assert "[REDACTED:SSN]" in raw


def test_declared_sensitive_values_are_masked(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "replay", redactor=Redactor(sensitive_values=["s3cr3t"]))
    rec.event("run_start", params={"token": "s3cr3t"})
    assert "s3cr3t" not in open(rec.log_path).read()


def test_failure_snapshot_is_rich_and_redacted(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "replay")
    path = rec.failure_snapshot(FakeSurface(), step_id="s2", expected="detail page", observed="expired")
    snap = json.load(open(path))
    assert snap["step_id"] == "s2"
    assert snap["url"].endswith("/members/detail")
    assert "accessibility_tree" in snap
    assert os.path.exists(snap["screenshot"])
    assert SSN not in open(path).read()


def test_screenshot_failure_never_breaks_a_run(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "replay")
    assert rec.screenshot(FakeSurface(fail_screenshot=True), "step-01") is None
    assert read_log(rec)[-1]["event"] == "screenshot_failed"


def test_finish_returns_evidence_and_writes_summary(tmp_path):
    rec = EvidenceRecorder(str(tmp_path), "replay")
    rec.screenshot(FakeSurface(), "step-01")
    evidence = rec.finish(status="success")
    assert evidence.log_ref == rec.log_path
    assert len(evidence.screenshots) == 1
    summary = json.load(open(os.path.join(rec.dir, "summary.json")))
    assert summary["status"] == "success"


def test_null_recorder_writes_nothing(tmp_path):
    rec = NullRecorder()
    rec.event("run_start")
    assert rec.screenshot(FakeSurface(), "x") is None
    assert rec.finish() is None
    assert list(tmp_path.iterdir()) == []
