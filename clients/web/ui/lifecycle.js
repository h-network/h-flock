"use strict";

import { api, PanelStatus } from "./shared.js";

const NAME = /^(?![0-9]+$)[a-z0-9][a-z0-9-]{0,62}$/;
const RESERVED = new Set(["all", "pod", "tenant", "agent"]);

export class LifecyclePanel {
  constructor({ agents }) {
    this.agents = agents;
    this.selected = "";
    this.status = new PanelStatus("lifecycle-status", () => {});
    this.status.empty("Select an agent");
    this.bind();
  }

  bind() {
    document.getElementById("hire-agent").onclick = () => document.getElementById("hire-dialog").showModal();
    document.getElementById("hire-form").onsubmit = (event) => this.hire(event);
    document.getElementById("pause-agent").onclick = () => this.control("PauseAgent", "Pause accepted · messages will queue until resume");
    document.getElementById("resume-agent").onclick = () => this.control("ResumeAgent", "Resume accepted · queued messages will drain");
    document.getElementById("retire-agent").onclick = () => this.openRetire();
    document.getElementById("retire-form").onsubmit = (event) => this.retire(event);
    document.getElementById("retire-confirm").oninput = (event) => {
      document.getElementById("retire-confirm-button").disabled = event.target.value !== this.selected;
    };
    for (const button of document.querySelectorAll("[data-close-dialog]")) {
      button.onclick = () => document.getElementById(button.dataset.closeDialog).close();
    }
  }

  select(agent) {
    this.selected = agent;
    const tmux = this.agents.detail(agent)?.port_type === "tmux";
    for (const id of ["pause-agent", "resume-agent", "retire-agent"]) document.getElementById(id).disabled = !tmux;
    this.status.ready(tmux ? "Lifecycle controls ready" : "Lifecycle applies to tmux agents");
  }

  validName(value) {
    return NAME.test(value) && !RESERVED.has(value);
  }

  async hire(event) {
    event.preventDefault();
    const agent = document.getElementById("hire-name").value.trim();
    const error = document.getElementById("hire-error");
    if (!this.validName(agent)) {
      error.textContent = "Use lowercase letters, digits and hyphens; do not use a reserved or all-digit name.";
      return;
    }
    const payload = { agent, port_type: "tmux", cli: document.getElementById("hire-cli").value };
    const profile = document.getElementById("hire-profile").value.trim();
    if (profile) payload.profile = profile;
    try {
      await this.send("StartAgent", payload);
      this.agents.addPending(agent);
      document.getElementById("hire-dialog").close();
      document.getElementById("hire-form").reset();
      error.textContent = "";
      this.status.ready(`Hire accepted for ${agent} · waiting for roster and window`);
    } catch (failure) { error.textContent = failure.message; }
  }

  openRetire() {
    document.getElementById("retire-name-label").textContent = this.selected;
    document.getElementById("retire-confirm-label").textContent = this.selected;
    document.getElementById("retire-confirm").value = "";
    document.getElementById("retire-confirm-button").disabled = true;
    document.getElementById("retire-error").textContent = "";
    document.getElementById("retire-dialog").showModal();
  }

  async retire(event) {
    event.preventDefault();
    if (document.getElementById("retire-confirm").value !== this.selected) return;
    try {
      await this.send("StopAgent", { agent: this.selected });
      document.getElementById("retire-dialog").close();
      this.status.ready(`Retire accepted for ${this.selected} · queues and boards retained`);
    } catch (failure) { document.getElementById("retire-error").textContent = failure.message; }
  }

  async control(kind, message) {
    try { await this.send(kind, { agent: this.selected }); this.status.ready(message); }
    catch (error) { this.status.error(error); }
  }

  send(kind, payload) {
    return api("/agents/host/envelopes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, payload }) });
  }
}
