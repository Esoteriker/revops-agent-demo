from __future__ import annotations

import json

try:
    from agents import function_tool
except ModuleNotFoundError:
    def function_tool(func=None, **_kwargs):
        if func is None:
            def decorator(inner):
                return inner
            return decorator
        return func

from .store import RuntimeStore


store = RuntimeStore()


async def _approval_for_outbound_email(_ctx, params, _call_id) -> bool:
    subject = str(params.get("subject", "")).lower()
    body = str(params.get("body", "")).lower()
    high_risk_terms = ("discount", "pricing", "contract", "legal", "security")
    return any(term in subject or term in body for term in high_risk_terms)


@function_tool
def lookup_account(account_name: str) -> str:
    """Look up an account and return a concise JSON summary."""
    account = store.find_account(account_name)
    if not account:
        return json.dumps({"error": f"Account '{account_name}' not found."}, indent=2)
    return json.dumps(account, indent=2)


@function_tool
def lookup_lead(account_name: str) -> str:
    """Look up the primary lead for an account and return a JSON summary."""
    lead = store.find_lead(account_name)
    if not lead:
        return json.dumps({"error": f"Lead for '{account_name}' not found."}, indent=2)
    return json.dumps(lead, indent=2)


@function_tool
def lookup_deal(account_name: str) -> str:
    """Look up the current deal for an account and return a JSON summary."""
    deal = store.find_deal(account_name)
    if not deal:
        return json.dumps({"error": f"Deal for '{account_name}' not found."}, indent=2)
    return json.dumps(deal, indent=2)


@function_tool
def score_lead(account_name: str) -> str:
    """Return a simple lead qualification summary based on the mock CRM record."""
    lead = store.find_lead(account_name)
    account = store.find_account(account_name)
    if not lead or not account:
        return json.dumps({"error": f"Could not score '{account_name}'."}, indent=2)

    score = lead["score"]
    tier_bonus = 8 if account["tier"] == "enterprise" else 4
    final_score = min(score + tier_bonus, 100)
    recommendation = "prioritize now" if final_score >= 85 else "nurture with targeted follow-up"
    summary = {
        "account_name": account_name,
        "base_score": score,
        "tier_bonus": tier_bonus,
        "final_score": final_score,
        "recommendation": recommendation,
    }
    return json.dumps(summary, indent=2)


@function_tool
def list_campaign_performance() -> str:
    """Return campaign performance data for operations planning."""
    campaigns = store.list_campaigns()
    enriched = []
    for campaign in campaigns:
        roi = round(campaign["pipeline_usd"] / max(campaign["spend_usd"], 1), 2)
        enriched.append({**campaign, "roi_multiple": roi})
    return json.dumps(enriched, indent=2)


@function_tool
def create_follow_up_task(account_name: str, owner: str, due_date: str, task: str) -> str:
    """Create a follow-up task in the mock CRM."""
    record = store.add_task(account_name=account_name, owner=owner, due_date=due_date, task=task)
    return json.dumps(record, indent=2)


@function_tool
def add_crm_note(account_name: str, note: str) -> str:
    """Add a CRM note for an account."""
    record = store.add_note(account_name=account_name, note=note)
    return json.dumps(record, indent=2)


@function_tool(needs_approval=_approval_for_outbound_email)
def send_outreach_email(account_name: str, recipient: str, subject: str, body: str) -> str:
    """Send an outbound email. Pricing, discount, legal, and security topics require approval."""
    record = store.add_email(
        account_name=account_name,
        recipient=recipient,
        subject=subject,
        body=body,
        approved=True,
    )
    return json.dumps(record, indent=2)


@function_tool(needs_approval=True)
def submit_discount_request(account_name: str, percent: int, reason: str, submitted_by: str) -> str:
    """Submit a discount request. This always requires approval."""
    record = store.add_discount_request(
        account_name=account_name,
        percent=percent,
        reason=reason,
        submitted_by=submitted_by,
    )
    return json.dumps(record, indent=2)
