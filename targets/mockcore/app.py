"""
MockCore — a deliberately *legacy* back-office banking app.

This is a stand-in for the kind of internal servicing tool a US bank/credit union
runs: server-rendered HTML, table-based layout, generic class names, and NO
`data-testid` / stable selectors. It exists to exercise the interesting parts of a
computer-use system:

  * a non-trivial multi-step flow:  search -> detail -> (risky) action -> confirm
  * *business outcomes* that are legitimate answers, not crashes (record not found,
    permission denied)
  * *runtime conditions* that a robust replay must survive (validation errors, an
    unexpected interstitial dialog, session timeout, transient slowness)
  * synthetic "PII" on screen (a fake SSN) so the redaction layer has something real
    to scrub.

Everything here is fake. There are no real credentials and no real PII.

Runtime failures are injected out-of-band via an in-memory scenario, so the *same
URL* can succeed or fail depending on server state — which mirrors reality (a runtime
condition, not a layout change). Set it with:

    POST /__control   {"scenario": "normal|slow|interstitial|timeout|validation|permission"}

or per-request with `?inject=<scenario>`.

Run:
    pip install flask
    python targets/mockcore/app.py          # -> http://127.0.0.1:5001
"""
from __future__ import annotations

import time
import uuid
from flask import Flask, request, redirect, url_for, make_response, g

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# Synthetic data. All names, balances, and the "SSN" are made up.             #
# --------------------------------------------------------------------------- #
MEMBERS = {
    "12345": {
        "name": "Jordan Rivera",
        "status": "Active",
        "savings_balance": "4,210.55",
        "checking_balance": "1,002.13",
        "ssn": "412-55-9832",          # fake — used to prove redaction
        "joined": "2019-03-14",
    },
    "67890": {
        "name": "Morgan Patel",
        "status": "Active",
        "savings_balance": "15,230.10",
        "checking_balance": "440.00",
        "ssn": "233-19-7745",          # fake
        "joined": "2021-11-02",
    },
    "22222": {
        "name": "Casey Nguyen",
        "status": "Restricted",        # triggers a permission outcome on risky actions
        "savings_balance": "88.00",
        "checking_balance": "0.00",
        "ssn": "551-40-1290",          # fake
        "joined": "2023-07-22",
    },
}

# In-memory injected scenario (test hook). Not how a real app works — a convenience
# so we can deterministically drive exceptional states for the replay evidence.
# `timeout_at`: when the timeout scenario was switched on. Sessions issued before it
# are expired; signing in again issues a fresh one — like a real session timeout.
STATE = {"scenario": "normal", "timeout_at": 0.0}

VALID_SCENARIOS = {
    "normal", "slow", "interstitial", "timeout", "validation", "permission",
}


def current_scenario() -> str:
    """Per-request override (?inject=) wins over the persisted scenario."""
    inject = request.args.get("inject")
    if inject in VALID_SCENARIOS:
        return inject
    return STATE["scenario"]


# --------------------------------------------------------------------------- #
# Layout helpers — intentionally ugly, table-based, no test ids.              #
# --------------------------------------------------------------------------- #
def page(title: str, body: str) -> str:
    # Legacy chrome: framing table, <font> tags, inline styles, generic classes.
    return f"""<!doctype html>
<html><head><title>{title} - MidStates Core</title>
<style>
  body {{ font-family: Verdana, Arial, sans-serif; font-size: 12px; background:#e8ecf0; margin:0; }}
  table {{ border-collapse: collapse; }}
  .hdr {{ background:#1f3a5f; color:#fff; }}
  .hdr td {{ padding:6px 12px; }}
  .nav td {{ background:#c9d4e0; padding:4px 10px; border-right:1px solid #97a; }}
  .panel {{ background:#fff; border:1px solid #99a; margin:12px; }}
  .panel td {{ padding:4px 8px; }}
  .lbl {{ color:#334; font-weight:bold; background:#eef2f6; }}
  .fld {{ border:1px solid #778; padding:2px; font-family:inherit; font-size:12px; }}
  .btn {{ background:#1f3a5f; color:#fff; border:1px solid #12233a; padding:3px 14px; cursor:pointer; }}
  .warn {{ color:#a40000; font-weight:bold; }}
  .ok {{ color:#0a6b2f; font-weight:bold; }}
</style></head>
<body>
<table width="100%" class="hdr"><tr>
  <td><b>MidStates Core</b> &nbsp; <font size="1">Back-Office Servicing Console</font></td>
  <td align="right"><font size="1">Operator: svc_agent01 &nbsp; | &nbsp; Session active</font></td>
</tr></table>
<table width="100%" class="nav"><tr>
  <td><a href="/">Home</a></td>
  <td><a href="/members">Member Lookup</a></td>
  <td><a href="/">Transactions</a></td>
  <td><a href="/">Admin</a></td>
</tr></table>
{body}
<table width="100%"><tr><td align="center">
  <font size="1" color="#889">MidStates Core v7.2.1 (build 20180921) — internal use only — synthetic demo data</font>
</td></tr></table>
</body></html>"""


