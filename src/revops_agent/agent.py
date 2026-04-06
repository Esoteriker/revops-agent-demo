from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from agents import Agent, RunConfig, RunState, Runner, SQLiteSession
except ModuleNotFoundError:
    Agent = None
    RunConfig = None
    RunState = None
    Runner = None
    SQLiteSession = Any

from .store import RuntimeStore
from .tools import (
    add_crm_note,
    create_follow_up_task,
    list_campaign_performance,
    lookup_account,
    lookup_deal,
    lookup_lead,
    score_lead,
    send_outreach_email,
    submit_discount_request,
)


CACHE_DIR = Path(".cache")
STATE_PATH = CACHE_DIR / "hitl_state.json"
store = RuntimeStore()


def _tool_error_formatter(args) -> str | None:
    if getattr(args, "kind", None) != "approval_rejected":
        return None
    return "The sensitive action was not executed because approval was denied. Continue with a safe alternative."


if Agent is not None:
    sales_agent = Agent(
        name="Sales Specialist",
        handoff_description="Handles lead qualification, deal review, follow-up drafting, and account outreach.",
        instructions=(
            "You are a senior enterprise sales assistant. Work from CRM facts, keep outputs concise, "
            "and never invent account data. Use tools before making recommendations. When asked to send "
            "customer-facing email, draft a crisp business message and call the email tool only if the "
            "user explicitly asks you to send it."
        ),
        tools=[
            lookup_account,
            lookup_lead,
            lookup_deal,
            score_lead,
            create_follow_up_task,
            add_crm_note,
            send_outreach_email,
            submit_discount_request,
        ],
    )

    ops_agent = Agent(
        name="Operations Specialist",
        handoff_description="Handles campaign review, pipeline operations, CRM updates, and execution planning.",
        instructions=(
            "You are a revenue operations assistant. Focus on operational clarity, next actions, and "
            "pipeline hygiene. Use tools to inspect campaigns and CRM records before making suggestions."
        ),
        tools=[
            lookup_account,
            lookup_deal,
            list_campaign_performance,
            create_follow_up_task,
            add_crm_note,
        ],
    )

    router_agent = Agent(
        name="RevOps Router",
        instructions=(
            "You are the top-level coordinator for a sales and operations automation assistant. "
            "Route sales execution, lead work, outreach, and deal support to the Sales Specialist. "
            "Route campaign analytics, pipeline process work, CRM hygiene, and operational planning to "
            "the Operations Specialist. If the request spans both areas, pick the agent best suited to "
            "own the answer and let that specialist respond."
        ),
        handoffs=[sales_agent, ops_agent],
    )
else:
    sales_agent = None
    ops_agent = None
    router_agent = None


def _require_api_key() -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    raise SystemExit("OPENAI_API_KEY is not set. Export it before running this demo.")


def _require_agents_sdk() -> None:
    if Agent is not None:
        return
    raise SystemExit(
        "The OpenAI Agents SDK is not installed. Install dependencies or run with --offline for the local demo."
    )


def _prompt_approval(tool_name: str, arguments: str | None) -> bool:
    answer = input(f"Approve {tool_name} with {arguments}? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _detect_account_name(message: str) -> str | None:
    lowered = message.casefold()
    for name in ("Acme Corp", "Nimbus Labs"):
        if name.casefold() in lowered:
            return name
    return None


def _route_offline(message: str) -> str:
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
        f"I took a look at {account_name} and noticed recurring pressure around {pain_points}. "
        f"We usually help teams like yours tighten reporting workflows and shorten execution cycles "
        f"without adding more tooling overhead.\n\n"
        f"If useful, I can send a short ROI summary tailored to your current planning cycle.\n\n"
        f"Best,\nYour account team"
    )
    if account.get("notes"):
        body = (
            f"{body}\n\nContext used:\n- " + "\n- ".join(account["notes"])
        )
    return subject, body


