"use strict";

import { api, classifyFailure, escapeHtml, forceDemoState, PanelStatus } from "./shared.js";

const columns = ["todo", "doing", "hold", "done"];
const ticket = (value) => typeof value === "string" ? { title: value } : (value || { title: "ticket" });

export class BoardsPanel {
  constructor({ onBoards }) {
    this.onBoards = onBoards;
    this.boards = new Map();
    this.status = new PanelStatus("boards-status", () => this.refresh());
  }

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
    root.replaceChildren(...Array.from(this.boards, ([agent, board]) => {
      const details = document.createElement("details");
      details.className = "agent-board";
      details.open = Boolean((board.doing || []).length);
      const total = columns.reduce((sum, column) => sum + (board[column] || []).length, 0);
      details.innerHTML = `<summary><strong>${escapeHtml(agent)}</strong><span>${total} tickets</span>${columns.map((column) => `<span>${column} ${(board[column] || []).length}</span>`).join("")}</summary><div class="board-columns">${columns.map((column) => `<section><h3>${column} <span>${(board[column] || []).length}</span></h3><ol>${(board[column] || []).map(ticket).map((item) => `<li title="${escapeHtml(item.description || item.title || "")}"><span>${escapeHtml(item.title || item.id || "ticket")}</span>${item.priority ? `<small>${escapeHtml(item.priority)}</small>` : ""}</li>`).join("")}</ol></section>`).join("")}</div>`;
      return details;
    }));
  }

  demoState(value) { forceDemoState(this.status, value); }
}