def interstitial_page(mid: str) -> str:
    """An unexpected 'System Notice' that must be dismissed to proceed (recoverable).

    The acknowledge form carries the member id as a hidden field so a GET submit
    preserves it — a bare query string on the form `action` is dropped by the browser.
    """
    body = f"""
<table class="panel" width="520" align="center" style="margin-top:60px;">
  <tr class="hdr"><td colspan="2"><b>System Notice</b></td></tr>
  <tr><td colspan="2" style="padding:16px;">
      Scheduled maintenance window notification. Some services may respond slowly.
      Please acknowledge to continue to your requested page.
  </td></tr>
  <tr><td colspan="2" align="right" style="padding:12px;">
      <form method="get" action="/members/detail" style="display:inline;">
        <input type="hidden" name="mid" value="{mid}">
        <input type="submit" class="btn" value="Acknowledge &amp; Continue">
      </form>
  </td></tr>
</table>"""
    return page("System Notice", body)


def expired_page() -> str:
    body = """
<table class="panel" width="420" align="center" style="margin-top:60px;">
  <tr class="hdr"><td><b>Session Expired</b></td></tr>
  <tr><td style="padding:16px;">
     <span class="warn">Your session has timed out due to inactivity.</span><br><br>
     Please sign in again to continue.<br><br>
     <form method="get" action="/signin"><input type="submit" class="btn" value="Return to Sign In"></form>
  </td></tr>
</table>"""
    return page("Session Expired", body)


# --------------------------------------------------------------------------- #
# Cross-cutting request handling: session + injected slowness/timeout.        #
# --------------------------------------------------------------------------- #
PROTECTED = ("/members",)


def _session_valid() -> bool:
    """A session (cookie `sid` = '<random>.<issued-at>') is valid if issued after the timeout."""
    try:
        issued = float(request.cookies.get("sid", "").split(".", 1)[1])
    except (IndexError, ValueError):
        return False
    return issued > STATE["timeout_at"]


@app.before_request
def _apply_scenario():
    scenario = current_scenario()

    # transient slowness on any protected page
    if scenario == "slow" and request.path.startswith(PROTECTED):
        time.sleep(3)

    # session timeout: protected routes need a session issued after the timeout began
    if scenario == "timeout" and request.path.startswith(PROTECTED) and not _session_valid():
        g.force_expired = True


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    resp = make_response(page("Home", """
<table class="panel" width="620" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Welcome to MidStates Core</b></td></tr>
  <tr><td style="padding:16px;">
    Use <a href="/members">Member Lookup</a> to service a member account.<br><br>
    <font size="1" color="#667">This is a synthetic training/demo environment.</font>
  </td></tr>
</table>"""))
    return resp


def signin_page(error: str = "") -> str:
    # A password field on purpose: credentials are exactly what an agent must never
    # handle, so an expired session is a job for a human operator.
    warn = f'<span class="warn">{error}</span><br><br>' if error else ""
    body = f"""
<table class="panel" width="420" align="center" style="margin-top:60px;">
  <tr class="hdr"><td><b>Operator Sign In</b></td></tr>
  <tr><td style="padding:16px;">
    {warn}
    <form method="post" action="/signin">
      <table>
        <tr><td class="lbl">Operator ID</td>
            <td><input type="text" name="operator" class="fld" size="20" placeholder="Operator ID"></td></tr>
        <tr><td class="lbl">Password</td>
            <td><input type="password" name="password" class="fld" size="20" placeholder="Password"></td></tr>
        <tr><td></td><td style="padding-top:8px;"><input type="submit" class="btn" value="Sign In"></td></tr>
      </table>
    </form>
  </td></tr>
</table>"""
    return page("Sign In", body)


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return signin_page()
    # Synthetic environment: any non-empty operator id + password signs in. Never log them.
    if not (request.form.get("operator") or "").strip() or not request.form.get("password"):
        return signin_page("Operator ID and password are required.")
    resp = redirect(url_for("member_search"))
    resp.set_cookie("sid", f"{uuid.uuid4().hex}.{time.time()}", httponly=True, samesite="Lax")
    return resp


