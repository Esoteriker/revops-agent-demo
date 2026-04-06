from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from agents import Agent, RunConfig, RunState, Runner, SQLiteSession
except ModuleNotFoundError:
    Agent = None
    RunConfig = None
    RunState = None
    Runner = None
    SQLiteSession = Any

from .store import RuntimeStore
from .offline_workflow import get_engine
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


def _format_offline_response(result: dict[str, Any]) -> str:
    lines: list[str] = [f"[langgraph offline] Routed to: {result['route']}"]
    account = result.get("context", {}).get("account")
    lead = result.get("context", {}).get("lead")
    deal = result.get("context", {}).get("deal")
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
    for insight in result.get("insights", []):
        lines.append(f"- {insight}")
    for step in result.get("steps", []):
        lines.append(f"* {step['label']}: {step['status']} | {step['detail']}")
    for draft in result.get("drafts", []):
        lines.append("Draft email:")
        lines.append(f"Subject: {draft['subject']}")
        lines.append(draft["body"])
    if result.get("approvals"):
        lines.append(f"Next action: {result['next_action']}")
    return "\n".join(lines)


def _run_offline(message: str) -> str:
    engine = get_engine()
    thread_id = str(uuid4())
    result = engine.start_run(message, thread_id)
    while result.get("approvals"):
        approval = result["approvals"][0]
        approved = _prompt_approval(approval["id"], json.dumps(approval["payload"]))
        result = engine.resume_run(thread_id, approved)
    return _format_offline_response(result)


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
