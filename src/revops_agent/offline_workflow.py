from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Literal, TypedDict

try:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt
except ModuleNotFoundError:
    InMemorySaver = None
    StateGraph = None
    START = "__start__"
    END = "__end__"
    Command = Any
    interrupt = None

from .store import RuntimeStore


store = RuntimeStore()


class WorkflowState(TypedDict, total=False):
    goal: str
    route: str
    account_name: str | None
    flags: dict[str, Any]
    context: dict[str, Any]
    metrics: list[dict[str, str]]
    insights: list[str]
    steps: list[dict[str, str]]
    drafts: list[dict[str, str]]
    activity: list[dict[str, str]]
    records: dict[str, dict[str, Any]]
    pending_email: dict[str, str]
    pending_discount: dict[str, Any]
    fallback_message: str


def _require_langgraph() -> None:
    if StateGraph is not None and InMemorySaver is not None and interrupt is not None:
        return
    raise RuntimeError("LangGraph is not installed. Install dependencies before running the offline workflow.")


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


def _upsert_step(steps: list[dict[str, str]], item: dict[str, str]) -> list[dict[str, str]]:
    updated = [dict(entry) for entry in steps]
    for index, entry in enumerate(updated):
        if entry["id"] == item["id"]:
            updated[index] = item
            return updated
    updated.append(item)
    return updated


def _append_activity(activity: list[dict[str, str]], item: dict[str, str]) -> list[dict[str, str]]:
    updated = [dict(entry) for entry in activity]
    updated.append(item)
    return updated


def _append_activity_once(activity: list[dict[str, str]], item: dict[str, str]) -> list[dict[str, str]]:
    updated = [dict(entry) for entry in activity]
    if any(entry.get("type") == item.get("type") and entry.get("message") == item.get("message") for entry in updated):
        return updated
    updated.append(item)
    return updated


def _flags_for_goal(goal: str, account_name: str | None) -> dict[str, Any]:
    lowered = goal.casefold()
    return {
        "review_campaigns": "campaign" in lowered,
        "create_task": bool(account_name and any(word in lowered for word in ("task", "follow-up", "follow up", "advance", "next step"))),
        "create_note": bool(account_name and any(word in lowered for word in ("note", "review", "advance", "brief"))),
        "draft_email": bool(account_name and "email" in lowered and any(word in lowered for word in ("draft", "send", "outreach"))),
        "send_email": bool(account_name and "send" in lowered and "email" in lowered),
        "request_discount": bool(account_name and "discount" in lowered),
        "discount_percent": _extract_discount_percent(goal) or 10,
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
            "pending_approvals": len(runtime["recent"]["discount_requests"]),
        },
        "sample_prompts": [
            "Advance Acme Corp toward close, draft the next email, and prepare a 15 percent discount request.",
            "Review Nimbus Labs and create the next follow-up task for the account owner.",
            "Summarize campaign performance and tell revops what to do next.",
        ],
    }


def _triage_node(state: WorkflowState) -> WorkflowState:
    goal = state["goal"]
    account_name = _detect_account_name(goal)
    steps = _upsert_step(
        state.get("steps", []),
        _step("triage", "Triage incoming goal", "completed", "Parsed route, account context, and requested actions."),
    )
    updates: WorkflowState = {
        "route": _route_message(goal),
        "account_name": account_name,
        "flags": _flags_for_goal(goal, account_name),
        "steps": steps,
        "records": deepcopy(state.get("records", {})),
    }
    if account_name is None:
        updates["fallback_message"] = (
            "Try a prompt about Acme Corp, Nimbus Labs, campaign review, follow-up tasks, email, or discounts."
        )
    return updates


