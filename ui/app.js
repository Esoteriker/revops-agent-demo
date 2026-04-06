const state = {
  runId: null,
  dashboard: null,
  result: null,
};

const $ = (id) => document.getElementById(id);

const STATUS_LABELS = {
  neutral: "Standing by",
  active: "In progress",
  positive: "Ready",
  warning: "Needs review",
  critical: "Blocked",
};

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }

  return response.json();
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char];
  });
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function formatShortDate(value) {
  if (!value) return "No date";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return escapeHTML(value);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
}

function formatTimestamp() {
  return `Synced ${new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date())}`;
}

function statusPill(tone, label = STATUS_LABELS[tone] || "Status") {
  return `<span class="status-pill ${tone}">${escapeHTML(label)}</span>`;
}

function metricTile(metric) {
  const tone = metric.tone || "neutral";
  return `
    <article class="metric-tile ${tone}">
      <span class="eyebrow">${escapeHTML(metric.label)}</span>
      <strong class="metric-value">${escapeHTML(metric.value)}</strong>
    </article>
  `;
}

function summaryTile(label, value, detail) {
  return `
    <article class="summary-tile">
      <span class="summary-label">${escapeHTML(label)}</span>
      <strong>${escapeHTML(value)}</strong>
      <p>${escapeHTML(detail)}</p>
    </article>
  `;
}

function emptyState(text) {
  return `<div class="empty-state">${escapeHTML(text)}</div>`;
}

function accountTone(health) {
  return {
    hot: "positive",
    warm: "warning",
    cold: "critical",
  }[String(health || "").toLowerCase()] || "neutral";
}

function planTone(result) {
  if (!result) return "neutral";
  if (result.steps.some((step) => step.status === "blocked")) return "critical";
  if (result.approvals.length) return "warning";
  if (result.steps.some((step) => step.status === "in_progress")) return "active";
  if (result.steps.length) return "positive";
  return "neutral";
}

function planHealthLabel(result) {
  if (!result) return "No active run";
  const completed = result.steps.filter((step) => step.status === "completed").length;
  const blocked = result.steps.filter((step) => step.status === "blocked").length;

  if (blocked) return `${blocked} blocked`;
  if (result.approvals.length) return `${result.approvals.length} approvals waiting`;
  return `${completed}/${result.steps.length} steps completed`;
}

function renderRunSummary(result) {
  if (!result) {
    $("runSummary").innerHTML = `
      <div class="summary-grid">
        ${summaryTile("Route", "None", "No workflow is staged")}
        ${summaryTile("Plan", "0 steps", "Awaiting an operator request")}
        ${summaryTile("Approvals", "0 waiting", "Decision gates appear here")}
        ${summaryTile("Outputs", "0 items", "Drafts, insights, and activity")}
      </div>
      <div class="goal-preview">
        <span class="summary-label">Goal</span>
        <p>No goal has been submitted yet.</p>
      </div>
    `;
    return;
  }

  const completed = result.steps.filter((step) => step.status === "completed").length;
  const outputs = result.metrics.length + result.insights.length + result.drafts.length;

  $("runSummary").innerHTML = `
    <div class="summary-grid">
      ${summaryTile("Route", result.route, "Agent owner for this request")}
      ${summaryTile("Plan", `${completed}/${result.steps.length}`, "Completed steps")}
      ${summaryTile("Approvals", `${result.approvals.length} waiting`, "Manual gates still open")}
      ${summaryTile("Outputs", `${outputs} items`, "Signals and drafts produced")}
    </div>
    <div class="goal-preview">
      <span class="summary-label">Goal</span>
      <p>${escapeHTML(result.goal)}</p>
    </div>
  `;
}

function setRunStatus(tone, message) {
  $("nextAction").className = `status-pill ${tone}`;
  $("nextAction").textContent = STATUS_LABELS[tone] || "Status";
  $("nextActionText").textContent = message;
}

function payloadRows(payload) {
  return Object.entries(payload)
    .map(
      ([key, value]) => `
        <div class="payload-row">
          <span>${escapeHTML(key.replaceAll("_", " "))}</span>
          <strong>${escapeHTML(value)}</strong>
        </div>
      `
    )
    .join("");
}

function recentGroup(title, items) {
  return `
    <section class="recent-group">
      <p class="section-label">${escapeHTML(title)}</p>
      <div class="recent-items">
        ${
          items.length
            ? items.map((item) => `<div class="recent-item">${escapeHTML(item)}</div>`).join("")
            : `<div class="empty-line">No recent writes.</div>`
        }
      </div>
    </section>
  `;
}

