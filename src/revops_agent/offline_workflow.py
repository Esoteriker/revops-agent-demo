from __future__ import annotations

import re
from typing import Any

from .store import RuntimeStore


store = RuntimeStore()


def _detect_account_name(message: str) -> str | None:
    lowered = message.casefold()
    for name in ("Acme Corp", "Nimbus Labs"):
        if name.casefold() in lowered:
            return name
    return None


def _route_message(message: str) -> str:
    lowered = message.casefold()
    ops_keywords = ("campaign", "pipeline", "ops", "operations", "crm hygiene", "process")
    return "Operations Specialist" if any(word in lowered for word in ops_keywords) else "Sales Specialist"


def _extract_discount_percent(message: str) -> int | None:
    match = re.search(r"(\d{1,2})\s*%", message)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{1,2})\s*percent", message.casefold())
    if match:
        return int(match.group(1))
    return None


def _build_email(account_name: str, recipient: str) -> tuple[str, str]:
    lead = store.find_lead(account_name) or {}
    account = store.find_account(account_name) or {}
    pain_points = ", ".join(lead.get("pain_points", [])) or "reporting bottlenecks"
    subject = f"{account_name}: a practical next step on {pain_points.split(',')[0]}"
    body = (
        f"Hi {recipient},\n\n"
        f"I reviewed {account_name} and noticed recurring pressure around {pain_points}. "
        f"We usually help teams like yours tighten reporting workflows and shorten execution cycles "
        f"without adding more tooling overhead.\n\n"
        f"If useful, I can send a short ROI summary tailored to your current planning cycle.\n\n"
        f"Best,\nYour account team"
    )
    if account.get("notes"):
        body = f"{body}\n\nContext used:\n- " + "\n- ".join(account["notes"])
    return subject, body


def _status_tone(status: str) -> str:
    return {
        "completed": "positive",
        "in_progress": "active",
        "pending_approval": "warning",
        "suggested": "neutral",
        "blocked": "critical",
    }.get(status, "neutral")


