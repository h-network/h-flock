"use strict";

import { api, classifyFailure, escapeHtml, forceDemoState, PanelStatus } from "./shared.js";

const columns = ["todo", "doing", "hold", "done"];
const ticket = (value) => typeof value === "string" ? { title: value } : (value || { title: "ticket" });

export class BoardsPanel {
  constructor({ onBoards, onResults = () => {} }) {
    this.onBoards = onBoards;
    this.onResults = onResults;
    this.filter = "";
    this.boards = new Map();
    this.status = new PanelStatus("boards-status", () => this.refresh());
  }

  setFilter(value) { this.filter = value.trim().toLowerCase(); this.render(); }

  async start() {
    this.status.loading("Loading boards…");
    await this.refresh();
    this.timer = setInterval(() => this.refresh(), 10000);
  }

  async refresh() {
    try {
      const value = await api("/board");
      this.boards = new Map((value.agents || []).map((board) => [board.agent, board]));
      const count = Array.from(this.boards.values()).reduce((sum, board) => sum + columns.reduce((n, column) => n + (board[column] || []).length, 0), 0);
      if (count) this.status.ready(`${count} tickets`);
      else this.status.empty("No open or completed tickets");
      this.render();
      this.onBoards(this.boards);
    } catch (error) { classifyFailure(this.status, error, this.boards.size > 0); }
  }

  render() {
    const root = document.getElementById("boards");
    let resultCount = 0;
    const rendered = Array.from(this.boards, ([agent, board]) => {
      const filtered = Object.fromEntries(columns.map((column) => [column, (board[column] || []).filter((value) => {
        const item = ticket(value);
        return !this.filter || `${agent} ${column} ${item.id || ""} ${item.title || ""} ${item.description || ""}`.toLowerCase().includes(this.filter);
      })]));
      const matching = columns.reduce((sum, column) => sum + filtered[column].length, 0);
      if (this.filter && !matching && !agent.toLowerCase().includes(this.filter)) return null;
      resultCount += matching;
      const details = document.createElement("details");
      details.className = "agent-board";
      details.open = Boolean(filtered.doing.length || this.filter);
      const total = columns.reduce((sum, column) => sum + filtered[column].length, 0);
      details.innerHTML = `<summary><strong>${escapeHtml(agent)}</strong><span>${total} tickets</span>${columns.map((column) => `<span>${column} ${filtered[column].length}</span>`).join("")}</summary><div class="board-columns">${columns.map((column) => `<section><h3>${column} <span>${filtered[column].length}</span></h3><ol>${filtered[column].map(ticket).map((item) => `<li title="${escapeHtml(item.description || item.title || "")}"><span>${escapeHtml(item.title || item.id || "ticket")}</span>${item.priority ? `<small>${escapeHtml(item.priority)}</small>` : ""}</li>`).join("")}</ol></section>`).join("")}</div>`;
      return details;
    }).filter(Boolean);
    this.onResults(resultCount);
    if (!rendered.length && this.filter) root.innerHTML = `<p class="filtered-empty">No board tickets match “${escapeHtml(this.filter)}”</p>`;
    else root.replaceChildren(...rendered);
  }

  renderAgent(agent) {
    const root = document.getElementById("agent-board");
    const board = this.boards.get(agent);
    if (!root) return;
    if (!board) {
      root.innerHTML = `<div class="empty-state"><h3>No board activity</h3><p>${escapeHtml(agent)} has no tickets yet.</p></div>`;
      return;
    }
    root.innerHTML = `<div class="board-columns">${columns.map((column) => {
      const items = (board[column] || []).map(ticket);
      return `<section><h3>${column} <span>${items.length}</span></h3><ol>${items.map((item) => `<li title="${escapeHtml(item.description || item.title || "")}"><span>${escapeHtml(item.title || item.id || "ticket")}</span>${item.priority ? `<small>${escapeHtml(item.priority)}</small>` : ""}</li>`).join("")}</ol></section>`;
    }).join("")}</div>`;
  }

  demoState(value) { forceDemoState(this.status, value); }
}