function renderCampaignBoard(campaigns) {
  $("campaignBoard").innerHTML = campaigns.length
    ? campaigns
        .map((campaign) => {
          const roi = campaign.pipeline_usd / Math.max(campaign.spend_usd, 1);
          return `
            <article class="campaign-row">
              <div class="campaign-copy">
                <strong>${escapeHTML(campaign.name)}</strong>
                <p>${escapeHTML(campaign.channel)} channel · ${escapeHTML(String(campaign.mqls))} MQLs</p>
              </div>
              <div class="campaign-stats">
                <span>${money(campaign.pipeline_usd)}</span>
                <strong>${roi.toFixed(2)}x ROI</strong>
              </div>
            </article>
          `;
        })
        .join("")
    : emptyState("No campaigns are available.");
}

function renderRuntimeSummary(runtime) {
  const recentTasks = runtime.recent.tasks.map((item) => `${item.task_id} · ${item.account_name}`);
  const recentEmails = runtime.recent.emails.map((item) => `${item.email_id} · ${item.account_name}`);
  const recentNotes = runtime.recent.notes.map((item) => `${item.note_id} · ${item.account_name}`);
  const recentDiscounts = runtime.recent.discount_requests.map((item) => `${item.request_id} · ${item.account_name}`);

  $("runtimeSummary").innerHTML = `
    <div class="runtime-grid">
      <article class="runtime-box">
        <span class="eyebrow">Tasks</span>
        <strong>${escapeHTML(String(runtime.tasks))}</strong>
      </article>
      <article class="runtime-box">
        <span class="eyebrow">Emails</span>
        <strong>${escapeHTML(String(runtime.emails))}</strong>
      </article>
      <article class="runtime-box">
        <span class="eyebrow">Notes</span>
        <strong>${escapeHTML(String(runtime.notes))}</strong>
      </article>
      <article class="runtime-box">
        <span class="eyebrow">Discounts</span>
        <strong>${escapeHTML(String(runtime.discount_requests))}</strong>
      </article>
    </div>

    <div class="recent-grid">
      ${recentGroup("Recent tasks", recentTasks)}
      ${recentGroup("Recent emails", recentEmails)}
      ${recentGroup("Recent notes", recentNotes)}
      ${recentGroup("Recent discounts", recentDiscounts)}
    </div>
  `;
}

function renderDashboard(dashboard) {
  state.dashboard = dashboard;
  $("qualifiedCount").textContent = dashboard.kpis.qualified_leads;
  $("lastSyncLabel").textContent = formatTimestamp();

  $("kpiStrip").innerHTML = `
    <article class="kpi-tile">
      <span class="eyebrow">Open pipeline</span>
      <strong>${money(dashboard.kpis.open_pipeline_usd)}</strong>
      <p>Tracked deal value across active opportunities.</p>
    </article>
    <article class="kpi-tile">
      <span class="eyebrow">Qualified leads</span>
      <strong>${escapeHTML(String(dashboard.kpis.qualified_leads))}</strong>
      <p>Leads that are ready for direct seller follow-up.</p>
    </article>
    <article class="kpi-tile">
      <span class="eyebrow">Active campaigns</span>
      <strong>${escapeHTML(String(dashboard.kpis.active_campaigns))}</strong>
      <p>Live demand sources contributing pipeline right now.</p>
    </article>
    <article class="kpi-tile">
      <span class="eyebrow">Pending approvals</span>
      <strong>${escapeHTML(String(dashboard.kpis.pending_approvals))}</strong>
      <p>Requests in the queue that still need human signoff.</p>
    </article>
  `;

  $("accountList").innerHTML = dashboard.accounts
    .map((account) => {
      const tone = accountTone(account.health);
      return `
        <button class="account-item" data-prompt="${escapeHTML(
          `Advance ${account.name} toward close and create the next follow-up task.`
        )}">
          <div class="account-top">
            <strong>${escapeHTML(account.name)}</strong>
            ${statusPill(tone, account.health)}
          </div>
          <p class="account-meta">${escapeHTML(account.industry)} · ${escapeHTML(account.region)}</p>
          <div class="account-flags">
            <span class="mini-badge">${escapeHTML(account.tier)}</span>
            <span class="mini-badge">Last touch ${formatShortDate(account.last_touch)}</span>
          </div>
        </button>
      `;
    })
    .join("");

  $("samplePrompts").innerHTML = dashboard.sample_prompts
    .map((prompt) => `<button class="prompt-chip" data-prompt="${escapeHTML(prompt)}">${escapeHTML(prompt)}</button>`)
    .join("");

  renderRuntimeSummary(dashboard.runtime);
  renderCampaignBoard(dashboard.campaigns);
  bindPromptButtons();
}