def _step(step_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {
        "id": step_id,
        "label": label,
        "status": status,
        "tone": _status_tone(status),
        "detail": detail,
    }


def _runtime_summary() -> dict[str, Any]:
    runtime = store.runtime_data()
    return {
        "tasks": len(runtime["tasks"]),
        "emails": len(runtime["emails"]),
        "notes": len(runtime["notes"]),
        "discount_requests": len(runtime["discount_requests"]),
        "recent": {
            "tasks": runtime["tasks"][-3:],
            "emails": runtime["emails"][-3:],
            "notes": runtime["notes"][-3:],
            "discount_requests": runtime["discount_requests"][-3:],
        },
    }


def build_dashboard_snapshot() -> dict[str, Any]:
    seed = store.seed_data()
    runtime = _runtime_summary()
    return {
        "accounts": seed["accounts"],
        "leads": seed["leads"],
        "deals": seed["deals"],
        "campaigns": seed["campaigns"],
        "runtime": runtime,
        "kpis": {
            "open_pipeline_usd": sum(item["amount_usd"] for item in seed["deals"]),
            "qualified_leads": sum(1 for item in seed["leads"] if item["status"] in {"qualified", "working"}),
            "active_campaigns": sum(1 for item in seed["campaigns"] if item["status"] == "active"),
            "pending_approvals": sum(1 for item in runtime["recent"]["discount_requests"] if item["status"] == "submitted"),
        },
        "sample_prompts": [
            "Advance Acme Corp toward close, draft the next email, and prepare a 15 percent discount request.",
            "Review Nimbus Labs and create the next follow-up task for the account owner.",
            "Summarize campaign performance and tell revops what to do next.",
        ],
    }


def run_offline_workflow(prompt: str, approvals: dict[str, bool] | None = None) -> dict[str, Any]:
    approvals = approvals or {}
    lowered = prompt.casefold()
    account_name = _detect_account_name(prompt)
    route = _route_message(prompt)
    account = store.find_account(account_name) if account_name else None
    lead = store.find_lead(account_name) if account_name else None
    deal = store.find_deal(account_name) if account_name else None

    steps: list[dict[str, str]] = []
    activity: list[dict[str, str]] = []
    approvals_needed: list[dict[str, Any]] = []
    drafts: list[dict[str, str]] = []
    insights: list[str] = []
    metrics: list[dict[str, str]] = []
    context: dict[str, Any] = {}

    if account:
        context["account"] = account
        steps.append(_step("account-sync", "Sync account context", "completed", f"Loaded {account['name']} account profile."))
        activity.append({"type": "context", "message": f"Loaded account profile for {account['name']}."})
        metrics.extend(
            [
                {"label": "Account tier", "value": account["tier"], "tone": "neutral"},
                {"label": "Health", "value": account["health"], "tone": "active"},
                {"label": "Last touch", "value": account["last_touch"], "tone": "neutral"},
            ]
        )

    if lead:
        final_score = min(lead["score"] + (8 if account and account["tier"] == "enterprise" else 4), 100)
        recommendation = "prioritize now" if final_score >= 85 else "nurture with targeted follow-up"
        context["lead"] = lead
        steps.append(_step("lead-qualification", "Score primary lead", "completed", f"Lead score landed at {final_score}."))
        insights.append(f"{lead['contact_name']} is the primary contact with a qualification score of {final_score}.")
        insights.append(f"Recommended motion: {recommendation}.")
        metrics.append({"label": "Lead score", "value": str(final_score), "tone": "positive" if final_score >= 85 else "warning"})

    if deal:
        context["deal"] = deal
        steps.append(_step("deal-review", "Review active opportunity", "completed", f"Deal is in {deal['stage']} for ${deal['amount_usd']:,}."))
        insights.append(f"Current deal stage is {deal['stage']} with next step '{deal['next_step']}'.")
        metrics.append({"label": "Deal amount", "value": f"${deal['amount_usd']:,}", "tone": "neutral"})

    if "campaign" in lowered:
        campaigns = store.seed_data()["campaigns"]
        ranked = sorted(
            campaigns,
            key=lambda item: item["pipeline_usd"] / max(item["spend_usd"], 1),
            reverse=True,
        )
        context["campaigns"] = campaigns
        steps.append(_step("campaign-review", "Review campaign performance", "completed", f"Compared {len(campaigns)} active campaign motions."))
        best = ranked[0]
        insights.append(f"Best-performing motion is {best['name']} at {round(best['pipeline_usd'] / best['spend_usd'], 2)}x ROI.")
        insights.append(f"Suggested next ops action: move more attention to {best['channel']} sourced pipeline.")
        metrics.append({"label": "Top ROI", "value": f"{round(best['pipeline_usd'] / best['spend_usd'], 2)}x", "tone": "positive"})

    should_create_task = account_name and any(word in lowered for word in ("task", "follow-up", "follow up", "advance", "next step"))
    should_create_note = account_name and any(word in lowered for word in ("note", "review", "advance", "brief"))
    should_draft_email = account_name and "email" in lowered and any(word in lowered for word in ("draft", "send", "outreach"))
    should_send_email = account_name and "send" in lowered and "email" in lowered
    should_request_discount = account_name and "discount" in lowered

    if should_create_task and account_name:
        task = store.add_task(
            account_name=account_name,
            owner=deal["owner"] if deal else "agent",
            due_date="2026-04-13",
            task="Advance the account with a targeted follow-up and confirm the next stakeholder review.",
        )
        steps.append(_step("task-create", "Create follow-up task", "completed", f"Created {task['task_id']} for {task['owner']}."))
        activity.append({"type": "task", "message": f"Created follow-up task {task['task_id']} due {task['due_date']}."})

    if should_create_note and account_name:
        note = store.add_note(
            account_name=account_name,
            note=f"Agent brief completed for {account_name}. Recommended a focused follow-up on the latest blocker.",
        )
        steps.append(_step("note-log", "Log CRM note", "completed", f"Stored note {note['note_id']} in the account timeline."))
        activity.append({"type": "note", "message": f"Stored CRM note {note['note_id']}."})

    if should_draft_email and account_name:
        recipient = lead["contact_name"] if lead else "Primary Contact"
        subject, body = _build_email(account_name, recipient)
        drafts.append({"type": "email", "subject": subject, "recipient": recipient, "body": body})
        steps.append(_step("email-draft", "Draft outreach email", "completed", f"Prepared a message for {recipient}."))
        activity.append({"type": "draft", "message": f"Prepared an outreach draft for {recipient}."})

    if should_send_email and account_name:
        recipient = lead["contact_name"] if lead else "Primary Contact"
        subject, body = _build_email(account_name, recipient)
        approval_id = "send-email"
        decision = approvals.get(approval_id)
        if decision is True:
            email = store.add_email(
                account_name=account_name,
                recipient=recipient,
                subject=subject,
                body=body,
                approved=True,
            )
            steps.append(_step("email-send", "Send outreach email", "completed", f"Sent {email['email_id']} to {recipient}."))
            activity.append({"type": "email", "message": f"Sent outbound email {email['email_id']}."})
        elif decision is False:
            steps.append(_step("email-send", "Send outreach email", "blocked", "Approval was denied by the reviewer."))
            activity.append({"type": "approval", "message": "Email approval was rejected."})
        else:
            steps.append(_step("email-send", "Send outreach email", "pending_approval", f"Waiting for approval before sending to {recipient}."))
            approvals_needed.append(
                {
                    "id": approval_id,
                    "title": "Approve outbound email",
                    "description": f"Send seller outreach to {recipient} for {account_name}.",
                    "payload": {"account_name": account_name, "recipient": recipient, "subject": subject},
                }
            )

    if should_request_discount and account_name:
        percent = _extract_discount_percent(prompt) or 10
        approval_id = "discount-request"
        decision = approvals.get(approval_id)
        if decision is True:
            request = store.add_discount_request(
                account_name=account_name,
                percent=percent,
                reason="Requested by offline operator workflow.",
                submitted_by="agent",
            )
            steps.append(_step("discount", "Submit discount request", "completed", f"Submitted {request['request_id']} for {percent}%."))
            activity.append({"type": "discount", "message": f"Submitted discount request {request['request_id']} for {percent}%."})
        elif decision is False:
            steps.append(_step("discount", "Submit discount request", "blocked", "Discount request was denied by the reviewer."))
            activity.append({"type": "approval", "message": "Discount approval was rejected."})
        else:
            steps.append(_step("discount", "Submit discount request", "pending_approval", f"Approval required for a {percent}% discount."))
            approvals_needed.append(
                {
                    "id": approval_id,
                    "title": "Approve discount request",
                    "description": f"Authorize a {percent}% discount for {account_name}.",
                    "payload": {"account_name": account_name, "percent": percent},
                }
            )

    if not steps:
        steps.append(_step("triage", "Triage incoming goal", "completed", "No account-specific execution was triggered."))
        insights.append("Try a prompt about Acme Corp, Nimbus Labs, campaign review, follow-up tasks, email, or discounts.")

    next_action = "Review pending approvals to continue execution." if approvals_needed else "Execution plan is clear. Continue with the next operator request."
    if route == "Operations Specialist" and not approvals_needed:
        next_action = "Create an ops follow-up if you want the system to persist the recommendation."

    return {
        "goal": prompt,
        "route": route,
        "context": context,
        "metrics": metrics,
        "insights": insights,
        "steps": steps,
        "drafts": drafts,
        "activity": activity,
        "approvals": approvals_needed,
        "next_action": next_action,
        "runtime": _runtime_summary(),
    }