def _run_offline(message: str) -> str:
    account_name = _detect_account_name(message)
    route = _route_offline(message)
    lowered = message.casefold()
    lines: list[str] = [f"[offline demo] Routed to: {route}"]

    if account_name:
        account = store.find_account(account_name)
        lead = store.find_lead(account_name)
        deal = store.find_deal(account_name)
        if account:
            lines.append(
                f"Account: {account['name']} | tier={account['tier']} | health={account['health']} | last_touch={account['last_touch']}"
            )
        if lead:
            lines.append(
                f"Lead: {lead['contact_name']} ({lead['role']}) | score={lead['score']} | status={lead['status']}"
            )
        if deal:
            lines.append(
                f"Deal: stage={deal['stage']} | amount=${deal['amount_usd']} | next_step={deal['next_step']}"
            )

    if "campaign" in lowered:
        campaigns = store.list_campaigns()
        lines.append("Campaign performance:")
        for campaign in campaigns:
            roi = round(campaign["pipeline_usd"] / max(campaign["spend_usd"], 1), 2)
            lines.append(
                f"- {campaign['name']} | channel={campaign['channel']} | mqls={campaign['mqls']} | roi={roi}x"
            )
        best = max(campaigns, key=lambda item: item["pipeline_usd"] / max(item["spend_usd"], 1))
        lines.append(f"Suggested next ops action: shift more attention to {best['name']}.")

    if account_name and ("qualif" in lowered or "score" in lowered):
        lead = store.find_lead(account_name)
        account = store.find_account(account_name)
        if lead and account:
            final_score = min(lead["score"] + (8 if account["tier"] == "enterprise" else 4), 100)
            recommendation = "prioritize now" if final_score >= 85 else "nurture with targeted follow-up"
            lines.append(f"Qualification: final_score={final_score} | recommendation={recommendation}")

    if account_name and "note" in lowered:
        note = f"Offline demo note for {account_name}: reviewed latest activity and recommended a targeted follow-up."
        record = store.add_note(account_name=account_name, note=note)
        lines.append(f"CRM note created: {record['note_id']}")

    if account_name and ("task" in lowered or "follow-up" in lowered or "follow up" in lowered):
        record = store.add_task(
            account_name=account_name,
            owner="agent",
            due_date="2026-04-13",
            task="Follow up on latest account activity and confirm next meeting.",
        )
        lines.append(f"Task created: {record['task_id']} due {record['due_date']}")

    if account_name and ("draft" in lowered and "email" in lowered):
        lead = store.find_lead(account_name) or {}
        recipient = lead.get("contact_name", "there")
        subject, body = _build_email(account_name, recipient)
        lines.append("Draft email:")
        lines.append(f"Subject: {subject}")
        lines.append(body)

    if account_name and "send" in lowered and "email" in lowered:
        lead = store.find_lead(account_name) or {}
        recipient = lead.get("contact_name", "there")
        subject, body = _build_email(account_name, recipient)
        approved = _prompt_approval(
            "send_outreach_email",
            json.dumps({"account_name": account_name, "recipient": recipient, "subject": subject}),
        )
        if approved:
            record = store.add_email(
                account_name=account_name,
                recipient=recipient,
                subject=subject,
                body=body,
                approved=True,
            )
            lines.append(f"Email sent in offline demo: {record['email_id']}")
        else:
            lines.append("Email send rejected during offline approval.")

    if account_name and "discount" in lowered:
        percent = _extract_discount_percent(message) or 10
        approved = _prompt_approval(
            "submit_discount_request",
            json.dumps({"account_name": account_name, "percent": percent}),
        )
        if approved:
            record = store.add_discount_request(
                account_name=account_name,
                percent=percent,
                reason="Offline demo request",
                submitted_by="agent",
            )
            lines.append(f"Discount request submitted: {record['request_id']} for {percent}%")
        else:
            lines.append("Discount request rejected during offline approval.")

    if len(lines) == 1:
        lines.append(
            "No direct offline action matched. Try a prompt about Acme Corp, Nimbus Labs, campaign performance, follow-up tasks, email drafts, or discount approvals."
        )

    return "\n".join(lines)


async def _run_until_complete(message: str, session: SQLiteSession) -> str:
    _require_agents_sdk()
    run_config = RunConfig(tool_error_formatter=_tool_error_formatter)
    result = await Runner.run(router_agent, message, session=session, run_config=run_config)

    while result.interruptions:
        state = result.to_state()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(state.to_string())

        stored = json.loads(STATE_PATH.read_text())
        state = await RunState.from_json(router_agent, stored)

        for interruption in result.interruptions:
            approved = await asyncio.get_running_loop().run_in_executor(
                None,
                _prompt_approval,
                interruption.name or "unknown_tool",
                interruption.arguments,
            )
            if approved:
                state.approve(interruption)
            else:
                state.reject(interruption)

        result = await Runner.run(router_agent, state, session=session, run_config=run_config)

    return str(result.final_output)


async def _interactive_loop() -> None:
    _require_agents_sdk()
    session = SQLiteSession("revops-demo")
    print("RevOps Agent ready. Type 'exit' to quit.")
    while True:
        message = input("\nYou: ").strip()
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            break

        output = await _run_until_complete(message, session)
        print(f"\nAgent: {output}")


def _interactive_offline_loop() -> None:
    print("RevOps Agent offline demo ready. Type 'exit' to quit.")
    while True:
        message = input("\nYou: ").strip()
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            break
        print(f"\nAgent: {_run_offline(message)}")


async def _single_prompt(prompt: str) -> None:
    _require_agents_sdk()
    session = SQLiteSession("revops-demo")
    output = await _run_until_complete(prompt, session)
    print(output)


def _single_prompt_offline(prompt: str) -> None:
    print(_run_offline(prompt))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RevOps agent demo.")
    parser.add_argument("--prompt", help="Single prompt mode.")
    parser.add_argument("--offline", action="store_true", help="Run a local offline demo without calling the OpenAI API.")
    args = parser.parse_args()

    if args.offline:
        if args.prompt:
            _single_prompt_offline(args.prompt)
            return
        _interactive_offline_loop()
        return

    _require_api_key()

    if args.prompt:
        asyncio.run(_single_prompt(args.prompt))
        return

    asyncio.run(_interactive_loop())


if __name__ == "__main__":
    main()