def _context_node(state: WorkflowState) -> WorkflowState:
    account_name = state.get("account_name")
    if not account_name:
        return {
            "insights": [state.get("fallback_message", "No account-specific context available.")],
            "activity": _append_activity_once(
                state.get("activity", []),
                {"type": "context", "message": "No account was matched for this run."},
            ),
        }

    context = deepcopy(state.get("context", {}))
    metrics = [dict(item) for item in state.get("metrics", [])]
    insights = list(state.get("insights", []))
    activity = [dict(item) for item in state.get("activity", [])]
    steps = [dict(item) for item in state.get("steps", [])]

    account = store.find_account(account_name)
    lead = store.find_lead(account_name)
    deal = store.find_deal(account_name)

    if account:
        context["account"] = account
        metrics.extend(
            [
                {"label": "Account tier", "value": account["tier"], "tone": "neutral"},
                {"label": "Health", "value": account["health"], "tone": "active"},
                {"label": "Last touch", "value": account["last_touch"], "tone": "neutral"},
            ]
        )
        steps = _upsert_step(steps, _step("account-sync", "Sync account context", "completed", f"Loaded {account['name']} account profile."))
        activity = _append_activity_once(activity, {"type": "context", "message": f"Loaded account profile for {account['name']}."})

    if lead:
        final_score = min(lead["score"] + (8 if account and account["tier"] == "enterprise" else 4), 100)
        context["lead"] = lead
        metrics.append({"label": "Lead score", "value": str(final_score), "tone": "positive" if final_score >= 85 else "warning"})
        insights.extend(
            [
                f"{lead['contact_name']} is the primary contact with a qualification score of {final_score}.",
                f"Recommended motion: {'prioritize now' if final_score >= 85 else 'nurture with targeted follow-up'}.",
            ]
        )
        steps = _upsert_step(steps, _step("lead-qualification", "Score primary lead", "completed", f"Lead score landed at {final_score}."))

    if deal:
        context["deal"] = deal
        metrics.append({"label": "Deal amount", "value": f"${deal['amount_usd']:,}", "tone": "neutral"})
        insights.append(f"Current deal stage is {deal['stage']} with next step '{deal['next_step']}'.")
        steps = _upsert_step(steps, _step("deal-review", "Review active opportunity", "completed", f"Deal is in {deal['stage']} for ${deal['amount_usd']:,}."))

    return {
        "context": context,
        "metrics": metrics,
        "insights": insights,
        "activity": activity,
        "steps": steps,
    }


def _campaign_node(state: WorkflowState) -> WorkflowState:
    if not state.get("flags", {}).get("review_campaigns"):
        return {}

    campaigns = store.seed_data()["campaigns"]
    ranked = sorted(
        campaigns,
        key=lambda item: item["pipeline_usd"] / max(item["spend_usd"], 1),
        reverse=True,
    )
    context = deepcopy(state.get("context", {}))
    context["campaigns"] = campaigns
    best = ranked[0]
    insights = list(state.get("insights", []))
    insights.extend(
        [
            f"Best-performing motion is {best['name']} at {round(best['pipeline_usd'] / best['spend_usd'], 2)}x ROI.",
            f"Suggested next ops action: move more attention to {best['channel']} sourced pipeline.",
        ]
    )
    metrics = [dict(item) for item in state.get("metrics", [])]
    metrics.append({"label": "Top ROI", "value": f"{round(best['pipeline_usd'] / best['spend_usd'], 2)}x", "tone": "positive"})
    steps = _upsert_step(
        state.get("steps", []),
        _step("campaign-review", "Review campaign performance", "completed", f"Compared {len(campaigns)} active campaign motions."),
    )
    return {"context": context, "insights": insights, "metrics": metrics, "steps": steps}


def _task_node(state: WorkflowState) -> WorkflowState:
    if not state.get("flags", {}).get("create_task") or not state.get("account_name"):
        return {}

    records = deepcopy(state.get("records", {}))
    task = records.get("task-create")
    if task is None:
        deal = state.get("context", {}).get("deal")
        task = store.add_task(
            account_name=state["account_name"],
            owner=deal["owner"] if deal else "agent",
            due_date="2026-04-13",
            task="Advance the account with a targeted follow-up and confirm the next stakeholder review.",
        )
        records["task-create"] = task
    steps = _upsert_step(
        state.get("steps", []),
        _step("task-create", "Create follow-up task", "completed", f"Created {task['task_id']} for {task['owner']}."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "task", "message": f"Created follow-up task {task['task_id']} due {task['due_date']}."},
    )
    return {"steps": steps, "activity": activity, "records": records}


def _note_node(state: WorkflowState) -> WorkflowState:
    if not state.get("flags", {}).get("create_note") or not state.get("account_name"):
        return {}

    records = deepcopy(state.get("records", {}))
    note = records.get("note-log")
    if note is None:
        note = store.add_note(
            account_name=state["account_name"],
            note=f"Agent brief completed for {state['account_name']}. Recommended a focused follow-up on the latest blocker.",
        )
        records["note-log"] = note
    steps = _upsert_step(
        state.get("steps", []),
        _step("note-log", "Log CRM note", "completed", f"Stored note {note['note_id']} in the account timeline."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "note", "message": f"Stored CRM note {note['note_id']}."},
    )
    return {"steps": steps, "activity": activity, "records": records}


