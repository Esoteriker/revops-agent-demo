import { useEffect, useState, useTransition } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed with status ${response.status}`);
  }

  return response.json();
}

function toneForStatus(status) {
  switch (status) {
    case "completed":
      return "positive";
    case "pending_approval":
      return "warning";
    case "blocked":
      return "critical";
    case "in_progress":
      return "active";
    default:
      return "neutral";
  }
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [currentRun, setCurrentRun] = useState(null);
  const [runId, setRunId] = useState(null);
  const [goal, setGoal] = useState("");
  const [notice, setNotice] = useState({
    tone: "neutral",
    title: "Booting",
    message: "Loading the operator console.",
  });
  const [busy, setBusy] = useState(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    loadBootstrap();
  }, []);

  async function loadBootstrap({ announce = true } = {}) {
    try {
      const payload = await apiRequest("/api/bootstrap");
      startTransition(() => {
        setDashboard(payload.dashboard);
      });
      if (announce) {
        setNotice({
          tone: "positive",
          title: "Connected",
          message: "Runtime snapshot loaded from the local backend.",
        });
      }
    } catch (error) {
      setNotice({
        tone: "critical",
        title: "Backend unavailable",
        message: error.message,
      });
    }
  }

  async function runWorkflow(prompt) {
    const trimmed = prompt.trim();
    if (!trimmed) {
      setNotice({
        tone: "warning",
        title: "Goal required",
        message: "Type a goal or choose a sample prompt before running the workflow.",
      });
      return;
    }

    setBusy("run");
    try {
      const payload = await apiRequest("/api/run", {
        method: "POST",
        body: JSON.stringify({ prompt: trimmed }),
      });

      setRunId(payload.run_id);
      startTransition(() => {
        setCurrentRun(payload.result);
        setDashboard((previous) => {
          if (!previous) return previous;
          return {
            ...previous,
            runtime: payload.result.runtime,
          };
        });
      });
      setNotice({
        tone: payload.result.approvals.length ? "warning" : "positive",
        title: payload.result.route,
        message: payload.result.next_action,
      });
      await loadBootstrap({ announce: false });
    } catch (error) {
      setNotice({
        tone: "critical",
        title: "Workflow failed",
        message: error.message,
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleApproval(approvalId, decision) {
    if (!runId) return;
    setBusy(`approval:${approvalId}`);
    try {
      const payload = await apiRequest("/api/approval", {
        method: "POST",
        body: JSON.stringify({
          run_id: runId,
          approval_id: approvalId,
          decision,
        }),
      });

      startTransition(() => {
        setCurrentRun(payload.result);
      });
      setNotice({
        tone: payload.result.approvals.length ? "warning" : "positive",
        title: "Approval updated",
        message: payload.result.next_action,
      });
      await loadBootstrap({ announce: false });
    } catch (error) {
      setNotice({
        tone: "critical",
        title: "Approval failed",
        message: error.message,
      });
    } finally {
      setBusy(null);
    }
  }

  async function resetRuntime() {
    setBusy("reset");
    try {
      await apiRequest("/api/reset", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setRunId(null);
      setCurrentRun(null);
      setGoal("");
      setNotice({
        tone: "neutral",
        title: "Reset complete",
        message: "The runtime store and current workflow state were cleared.",
      });
      await loadBootstrap({ announce: false });
    } catch (error) {
      setNotice({
        tone: "critical",
        title: "Reset failed",
        message: error.message,
      });
    } finally {
      setBusy(null);
    }
  }

  function samplePrompt(prompt) {
    setGoal(prompt);
    setNotice({
      tone: "neutral",
      title: "Prompt staged",
      message: "Review the goal, then run the workflow from the composer.",
    });
  }

  const runtime = dashboard?.runtime;
  const samplePrompts = dashboard?.sample_prompts || [];
  const accounts = dashboard?.accounts || [];
  const campaigns = dashboard?.campaigns || [];

  return (
    <div className="app-shell">
      <aside className="side-rail">
        <div className="brand-block">
          <div className="eyebrow">Revenue Command</div>
          <h1>RevOps ERP</h1>
          <p>
            Operator-grade console for goals, approvals, and account execution. The interface keeps the
            workflow visible, not chatty.
          </p>
        </div>

        <section className="panel">
          <div className="panel-head">
            <span>Priority Accounts</span>
            <strong>{dashboard?.kpis?.qualified_leads ?? 0}</strong>
          </div>
          <div className="account-list">
            {accounts.map((account) => (
              <button
                key={account.account_id}
                type="button"
                className="account-card"
                onClick={() => samplePrompt(`Advance ${account.name} toward close and create the next follow-up task.`)}
              >
                <span className="account-name">{account.name}</span>
                <span className="account-meta">
                  {account.industry} · {account.region}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span>Sample Goals</span>
          </div>
          <div className="prompt-list">
            {samplePrompts.map((prompt) => (
              <button key={prompt} type="button" className="prompt-chip" onClick={() => samplePrompt(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        </section>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">Execution Workspace</div>
            <h2>Operator Console</h2>
          </div>
          <div className="topbar-actions">
            <button type="button" className="ghost-button" onClick={loadBootstrap} disabled={busy !== null}>
              Refresh
            </button>
            <button type="button" className="ghost-button danger" onClick={resetRuntime} disabled={busy !== null}>
              Reset Runtime
            </button>
          </div>
        </header>

        <section className="notice-bar notice-card">
          <div>
            <div className="eyebrow">Status</div>
            <strong className={`status-pill ${notice.tone}`}>{notice.title}</strong>
          </div>
          <p>{notice.message}</p>
        </section>

        <section className="hero-band">
          <div className="hero-copy">
            <div className="eyebrow">Mode</div>
            <h3>Offline agent orchestration with approval checkpoints</h3>
            <p>
              Every run becomes a visible operational plan. The backend returns steps, insights, drafts,
              and approvals that the UI surfaces like an ERP work queue.
            </p>
          </div>
          <div className="kpi-grid">
            <Kpi label="Open pipeline" value={money(dashboard?.kpis?.open_pipeline_usd ?? 0)} />
            <Kpi label="Qualified leads" value={dashboard?.kpis?.qualified_leads ?? 0} />
            <Kpi label="Active campaigns" value={dashboard?.kpis?.active_campaigns ?? 0} />
            <Kpi label="Pending approvals" value={dashboard?.kpis?.pending_approvals ?? 0} />
          </div>
        </section>

        <section className="composer-card">
          <div className="section-head">
            <div>
              <div className="eyebrow">Goal Composer</div>
              <h3>Plan a revenue or operations goal</h3>
            </div>
            <span className="helper-text">Ctrl/⌘ + Enter to run</span>
          </div>
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                runWorkflow(goal);
              }
            }}
            placeholder="Advance Acme Corp toward close, draft the next email, and prepare a 15 percent discount request."
          />
          <div className="composer-actions">
            <button type="button" className="primary-button" onClick={() => runWorkflow(goal)} disabled={busy !== null}>
              {busy === "run" ? "Running..." : "Run Workflow"}
            </button>
            <span className="helper-text">{isPending ? "Rendering latest backend snapshot..." : "Backend API is local-only."}</span>
          </div>
        </section>

        <section className="content-grid">
          <div className="stack">
            <Card title="Current Run" eyebrow={currentRun?.route || "Awaiting goal"} accent={currentRun?.approvals?.length ? "warning" : "positive"}>
              {currentRun ? (
                <>
                  <div className="context-grid">
                    {currentRun.context?.account ? (
                      <ContextTile label="Account" value={currentRun.context.account.name} detail={`${currentRun.context.account.industry} · ${currentRun.context.account.region}`} />
                    ) : null}
                    {currentRun.context?.lead ? (
                      <ContextTile label="Lead" value={currentRun.context.lead.contact_name} detail={`${currentRun.context.lead.role} · ${currentRun.context.lead.status}`} />
                    ) : null}
                    {currentRun.context?.deal ? (
                      <ContextTile label="Deal" value={money(currentRun.context.deal.amount_usd)} detail={`${currentRun.context.deal.stage} · ${currentRun.context.deal.close_date}`} />
                    ) : null}
                  </div>

                  <div className="section-subtitle">Execution Plan</div>
                  <div className="plan-list">
                    {currentRun.steps.map((step) => (
                      <article key={step.id} className="plan-step">
                        <div className="plan-step-top">
                          <strong>{step.label}</strong>
                          <span className={`status-pill ${toneForStatus(step.status)}`}>{step.status.replaceAll("_", " ")}</span>
                        </div>
                        <p>{step.detail}</p>
                      </article>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState text="Run a goal to see the execution plan, context, and operational status." />
              )}
            </Card>

            <Card title="Signals and Drafts" eyebrow="Working Output" accent="neutral">
              <div className="split-stack">
                <section>
                  <div className="section-subtitle">Insights</div>
                  <div className="bullet-list">
                    {(currentRun?.insights || []).length ? (
                      currentRun.insights.map((item) => <div key={item} className="bullet-item">{item}</div>)
                    ) : (
                      <EmptyState text="No insights yet." />
                    )}
                  </div>
                </section>
                <section>
                  <div className="section-subtitle">Drafts</div>
                  <div className="draft-list">
                    {(currentRun?.drafts || []).length ? (
                      currentRun.drafts.map((draft) => (
                        <article key={`${draft.subject}-${draft.recipient}`} className="draft-card">
                          <div className="draft-head">
                            <strong>{draft.subject}</strong>
                            <span className="mini-pill">{draft.recipient}</span>
                          </div>
                          <pre>{draft.body}</pre>
                        </article>
                      ))
                    ) : (
                      <EmptyState text="No drafts generated yet." />
                    )}
                  </div>
                </section>
              </div>
            </Card>
          </div>

          <div className="stack">
            <Card title="Approvals" eyebrow="Human-in-the-loop" accent="warning">
              <div className="approval-stack">
                {(currentRun?.approvals || []).length ? (
                  currentRun.approvals.map((approval) => (
                    <article key={approval.id} className="approval-card">
                      <strong>{approval.title}</strong>
                      <p>{approval.description}</p>
                      <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
                      <div className="approval-actions">
                        <button
                          type="button"
                          className="approval-button approve"
                          onClick={() => handleApproval(approval.id, "approve")}
                          disabled={busy !== null}
                        >
                          {busy === `approval:${approval.id}` ? "Approving..." : "Approve"}
                        </button>
                        <button
                          type="button"
                          className="approval-button reject"
                          onClick={() => handleApproval(approval.id, "reject")}
                          disabled={busy !== null}
                        >
                          Reject
                        </button>
                      </div>
                    </article>
                  ))
                ) : (
                  <EmptyState text="No approvals waiting right now." />
                )}
              </div>
            </Card>

            <Card title="Recent Activity" eyebrow="Action Feed" accent="neutral">
              <div className="activity-list">
                {(currentRun?.activity || []).length ? (
                  currentRun.activity.map((item, index) => (
                    <article key={`${item.type}-${index}`} className="activity-item">
                      <strong>{item.type}</strong>
                      <p>{item.message}</p>
                    </article>
                  ))
                ) : (
                  <EmptyState text="Run the workflow to populate the action feed." />
                )}
              </div>
            </Card>

            <Card title="Runtime Summary" eyebrow="Persistent State" accent="neutral">
              {runtime ? (
                <div className="runtime-stack">
                  <div className="runtime-grid">
                    <RuntimeTile label="Tasks" value={runtime.tasks} />
                    <RuntimeTile label="Emails" value={runtime.emails} />
                    <RuntimeTile label="Notes" value={runtime.notes} />
                    <RuntimeTile label="Discounts" value={runtime.discount_requests} />
                  </div>

                  <section className="recent-block">
                    <div className="section-subtitle">Recent Writes</div>
                    <RecentList title="Tasks" items={runtime.recent.tasks} renderItem={(item) => `${item.task_id} · ${item.account_name}`} />
                    <RecentList title="Emails" items={runtime.recent.emails} renderItem={(item) => `${item.email_id} · ${item.account_name}`} />
                    <RecentList title="Notes" items={runtime.recent.notes} renderItem={(item) => `${item.note_id} · ${item.account_name}`} />
                    <RecentList title="Discounts" items={runtime.recent.discount_requests} renderItem={(item) => `${item.request_id} · ${item.account_name}`} />
                  </section>
                </div>
              ) : (
                <EmptyState text="Loading runtime summary..." />
              )}
            </Card>

            <Card title="Campaign Pulse" eyebrow="Operations Context" accent="neutral">
              <div className="campaign-list">
                {campaigns.map((campaign) => {
                  const roi = campaign.pipeline_usd / Math.max(campaign.spend_usd, 1);
                  return (
                    <article key={campaign.campaign_id} className="campaign-row">
                      <div>
                        <strong>{campaign.name}</strong>
                        <p>{campaign.channel} · {campaign.mqls} MQLs</p>
                      </div>
                      <span className="mini-pill">{roi.toFixed(2)}x ROI</span>
                    </article>
                  );
                })}
              </div>
            </Card>
          </div>
        </section>
      </main>
    </div>
  );
}

function Card({ eyebrow, title, accent = "neutral", children }) {
  return (
    <section className="surface-card">
      <div className="card-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h3>{title}</h3>
        </div>
        <span className={`status-pill ${accent}`}>{accent === "neutral" ? "steady" : accent}</span>
      </div>
      {children}
    </section>
  );
}

function Kpi({ label, value }) {
  return (
    <div className="kpi-card">
      <div className="eyebrow">{label}</div>
      <strong>{value}</strong>
    </div>
  );
}

function RuntimeTile({ label, value }) {
  return (
    <div className="runtime-card">
      <div className="eyebrow">{label}</div>
      <strong>{value}</strong>
    </div>
  );
}

function ContextTile({ label, value, detail }) {
  return (
    <article className="context-card">
      <div className="eyebrow">{label}</div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function RecentList({ title, items, renderItem }) {
  return (
    <div className="recent-list">
      <div className="recent-label">{title}</div>
      <div className="recent-items">
        {items.length ? items.map((item, index) => <div key={`${title}-${index}`}>{renderItem(item)}</div>) : <div className="muted-line">No recent {title.toLowerCase()}.</div>}
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>;
}

export default App;