function renderContext(result) {
  const cards = [];

  if (result.context.account) {
    const account = result.context.account;
    cards.push(`
      <article class="context-card">
        <span class="eyebrow">Account</span>
        <strong>${escapeHTML(account.name)}</strong>
        <p>${escapeHTML(account.industry)} · ${escapeHTML(account.region)}</p>
        <div class="context-detail">
          <span>${escapeHTML(account.tier)} tier</span>
          <span>${escapeHTML(String(account.employees))} employees</span>
        </div>
      </article>
    `);
  }

  if (result.context.lead) {
    const lead = result.context.lead;
    cards.push(`
      <article class="context-card">
        <span class="eyebrow">Primary lead</span>
        <strong>${escapeHTML(lead.contact_name)}</strong>
        <p>${escapeHTML(lead.role)} · ${escapeHTML(lead.source)} source</p>
        <div class="context-detail">
          <span>Status ${escapeHTML(lead.status)}</span>
          <span>Score ${escapeHTML(String(lead.score))}</span>
        </div>
      </article>
    `);
  }

  if (result.context.deal) {
    const deal = result.context.deal;
    cards.push(`
      <article class="context-card">
        <span class="eyebrow">Open deal</span>
        <strong>${money(deal.amount_usd)}</strong>
        <p>${escapeHTML(deal.stage)} · closes ${escapeHTML(deal.close_date)}</p>
        <div class="context-detail">
          <span>Owner ${escapeHTML(deal.owner)}</span>
          <span>${escapeHTML(deal.next_step)}</span>
        </div>
      </article>
    `);
  }

  $("contextBlock").innerHTML = cards.length ? cards.join("") : emptyState("No account context for this run yet.");
}

function renderPlan(result) {
  if (!result.steps.length) {
    $("planList").innerHTML = emptyState("No workflow steps are available for this goal.");
    return;
  }

  $("planList").innerHTML = result.steps
    .map(
      (step, index) => `
        <article class="plan-row ${escapeHTML(step.tone)}">
          <div class="plan-step-label">
            <span class="row-index">${String(index + 1).padStart(2, "0")}</span>
            <strong>${escapeHTML(step.label)}</strong>
          </div>
          <div class="plan-step-status">
            ${statusPill(step.tone, step.status.replaceAll("_", " "))}
          </div>
          <p>${escapeHTML(step.detail)}</p>
        </article>
      `
    )
    .join("");
}

function renderMetrics(result) {
  $("metricGrid").innerHTML = result.metrics.length
    ? result.metrics.map(metricTile).join("")
    : emptyState("No metrics for this run yet.");
}

function renderInsights(result) {
  $("insightList").innerHTML = result.insights.length
    ? result.insights.map((item) => `<article class="insight-item">${escapeHTML(item)}</article>`).join("")
    : emptyState("No insights yet.");
}

function renderDrafts(result) {
  $("draftCount").textContent = `${result.drafts.length} draft${result.drafts.length === 1 ? "" : "s"}`;
  $("draftList").innerHTML = result.drafts.length
    ? result.drafts
        .map(
          (draft) => `
            <article class="draft-card">
              <div class="draft-head">
                <div>
                  <strong>${escapeHTML(draft.subject)}</strong>
                  <p>${escapeHTML(draft.recipient)}</p>
                </div>
                <span class="mini-badge">email draft</span>
              </div>
              <pre>${escapeHTML(draft.body)}</pre>
            </article>
          `
        )
        .join("")
    : emptyState("No drafts generated for this run.");
}

function renderApprovals(result) {
  $("approvalCount").textContent = result.approvals.length;
  $("approvalList").innerHTML = result.approvals.length
    ? result.approvals
        .map(
          (approval) => `
            <article class="approval-card">
              <div class="approval-head">
                <strong>${escapeHTML(approval.title)}</strong>
                ${statusPill("warning", "Pending")}
              </div>
              <p>${escapeHTML(approval.description)}</p>
              <div class="payload-grid">
                ${payloadRows(approval.payload)}
              </div>
              <div class="approval-actions">
                <button class="decision-button approve" data-approval="${escapeHTML(approval.id)}" data-decision="approve">Approve</button>
                <button class="decision-button reject" data-approval="${escapeHTML(approval.id)}" data-decision="reject">Reject</button>
              </div>
            </article>
          `
        )
        .join("")
    : emptyState("No approvals waiting.");

  bindApprovalButtons();
}

function renderActivity(result) {
  $("activityList").innerHTML = result.activity.length
    ? result.activity
        .map(
          (item) => `
            <article class="activity-item">
              <div class="activity-head">
                <span class="mini-badge">${escapeHTML(item.type)}</span>
              </div>
              <p>${escapeHTML(item.message)}</p>
            </article>
          `
        )
        .join("")
    : emptyState("No activity recorded yet.");
}