def _draft_node(state: WorkflowState) -> WorkflowState:
    flags = state.get("flags", {})
    account_name = state.get("account_name")
    if not account_name or not (flags.get("draft_email") or flags.get("send_email")):
        return {}

    lead = state.get("context", {}).get("lead") or {}
    recipient = lead.get("contact_name", "Primary Contact")
    subject, body = _build_email(account_name, recipient)
    drafts = [dict(item) for item in state.get("drafts", [])]
    drafts.append({"type": "email", "subject": subject, "recipient": recipient, "body": body})
    steps = _upsert_step(
        state.get("steps", []),
        _step("email-draft", "Draft outreach email", "completed", f"Prepared a message for {recipient}."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "draft", "message": f"Prepared an outreach draft for {recipient}."},
    )
    return {
        "drafts": drafts,
        "steps": steps,
        "activity": activity,
        "pending_email": {
            "account_name": account_name,
            "recipient": recipient,
            "subject": subject,
            "body": body,
        },
    }


def _email_approval_node(state: WorkflowState) -> Command:
    flags = state.get("flags", {})
    if not flags.get("send_email"):
        return Command(goto="discount_approval")

    payload = {
        "id": "send-email",
        "title": "Approve outbound email",
        "description": f"Send seller outreach to {state['pending_email']['recipient']} for {state['account_name']}.",
        "payload": {
            "account_name": state["pending_email"]["account_name"],
            "recipient": state["pending_email"]["recipient"],
            "subject": state["pending_email"]["subject"],
        },
        "step": {
            "id": "email-send",
            "label": "Send outreach email",
            "detail": f"Waiting for approval before sending to {state['pending_email']['recipient']}.",
        },
    }
    approved = interrupt(payload)
    return Command(goto="email_send" if approved else "email_rejected")


def _email_send_node(state: WorkflowState) -> WorkflowState:
    pending = state.get("pending_email")
    if not pending:
        return {}
    records = deepcopy(state.get("records", {}))
    email = records.get("email-send")
    if email is None:
        email = store.add_email(
            account_name=pending["account_name"],
            recipient=pending["recipient"],
            subject=pending["subject"],
            body=pending["body"],
            approved=True,
        )
        records["email-send"] = email
    steps = _upsert_step(
        state.get("steps", []),
        _step("email-send", "Send outreach email", "completed", f"Sent {email['email_id']} to {pending['recipient']}."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "email", "message": f"Sent outbound email {email['email_id']}."},
    )
    return {"steps": steps, "activity": activity, "records": records}


def _email_rejected_node(state: WorkflowState) -> WorkflowState:
    pending = state.get("pending_email")
    if not pending:
        return {}
    steps = _upsert_step(
        state.get("steps", []),
        _step("email-send", "Send outreach email", "blocked", "Approval was denied by the reviewer."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "approval", "message": "Email approval was rejected."},
    )
    return {"steps": steps, "activity": activity}


def _discount_approval_node(state: WorkflowState) -> Command:
    flags = state.get("flags", {})
    if not flags.get("request_discount"):
        return Command(goto="finalize")

    payload = {
        "id": "discount-request",
        "title": "Approve discount request",
        "description": f"Authorize a {flags['discount_percent']}% discount for {state['account_name']}.",
        "payload": {
            "account_name": state["account_name"],
            "percent": flags["discount_percent"],
        },
        "step": {
            "id": "discount",
            "label": "Submit discount request",
            "detail": f"Approval required for a {flags['discount_percent']}% discount.",
        },
    }
    approved = interrupt(payload)
    return Command(goto="discount_submit" if approved else "discount_rejected")


def _discount_submit_node(state: WorkflowState) -> WorkflowState:
    flags = state.get("flags", {})
    records = deepcopy(state.get("records", {}))
    request = records.get("discount")
    if request is None:
        request = store.add_discount_request(
            account_name=state["account_name"],
            percent=flags["discount_percent"],
            reason="Requested by offline operator workflow.",
            submitted_by="agent",
        )
        records["discount"] = request
    steps = _upsert_step(
        state.get("steps", []),
        _step("discount", "Submit discount request", "completed", f"Submitted {request['request_id']} for {flags['discount_percent']}%."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "discount", "message": f"Submitted discount request {request['request_id']} for {flags['discount_percent']}%."},
    )
    return {"steps": steps, "activity": activity, "records": records}


