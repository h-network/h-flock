"use strict";

import { api, escapeHtml, relativeTime, absoluteTime } from "./shared.js";

let currentQuery = "";
let currentEvent = "";
let currentOffset = 0;
const currentLimit = 50;

export async function renderAuditSection(container, status) {
  if (!container) return;
  status?.loading("Loading audit log…");
  await loadAndRenderAudit(container, status);
}

async function loadAndRenderAudit(container, status) {
  try {
    const params = new URLSearchParams({
      limit: String(currentLimit),
      offset: String(currentOffset),
    });
    if (currentQuery) params.set("q", currentQuery);
    if (currentEvent) params.set("event", currentEvent);

    const data = await api(`/audit?${params.toString()}`);
    status?.ready(`${data.total || 0} audit records`);
    displayAuditList(container, data, status);
  } catch (error) {
    status?.error(error);
    container.innerHTML = `<div class="filtered-empty"><p class="form-error">Failed to load audit log: ${escapeHtml(error.message)}</p></div>`;
  }
}

function displayAuditList(container, data, status) {
  const records = data.records || [];
  const total = data.total || 0;
  const offset = data.offset || 0;
  const limit = data.limit || currentLimit;

  const eventBadges = {
    login_success: "state-ready",
    login_failure: "state-error",
    logout: "state-stale",
    operator_action: "state-loading",
    recording_created: "state-ready",
    recording_truncated: "state-stale",
  };

  const rowsHtml = records.length === 0
    ? `<tr><td colspan="6" class="filtered-empty">No audit log records match the current filter.</td></tr>`
    : records.map((rec, idx) => {
        const eventName = rec.event || "unknown";
        const badgeClass = eventBadges[eventName] || "state-empty";
        const detailsObj = rec.details || {};
        const detailsSummary = typeof detailsObj === "string" ? detailsObj : (detailsObj.kind || detailsObj.reason || JSON.stringify(detailsObj));
        const rowId = `audit-detail-${idx}`;

        return `
          <tr class="recording-row">
            <td><time datetime="${escapeHtml(rec.timestamp)}" title="${escapeHtml(absoluteTime(rec.timestamp))}">${escapeHtml(relativeTime(rec.timestamp))}</time></td>
            <td><span class="badge ${badgeClass}">${escapeHtml(eventName)}</span></td>
            <td><code style="font-family: var(--font-mono); font-size: var(--text-xs);">${escapeHtml(rec.session_id || "unauthenticated")}</code></td>
            <td><span style="font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-secondary);">${escapeHtml(rec.client_ip || "127.0.0.1")}</span></td>
            <td><span style="font-size: var(--text-sm); font-weight: 500;">${escapeHtml(detailsSummary)}</span></td>
            <td style="text-align: right;">
              <button type="button" class="quiet-button toggle-detail-btn" data-target="${rowId}">JSON</button>
            </td>
          </tr>
          <tr id="${rowId}" hidden style="background: var(--surface-subtle);">
            <td colspan="6" style="padding: var(--space-3);">
              <pre style="margin: 0; font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-primary); white-space: pre-wrap;">${escapeHtml(JSON.stringify(rec, null, 2))}</pre>
            </td>
          </tr>
        `;
      }).join("");

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + limit, total);

  container.innerHTML = `
    <div style="padding: var(--space-4);">
      <header style="margin-bottom: var(--space-4); display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--space-3);">
        <div>
          <h2 style="font-size: var(--text-xl);">Operator Action Log</h2>
          <p style="color: var(--text-secondary); font-size: var(--text-sm);">Log of operator actions, authentications, and session events performed through the console proxy. (Direct API token traffic to /agents/... bypasses the console proxy and is recorded in tenant activity logs.)</p>
        </div>
        <div style="display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap;">
          <input type="search" id="audit-search-input" placeholder="Search operator log…" value="${escapeHtml(currentQuery)}" style="min-width: 14rem; height: var(--control-height);" />
          <select id="audit-event-filter" style="height: var(--control-height);">
            <option value="" ${currentEvent === "" ? "selected" : ""}>All Events</option>
            <option value="login_success" ${currentEvent === "login_success" ? "selected" : ""}>login_success</option>
            <option value="login_failure" ${currentEvent === "login_failure" ? "selected" : ""}>login_failure</option>
            <option value="operator_action" ${currentEvent === "operator_action" ? "selected" : ""}>operator_action</option>
            <option value="logout" ${currentEvent === "logout" ? "selected" : ""}>logout</option>
            <option value="recording_created" ${currentEvent === "recording_created" ? "selected" : ""}>recording_created</option>
            <option value="recording_truncated" ${currentEvent === "recording_truncated" ? "selected" : ""}>recording_truncated</option>
          </select>
        </div>
      </header>

      <div style="overflow-x: auto; border: var(--panel-border); border-radius: var(--radius-lg); background: var(--surface-panel); margin-bottom: var(--space-4);">
        <table style="width: 100%; border-collapse: collapse; font-size: var(--text-sm);">
          <thead>
            <tr style="border-bottom: var(--panel-border); background: var(--surface-subtle); text-align: left; color: var(--text-secondary);">
              <th style="padding: var(--space-3);">Time</th>
              <th style="padding: var(--space-3);">Event</th>
              <th style="padding: var(--space-3);">Session ID</th>
              <th style="padding: var(--space-3);">Client IP</th>
              <th style="padding: var(--space-3);">Details Summary</th>
              <th style="padding: var(--space-3); text-align: right;">Payload</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>

      <footer style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); font-size: var(--text-sm); color: var(--text-secondary);">
        <div>Showing ${pageStart}–${pageEnd} of ${total} records</div>
        <div style="display: flex; gap: var(--space-2);">
          <button type="button" id="audit-prev-btn" class="quiet-button" ${offset === 0 ? "disabled" : ""}>← Previous</button>
          <button type="button" id="audit-next-btn" class="quiet-button" ${offset + limit >= total ? "disabled" : ""}>Next →</button>
        </div>
      </footer>
    </div>
  `;

  // Filter events
  document.getElementById("audit-search-input")?.addEventListener("change", (e) => {
    currentQuery = e.target.value.trim();
    currentOffset = 0;
    loadAndRenderAudit(container, status);
  });

  document.getElementById("audit-event-filter")?.addEventListener("change", (e) => {
    currentEvent = e.target.value;
    currentOffset = 0;
    loadAndRenderAudit(container, status);
  });

  document.getElementById("audit-prev-btn")?.addEventListener("click", () => {
    if (currentOffset > 0) {
      currentOffset = Math.max(0, currentOffset - currentLimit);
      loadAndRenderAudit(container, status);
    }
  });

  document.getElementById("audit-next-btn")?.addEventListener("click", () => {
    if (currentOffset + currentLimit < total) {
      currentOffset += currentLimit;
      loadAndRenderAudit(container, status);
    }
  });

  container.querySelectorAll(".toggle-detail-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      const row = document.getElementById(targetId);
      if (row) {
        row.hidden = !row.hidden;
        btn.textContent = row.hidden ? "JSON" : "Hide";
      }
    });
  });
}
