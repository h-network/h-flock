"use strict";

import { AgentsPanel } from "./ui/agents.js";
import { AlertsPanel } from "./ui/alerts.js";
import { BoardsPanel } from "./ui/boards.js";

// Read-only Telegram Mini App view. Reuses the same panel modules the full
// console (app.js) uses — same API client, same rendering, same freshness
// states (loading/empty/error/stale/disconnected, PanelStatus in shared.js).
// What's deliberately absent is everything that writes: no LifecyclePanel,
// no MessagesPanel, no terminal workspace, no hire dialog. See mini.html's
// comment and server.py's _session_is_telegram for why that's enforced on
// the server too, not just left out of this page.

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
  try {
    tg.ready();
    tg.expand();
    const scheme = tg.colorScheme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", scheme);
    tg.onEvent?.("themeChanged", () => {
      document.documentElement.setAttribute("data-theme", tg.colorScheme === "dark" ? "dark" : "light");
    });
    tg.MainButton?.setText("Refresh");
    tg.MainButton?.onClick(() => { agents.refresh(); boards.refresh(); });
    tg.MainButton?.show();
  } catch (error) {
    // Not fatal — the page still works as a plain read-only page if the
    // SDK misbehaves; only the Telegram-native chrome (theme, MainButton)
    // is lost.
  }
}

const $ = (id) => document.getElementById(id);

const rosterCounts = { working: 0, blocked: 0 };
const updateOverview = () => {
  $("overview-working").textContent = rosterCounts.working;
  $("overview-blocked").textContent = rosterCounts.blocked;
};

const agents = new AgentsPanel({
  onSelect: () => {}, // no agent detail page here — read-only summary only
  onRoster: (counts) => {
    rosterCounts.working = counts.working || 0;
    rosterCounts.blocked = counts.blocked || 0;
    updateOverview();
  },
});
const boards = new BoardsPanel({ onBoards: (boardMap) => agents.setBoards(boardMap) });
const alerts = new AlertsPanel({ onCount: (count) => { $("overview-alerts").textContent = count; } });

async function start() {
  const config = await fetch("/client-config").then((response) => response.json());
  if (config.auth_required && !config.authenticated) {
    location.assign("/");
    return;
  }
  $("global-connection").textContent = "live";
  $("global-connection").className = "badge state-ready";
  await Promise.allSettled([agents.start(), boards.start(), alerts.start()]);
}

start().catch((error) => {
  $("global-connection").textContent = `startup failed: ${error.message}`;
  $("global-connection").className = "badge state-error";
});