@app.route("/members")
def member_search():
    if getattr(g, "force_expired", False):
        return expired_page()
    # Note: input has a placeholder (its accessible name) but NO id/testid, and the
    # label is a sibling table cell with no `for=` association. This forces a locator
    # strategy beyond "click the id".
    body = """
<table class="panel" width="620" align="center" style="margin-top:24px;">
  <tr class="hdr"><td colspan="2"><b>Member Lookup</b></td></tr>
  <tr><td colspan="2" style="padding:10px;">
    <form method="post" action="/members/lookup">
      <table>
        <tr>
          <td class="lbl">Member ID</td>
          <td><input type="text" name="mid" class="fld" size="20" placeholder="Member ID"></td>
        </tr>
        <tr>
          <td></td>
          <td style="padding-top:8px;"><input type="submit" class="btn" value="Search"></td>
        </tr>
      </table>
    </form>
  </td></tr>
</table>"""
    return page("Member Lookup", body)


@app.route("/members/lookup", methods=["POST"])
def member_lookup():
    if getattr(g, "force_expired", False):
        return expired_page()

    scenario = current_scenario()
    mid = (request.form.get("mid") or "").strip()

    # Unexpected interstitial before we can show the detail (recoverable condition).
    if scenario == "interstitial":
        return interstitial_page(mid)

    return _render_detail(mid)


@app.route("/members/detail")
def member_detail_get():
    # Used when returning from the interstitial (GET with mid in query).
    if getattr(g, "force_expired", False):
        return expired_page()
    mid = (request.args.get("mid") or "").strip()
    return _render_detail(mid)


def _render_detail(mid: str) -> str:
    member = MEMBERS.get(mid)

    # BUSINESS OUTCOME: not found is a legitimate answer, returned with HTTP 200 and
    # only distinguishable by reading the screen — you cannot rely on a 404 here.
    if member is None:
        body = f"""
<table class="panel" width="620" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Member Lookup</b></td></tr>
  <tr><td style="padding:16px;">
     <span class="warn">No record found for member ID "{mid}".</span><br><br>
     <a href="/members">Back to search</a>
  </td></tr>
</table>"""
        return page("Not Found", body)

    # Detail screen — savings balance lives inside a nested table with generic markup.
    body = f"""
<table class="panel" width="720" align="center" style="margin-top:24px;">
  <tr class="hdr"><td colspan="2"><b>Member Detail</b></td></tr>
  <tr><td style="padding:12px;" colspan="2">
    <table width="100%">
      <tr><td class="lbl" width="180">Member ID</td><td>{mid}</td></tr>
      <tr><td class="lbl">Name</td><td>{member['name']}</td></tr>
      <tr><td class="lbl">Status</td><td>{member['status']}</td></tr>
      <tr><td class="lbl">Tax ID (SSN)</td><td>{member['ssn']}</td></tr>
      <tr><td class="lbl">Member Since</td><td>{member['joined']}</td></tr>
      <tr><td class="lbl" valign="top">Balances</td>
          <td>
            <table border="1" cellpadding="3" style="border-color:#ccd;">
              <tr class="lbl"><td>Product</td><td>Balance</td></tr>
              <tr><td>Savings</td><td>${member['savings_balance']}</td></tr>
              <tr><td>Checking</td><td>${member['checking_balance']}</td></tr>
            </table>
          </td></tr>
    </table>
    <br>
    <form method="get" action="/members/subaccount/new">
      <input type="hidden" name="mid" value="{mid}">
      <input type="submit" class="btn" value="Open Sub-Account">
    </form>
  </td></tr>
</table>"""
    return page("Member Detail", body)


@app.route("/members/subaccount/new")
def subaccount_new():
    if getattr(g, "force_expired", False):
        return expired_page()
    mid = (request.args.get("mid") or "").strip()
    member = MEMBERS.get(mid)
    if member is None:
        return _render_detail(mid)  # falls through to not-found

    # RISKY / IRREVERSIBLE action form. Labels are sibling cells (weak association);
    # the select and inputs have name attrs but no ids.
    body = f"""
<table class="panel" width="640" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Open Sub-Account &mdash; {member['name']} ({mid})</b></td></tr>
  <tr><td style="padding:12px;">
    <form method="post" action="/members/subaccount/create">
      <input type="hidden" name="mid" value="{mid}">
      <table>
        <tr><td class="lbl">Account Type</td>
            <td><select name="acct_type" class="fld">
                  <option value="">-- select --</option>
                  <option value="savings">Savings</option>
                  <option value="money_market">Money Market</option>
                  <option value="cd">Certificate of Deposit</option>
                </select></td></tr>
        <tr><td class="lbl">Initial Deposit (USD)</td>
            <td><input type="text" name="deposit" class="fld" size="14" placeholder="0.00"></td></tr>
        <tr><td class="lbl">Nickname</td>
            <td><input type="text" name="nickname" class="fld" size="24" placeholder="e.g. Vacation Fund"></td></tr>
        <tr><td></td><td style="padding-top:10px;">
            <input type="submit" class="btn" value="Create Sub-Account"></td></tr>
      </table>
    </form>
  </td></tr>
</table>"""
    return page("Open Sub-Account", body)


