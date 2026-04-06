const state = {
  runId: null,
  dashboard: null,
  result: null,
};

const $ = (id) => document.getElementById(id);

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

function metricTile(metric) {
  return `
    <div class="metric-tile">
      <span class="eyebrow">${metric.label}</span>
      <strong class="metric-value">${metric.value}</strong>
    </div>
  `;
}

function statusPill(step) {
  return `<span class="status-pill ${step.tone}">${step.status.replaceAll("_", " ")}</span>`;
}

function renderDashboard(dashboard) {
  state.dashboard = dashboard;
  $("qualifiedCount").textContent = dashboard.kpis.qualified_leads;
  $("kpiStrip").innerHTML = `
    <div class="kpi-tile"><span class="eyebrow">Open pipeline</span><strong class="kpi-value">$${dashboard.kpis.open_pipeline_usd.toLocaleString()}</strong></div>
    <div class="kpi-tile"><span class="eyebrow">Qualified leads</span><strong class="kpi-value">${dashboard.kpis.qualified_leads}</strong></div>
    <div class="kpi-tile"><span class="eyebrow">Active campaigns</span><strong class="kpi-value">${dashboard.kpis.active_campaigns}</strong></div>
    <div class="kpi-tile"><span class="eyebrow">Pending approvals</span><strong class="kpi-value">${dashboard.kpis.pending_approvals}</strong></div>
  `;

  $("accountList").innerHTML = dashboard.accounts
    .map(
      (account) => `
        <button class="account-item" data-prompt="Advance ${account.name} toward close and create the next follow-up task.">
          <strong>${account.name}</strong>
          <div class="account-meta">${account.industry} · ${account.region}</div>
        </button>
      `
    )
    .join("");

  $("samplePrompts").innerHTML = dashboard.sample_prompts
    .map((prompt) => `<button class="prompt-chip" data-prompt="${prompt}">${prompt}</button>`)
    .join("");

  renderRuntimeSummary(dashboard.runtime);
  bindPromptButtons();
}

function renderRuntimeSummary(runtime) {
  $("runtimeSummary").innerHTML = `
    <div class="runtime-grid">
      <div class="runtime-box"><span class="eyebrow">Tasks</span><strong class="metric-value">${runtime.tasks}</strong></div>
      <div class="runtime-box"><span class="eyebrow">Emails</span><strong class="metric-value">${runtime.emails}</strong></div>
      <div class="runtime-box"><span class="eyebrow">Notes</span><strong class="metric-value">${runtime.notes}</strong></div>
      <div class="runtime-box"><span class="eyebrow">Discounts</span><strong class="metric-value">${runtime.discount_requests}</strong></div>
    </div>
  `;
}

function renderResult(result) {
  state.result = result;
  $("routeLabel").textContent = result.route;
  $("nextAction").textContent = result.next_action;
  $("nextAction").className = `status-pill ${result.approvals.length ? "warning" : "active"}`;

  const contextParts = [];
  if (result.context.account) {
    const account = result.context.account;
    contextParts.push(`<div><strong>${account.name}</strong><p>${account.industry} · ${account.region} · ${account.employees} employees</p></div>`);
  }
  if (result.context.lead) {
    const lead = result.context.lead;
    contextParts.push(`<div><strong>${lead.contact_name}</strong><p>${lead.role} · source ${lead.source}</p></div>`);
  }
  if (result.context.deal) {
    const deal = result.context.deal;
    contextParts.push(`<div><strong>$${deal.amount_usd.toLocaleString()}</strong><p>${deal.stage} · closes ${deal.close_date}</p></div>`);
  }
  $("contextBlock").innerHTML = contextParts.length
    ? `<div class="context-grid">${contextParts.join("")}</div>`
    : `<p>No account context for this run yet.</p>`;

  $("planList").innerHTML = result.steps
    .map(
      (step) => `
        <div class="plan-step">
          <div class="plan-step-head">
            <strong>${step.label}</strong>
            ${statusPill(step)}
          </div>
          <p>${step.detail}</p>
        </div>
      `
    )
    .join("");

  $("metricGrid").innerHTML = result.metrics.length
    ? result.metrics.map(metricTile).join("")
    : `<div class="empty-state">No metrics for this run yet.</div>`;

  $("insightList").innerHTML = result.insights.length
    ? result.insights.map((item) => `<div class="insight-item">${item}</div>`).join("")
    : `<div class="empty-state">No insights yet.</div>`;

  $("draftList").innerHTML = result.drafts.length
    ? result.drafts
        .map(
          (draft) => `
            <div class="draft-card">
              <div class="draft-head">
                <strong>${draft.subject}</strong>
                <span class="mini-badge">${draft.recipient}</span>
              </div>
              <pre>${draft.body}</pre>
            </div>
          `
        )
        .join("")
    : `<div class="empty-state">No drafts generated for this run.</div>`;

  $("approvalCount").textContent = result.approvals.length;
  $("approvalList").innerHTML = result.approvals.length
    ? result.approvals
        .map(
          (approval) => `
            <div class="approval-card">
              <strong>${approval.title}</strong>
              <p>${approval.description}</p>
              <pre>${JSON.stringify(approval.payload, null, 2)}</pre>
              <div class="approval-actions">
                <button class="decision-button approve" data-approval="${approval.id}" data-decision="approve">Approve</button>
                <button class="decision-button reject" data-approval="${approval.id}" data-decision="reject">Reject</button>
              </div>
            </div>
          `
        )
        .join("")
    : `<div class="empty-state">No approvals waiting.</div>`;

  $("activityList").innerHTML = result.activity.length
    ? result.activity.map((item) => `<div class="activity-item"><strong>${item.type}</strong><p>${item.message}</p></div>`).join("")
    : `<div class="empty-state">No activity recorded yet.</div>`;

  renderRuntimeSummary(result.runtime);
  bindApprovalButtons();
}

async function loadBootstrap() {
  const payload = await fetchJSON("/api/bootstrap");
  renderDashboard(payload.dashboard);
}

async function runWorkflow() {
  const prompt = $("goalInput").value.trim();
  if (!prompt) return;
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
  } finally {
    $("runButton").textContent = "Run Workflow";
  }
}

async function resolveApproval(approvalId, decision) {
  if (!state.runId) return;
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
}

async function resetRuntime() {
  await fetchJSON("/api/reset", {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.runId = null;
  state.result = null;
  $("routeLabel").textContent = "Awaiting goal";
  $("nextAction").textContent = "Waiting for input";
  $("nextAction").className = "status-pill neutral";
  $("contextBlock").innerHTML = `<p>No account context for this run yet.</p>`;
  $("planList").innerHTML = `<div class="plan-list empty-state">Run a goal to see the execution plan.</div>`;
  $("metricGrid").innerHTML = "";
  $("insightList").innerHTML = `<div class="empty-state">No insights yet.</div>`;
  $("draftList").innerHTML = `<div class="empty-state">No drafts generated for this run.</div>`;
  $("approvalList").innerHTML = `<div class="empty-state">No approvals waiting.</div>`;
  $("activityList").innerHTML = `<div class="empty-state">No workflow has run yet.</div>`;
  await loadBootstrap();
}

function bindPromptButtons() {
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("goalInput").value = button.dataset.prompt;
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

$("runButton").addEventListener("click", runWorkflow);
$("refreshButton").addEventListener("click", loadBootstrap);
$("resetButton").addEventListener("click", resetRuntime);

loadBootstrap().catch((error) => {
  console.error(error);
  $("activityList").innerHTML = `<div class="empty-state">${error.message}</div>`;
});