def _discount_rejected_node(state: WorkflowState) -> WorkflowState:
    steps = _upsert_step(
        state.get("steps", []),
        _step("discount", "Submit discount request", "blocked", "Discount request was denied by the reviewer."),
    )
    activity = _append_activity_once(
        state.get("activity", []),
        {"type": "approval", "message": "Discount approval was rejected."},
    )
    return {"steps": steps, "activity": activity}


def _finalize_node(state: WorkflowState) -> WorkflowState:
    if len(state.get("steps", [])) == 1 and state.get("fallback_message"):
        return {
            "insights": [state["fallback_message"]],
        }
    return {}


def _build_graph():
    _require_langgraph()
    graph = StateGraph(WorkflowState)
    graph.add_node("triage", _triage_node)
    graph.add_node("context", _context_node)
    graph.add_node("campaign_review", _campaign_node)
    graph.add_node("task_create", _task_node)
    graph.add_node("note_log", _note_node)
    graph.add_node("email_draft", _draft_node)
    graph.add_node("email_approval", _email_approval_node)
    graph.add_node("email_send", _email_send_node)
    graph.add_node("email_rejected", _email_rejected_node)
    graph.add_node("discount_approval", _discount_approval_node)
    graph.add_node("discount_submit", _discount_submit_node)
    graph.add_node("discount_rejected", _discount_rejected_node)
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "context")
    graph.add_edge("context", "campaign_review")
    graph.add_edge("campaign_review", "task_create")
    graph.add_edge("task_create", "note_log")
    graph.add_edge("note_log", "email_draft")
    graph.add_edge("email_draft", "email_approval")
    graph.add_edge("email_send", "discount_approval")
    graph.add_edge("email_rejected", "discount_approval")
    graph.add_edge("discount_submit", "finalize")
    graph.add_edge("discount_rejected", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=InMemorySaver())


def _pending_overlays(interrupts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    approvals: list[dict[str, Any]] = []
    pending_steps: list[dict[str, str]] = []
    for item in interrupts:
        approvals.append(
            {
                "id": item["id"],
                "title": item["title"],
                "description": item["description"],
                "payload": item["payload"],
            }
        )
        pending_steps.append(
            _step(
                item["step"]["id"],
                item["step"]["label"],
                "pending_approval",
                item["step"]["detail"],
            )
        )
    return approvals, pending_steps


def _response_from_state(state: WorkflowState, interrupts: list[dict[str, Any]]) -> dict[str, Any]:
    data = deepcopy(state)
    approvals, pending_steps = _pending_overlays(interrupts)
    steps = [dict(item) for item in data.get("steps", [])]
    for item in pending_steps:
        steps = _upsert_step(steps, item)

    route = data.get("route", "Sales Specialist")
    next_action = "Review pending approvals to continue execution." if approvals else "Execution plan is clear. Continue with the next operator request."
    if route == "Operations Specialist" and not approvals:
        next_action = "Create an ops follow-up if you want the system to persist the recommendation."

    return {
        "goal": data.get("goal", ""),
        "route": route,
        "context": data.get("context", {}),
        "metrics": data.get("metrics", []),
        "insights": data.get("insights", []),
        "steps": steps,
        "drafts": data.get("drafts", []),
        "activity": data.get("activity", []),
        "approvals": approvals,
        "next_action": next_action,
        "runtime": _runtime_summary(),
    }


class LangGraphRevOpsEngine:
    def __init__(self) -> None:
        self.graph = _build_graph()

    def start_run(self, prompt: str, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self.graph.invoke({"goal": prompt}, config=config)
        snapshot = self.graph.get_state(config)
        interrupts = [item.value for item in result.get("__interrupt__", [])] if isinstance(result, dict) else []
        return _response_from_state(snapshot.values, interrupts)

    def resume_run(self, thread_id: str, approved: bool) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self.graph.invoke(Command(resume=approved), config=config)
        snapshot = self.graph.get_state(config)
        interrupts = [item.value for item in result.get("__interrupt__", [])] if isinstance(result, dict) else []
        return _response_from_state(snapshot.values, interrupts)


ENGINE: LangGraphRevOpsEngine | None = None


def get_engine() -> LangGraphRevOpsEngine:
    global ENGINE
    if ENGINE is None:
        ENGINE = LangGraphRevOpsEngine()
    return ENGINE


def reset_engine() -> None:
    global ENGINE
    ENGINE = LangGraphRevOpsEngine()