@app.route("/members/subaccount/create", methods=["POST"])
def subaccount_create():
    if getattr(g, "force_expired", False):
        return expired_page()

    scenario = current_scenario()
    mid = (request.form.get("mid") or "").strip()
    member = MEMBERS.get(mid)
    if member is None:
        return _render_detail(mid)

    acct_type = (request.form.get("acct_type") or "").strip()
    deposit = (request.form.get("deposit") or "").strip()
    nickname = (request.form.get("nickname") or "").strip()

    # PERMISSION outcome: restricted members can't open sub-accounts.
    if scenario == "permission" or member["status"] == "Restricted":
        body = f"""
<table class="panel" width="620" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Open Sub-Account</b></td></tr>
  <tr><td style="padding:16px;">
     <span class="warn">Permission denied: member status "{member['status']}" is not eligible
     for new sub-accounts. Contact a supervisor.</span><br><br>
     <a href="/members/subaccount/new?mid={mid}">Back</a>
  </td></tr>
</table>"""
        return page("Permission Denied", body)

    # VALIDATION error: deposit must be numeric and >= 50.
    def _invalid_deposit() -> bool:
        try:
            return float(deposit.replace(",", "")) < 50
        except ValueError:
            return True

    if scenario == "validation" or not acct_type or _invalid_deposit():
        msg = "Please correct the following:"
        errs = []
        if not acct_type:
            errs.append("Account Type is required.")
        if _invalid_deposit():
            errs.append("Initial Deposit must be a number of at least $50.00.")
        if scenario == "validation" and not errs:
            errs.append("Initial Deposit must be a number of at least $50.00.")
        body = f"""
<table class="panel" width="640" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Open Sub-Account</b></td></tr>
  <tr><td style="padding:16px;">
     <span class="warn">{msg}</span>
     <ul>{''.join(f'<li>{e}</li>' for e in errs)}</ul>
     <a href="/members/subaccount/new?mid={mid}">Back to form</a>
  </td></tr>
</table>"""
        return page("Validation Error", body)

    # SUCCESS: confirmation screen with a generated sub-account number.
    sub_no = "SA-" + uuid.uuid4().hex[:8].upper()
    body = f"""
<table class="panel" width="660" align="center" style="margin-top:24px;">
  <tr class="hdr"><td><b>Sub-Account Created</b></td></tr>
  <tr><td style="padding:16px;">
     <span class="ok">Success.</span> A new sub-account has been opened.
     <table style="margin-top:10px;">
       <tr><td class="lbl" width="180">Member</td><td>{member['name']} ({mid})</td></tr>
       <tr><td class="lbl">Sub-Account Number</td><td>{sub_no}</td></tr>
       <tr><td class="lbl">Type</td><td>{acct_type}</td></tr>
       <tr><td class="lbl">Initial Deposit</td><td>${deposit}</td></tr>
       <tr><td class="lbl">Nickname</td><td>{nickname or '(none)'}</td></tr>
     </table>
  </td></tr>
</table>"""
    return page("Confirmation", body)


# --------------------------------------------------------------------------- #
# Test hook: set the injected scenario out-of-band.                           #
# --------------------------------------------------------------------------- #
@app.route("/__control", methods=["GET", "POST"])
def control():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        scenario = (data.get("scenario") or "normal").strip()
        if scenario not in VALID_SCENARIOS:
            return {"error": f"unknown scenario '{scenario}'",
                    "valid": sorted(VALID_SCENARIOS)}, 400
        STATE["scenario"] = scenario
        if scenario == "timeout":
            STATE["timeout_at"] = time.time()  # every session issued before now is expired
        return {"scenario": STATE["scenario"]}
    return {"scenario": STATE["scenario"], "valid": sorted(VALID_SCENARIOS)}


if __name__ == "__main__":
    print("MockCore legacy bank app -> http://127.0.0.1:5001")
    print("Members: 12345 (Active), 67890 (Active), 22222 (Restricted). Unknown ids -> not found.")
    app.run(host="127.0.0.1", port=5001, debug=False)
