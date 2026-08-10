"use strict";

export class CommandPalette {
  constructor({ commands }) {
    this.commands = commands;
    this.dialog = document.getElementById("command-dialog");
    this.input = document.getElementById("command-input");
    this.results = document.getElementById("command-results");
    this.active = 0;
    this.input.oninput = () => this.render();
    this.input.onkeydown = (event) => this.keydown(event);
  }

  open(query = "") {
    this.input.value = query;
    this.active = 0;
    this.render();
    this.dialog.showModal();
    this.input.focus();
  }

  matches() {
    const query = this.input.value.trim().toLowerCase();
    return this.commands().filter((command) => !query || `${command.label} ${command.keywords || ""}`.toLowerCase().includes(query)).slice(0, 30);
  }

  render() {
    const commands = this.matches();
    this.active = Math.min(this.active, Math.max(0, commands.length - 1));
    this.results.replaceChildren(...commands.map((command, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.className = index === this.active ? "active" : "";
      button.innerHTML = `<span>${command.label}</span><small>${command.hint || ""}</small>`;
      button.onclick = () => { this.dialog.close(); command.run(); };
      item.append(button);
      return item;
    }));
    document.getElementById("command-empty").hidden = commands.length !== 0;
  }

  keydown(event) {
    const commands = this.matches();
    if (event.key === "ArrowDown") this.active = Math.min(commands.length - 1, this.active + 1);
    else if (event.key === "ArrowUp") this.active = Math.max(0, this.active - 1);
    else if (event.key === "Enter" && commands[this.active]) {
      event.preventDefault();
      this.dialog.close();
      commands[this.active].run();
      return;
    } else return;
    event.preventDefault();
    this.render();
    this.results.querySelector("button.active")?.scrollIntoView({ block: "nearest" });
  }
}
