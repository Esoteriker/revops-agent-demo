# RevOps Agent Demo

This project is a small enterprise-style sales and operations automation demo built with the OpenAI Agents SDK.

It shows four practical patterns:

- a router agent that decides whether sales or operations should handle the request
- function tools backed by local mock CRM data
- session memory for multi-turn conversations
- human approval for sensitive actions such as sending email or discount escalation

## What the demo can do

- inspect leads, accounts, deals, and campaign performance
- draft outreach messages for sales follow-up
- create follow-up tasks and CRM notes
- propose discount requests that require approval before execution
- pause on sensitive tool calls and resume after a human decision

## Project layout

```text
data/mock_crm.json           Seed CRM data
src/revops_agent/agent.py    Agent definitions and CLI loop
src/revops_agent/tools.py    Business tools exposed to the model
src/revops_agent/store.py    Lightweight JSON-backed data store
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export OPENAI_API_KEY=sk-...
```

## Run

```bash
python3 -m revops_agent.agent --prompt "Review Acme Corp and draft a follow-up email for the CFO."
```

Interactive mode:

```bash
python3 -m revops_agent.agent
```

Example prompts:

- `Check whether Acme Corp is a qualified lead and draft an outreach note.`
- `Look at the Nimbus Labs deal and create a follow-up task for next week.`
- `Summarize campaign performance and suggest the next operations action.`
- `Prepare a discount request for Acme Corp at 18 percent.`

## Notes

- The demo uses local JSON files as stand-ins for CRM and ops systems.
- Tool approvals are handled through the SDK interruption flow.
- Conversation state is stored with `SQLiteSession` so the agent can remember previous turns.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Repository

Source: <https://github.com/Esoteriker/revops-agent-demo>