function renderResult(result) {
  state.result = result;
  $("routeLabel").textContent = result.route;
  $("planHealth").textContent = planHealthLabel(result);

  renderRunSummary(result);
  renderContext(result);
  renderPlan(result);
  renderMetrics(result);
  renderInsights(result);
  renderDrafts(result);
  renderApprovals(result);
  renderActivity(result);
  renderRuntimeSummary(result.runtime);

  setRunStatus(planTone(result), result.next_action);
}

function resetRunSurface() {
  state.result = null;
  $("routeLabel").textContent = "Awaiting goal";
  $("planHealth").textContent = "No active run";
  $("draftCount").textContent = "0 drafts";
  renderRunSummary(null);
  setRunStatus("neutral", "Stage a goal to populate the operator workspace.");
  $("contextBlock").innerHTML = emptyState("No account context for this run yet.");
  $("planList").innerHTML = emptyState("Run a goal to see the execution plan.");
  $("metricGrid").innerHTML = emptyState("No metrics for this run yet.");
  $("insightList").innerHTML = emptyState("No insights yet.");
  $("draftList").innerHTML = emptyState("No drafts generated for this run.");
  $("approvalCount").textContent = "0";
  $("approvalList").innerHTML = emptyState("No approvals waiting.");
  $("activityList").innerHTML = emptyState("No workflow has run yet.");
}

function showOperatorMessage(message, tone = "neutral") {
  $("activityList").innerHTML = `
    <article class="activity-item">
      <div class="activity-head">
        ${statusPill(tone, STATUS_LABELS[tone] || "Update")}
      </div>
      <p>${escapeHTML(message)}</p>
    </article>
  `;
}

async function loadBootstrap() {
  const payload = await fetchJSON("/api/bootstrap");
  renderDashboard(payload.dashboard);
}

async function runWorkflow() {
  const prompt = $("goalInput").value.trim();
  if (!prompt) {
    $("goalInput").focus();
    setRunStatus("warning", "Enter a goal first, or select one of the staged prompts from the left rail.");
    showOperatorMessage("Input required before the workflow can run.", "warning");
    return;
  }

  $("runButton").disabled = true;
  $("runButton").textContent = "Running...";

  try {
    const payload = await fetchJSON("/api/run", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });

    state.runId = payload.run_id;
    renderResult(payload.result);

    const latest = await fetchJSON("/api/runtime");
    renderDashboard(latest.dashboard);
  } catch (error) {
    setRunStatus("critical", error.message);
    showOperatorMessage(error.message, "critical");
  } finally {
    $("runButton").disabled = false;
    $("runButton").textContent = "Run workflow";
  }
}

async function resolveApproval(approvalId, decision) {
  if (!state.runId) return;

  try {
    const payload = await fetchJSON("/api/approval", {
      method: "POST",
      body: JSON.stringify({
        run_id: state.runId,
        approval_id: approvalId,
        decision,
      }),
    });

    renderResult(payload.result);

    const latest = await fetchJSON("/api/runtime");
    renderDashboard(latest.dashboard);
  } catch (error) {
    setRunStatus("critical", error.message);
    showOperatorMessage(error.message, "critical");
  }
}

async function resetRuntime() {
  try {
    await fetchJSON("/api/reset", {
      method: "POST",
      body: JSON.stringify({}),
    });

    state.runId = null;
    resetRunSurface();
    $("goalInput").value = "";
    await loadBootstrap();
  } catch (error) {
    setRunStatus("critical", error.message);
    showOperatorMessage(error.message, "critical");
  }
}

function bindPromptButtons() {
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("goalInput").value = button.dataset.prompt || "";
      $("goalInput").focus();
    });
  });
}

function bindApprovalButtons() {
  document.querySelectorAll("[data-approval]").forEach((button) => {
    button.addEventListener("click", () => {
      resolveApproval(button.dataset.approval, button.dataset.decision);
    });
  });
}

function bindModuleButtons() {
  document.querySelectorAll(".module[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".module").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");

      const target = document.getElementById(button.dataset.target);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
}

$("runButton").addEventListener("click", runWorkflow);
$("refreshButton").addEventListener("click", loadBootstrap);
$("resetButton").addEventListener("click", resetRuntime);
$("goalInput").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    runWorkflow();
  }
});

bindModuleButtons();
resetRunSurface();

loadBootstrap().catch((error) => {
  $("lastSyncLabel").textContent = "Backend offline";
  setRunStatus("critical", error.message);
  showOperatorMessage(error.message, "critical");
});
