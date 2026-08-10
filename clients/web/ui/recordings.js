"use strict";

import { api, escapeHtml, relativeTime, absoluteTime } from "./shared.js";

export async function renderRecordingsSection(container, status) {
  if (!container) return;
  status?.loading("Loading recordings…");

  try {
    const recordings = await api("/recordings");
    status?.ready(`${recordings.length} recordings`);
    displayRecordingsList(container, recordings, status);
  } catch (error) {
    status?.error(error);
    container.innerHTML = `<div class="filtered-empty"><p class="form-error">Failed to load recordings: ${escapeHtml(error.message)}</p></div>`;
  }
}

function displayRecordingsList(container, recordings, status) {
  if (!recordings || recordings.length === 0) {
    container.innerHTML = `
      <div class="empty-office" style="margin: var(--space-4);">
        <div>
          <p class="eyebrow">Terminal Recordings</p>
          <h2>No Terminal Session Recordings</h2>
          <p>Operator terminal session recordings are saved here when recording is enabled on active agent terminal windows.</p>
        </div>
      </div>
    `;
    return;
  }

  const formatSize = (bytes) => {
    if (!bytes || bytes <= 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const rowsHtml = recordings.map((rec) => {
    const isTruncated = Boolean(rec.truncated);
    const badgeClass = isTruncated ? "state-stale" : "state-ready";
    const badgeText = isTruncated ? "Capped (Truncated)" : "Complete";
    const formattedSize = formatSize(rec.size_bytes);

    return `
      <tr class="recording-row">
        <td><code style="font-family: var(--font-mono); font-size: var(--text-xs);">${escapeHtml(rec.id)}</code></td>
        <td><strong>${escapeHtml(rec.agent)}</strong></td>
        <td><time datetime="${escapeHtml(rec.created_at)}" title="${escapeHtml(absoluteTime(rec.created_at))}">${escapeHtml(relativeTime(rec.created_at))}</time></td>
        <td style="font-variant-numeric: tabular-nums; text-align: right;">${rec.frame_count ?? 0} frames</td>
        <td style="font-variant-numeric: tabular-nums; text-align: right;">${formattedSize}</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
        <td style="text-align: right;">
          <button type="button" class="quiet-button view-rec-btn" data-id="${escapeHtml(rec.id)}">Replay</button>
        </td>
      </tr>
    `;
  }).join("");

  container.innerHTML = `
    <div style="padding: var(--space-4);">
      <header style="margin-bottom: var(--space-4); display: flex; justify-content: space-between; align-items: center;">
        <div>
          <h2 style="font-size: var(--text-xl);">Terminal Session Recordings</h2>
          <p style="color: var(--text-secondary); font-size: var(--text-sm);">Server-side recorded operator session streams with timing controls</p>
        </div>
      </header>
      <div style="overflow-x: auto; border: var(--panel-border); border-radius: var(--radius-lg); background: var(--surface-panel);">
        <table style="width: 100%; border-collapse: collapse; font-size: var(--text-sm);">
          <thead>
            <tr style="border-bottom: var(--panel-border); background: var(--surface-subtle); text-align: left; color: var(--text-secondary);">
              <th style="padding: var(--space-3);">Recording ID</th>
              <th style="padding: var(--space-3);">Agent</th>
              <th style="padding: var(--space-3);">Recorded</th>
              <th style="padding: var(--space-3); text-align: right;">Frames</th>
              <th style="padding: var(--space-3); text-align: right;">Size</th>
              <th style="padding: var(--space-3);">Status</th>
              <th style="padding: var(--space-3); text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.querySelectorAll(".view-rec-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const recId = btn.getAttribute("data-id");
      openReplayModal(recId, status);
    });
  });
}

async function openReplayModal(recId, status) {
  let dialog = document.getElementById("replay-modal");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "replay-modal";
    dialog.className = "dialog-shell";
    document.body.appendChild(dialog);
  }

  dialog.innerHTML = `<div style="padding: var(--space-4);">Loading recording details…</div>`;
  dialog.showModal();

  try {
    const data = await api(`/recordings/${recId}`);
    const frames = data.frames || data.chunks || [];
    const isTruncated = Boolean(data.truncated);
    const truncateNotice = isTruncated
      ? `<div style="padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); border-radius: var(--radius-md); background: var(--warning-soft); color: var(--warning); font-size: var(--text-xs);">
           ⚠ Recording capped: ${escapeHtml(data.truncate_reason || "maximum size limit reached")} at ${escapeHtml(relativeTime(data.truncated_at))}
         </div>`
      : "";

    dialog.innerHTML = `
      <header>
        <div>
          <h2>Session Replay: ${escapeHtml(data.agent || recId)}</h2>
          <p style="font-size: var(--text-xs); color: var(--text-secondary);">${frames.length} frames · ${escapeHtml(absoluteTime(data.created_at || data.start_ts))}</p>
        </div>
        <button type="button" id="close-replay-btn" class="quiet-button">✕ Close</button>
      </header>
      ${truncateNotice}
      <div style="background: #000; color: #00ff66; padding: var(--space-3); border-radius: var(--radius-md); font-family: var(--font-mono); height: 18rem; overflow: auto; white-space: pre-wrap;" id="replay-screen">
        Select Play to begin playback…
      </div>
      <footer style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);">
        <div style="display: flex; gap: var(--space-2);">
          <button type="button" id="play-replay-btn" class="quiet-button">▶ Play</button>
          <button type="button" id="step-replay-btn" class="quiet-button">⏭ Step</button>
        </div>
        <div id="replay-progress" style="font-size: var(--text-xs); color: var(--text-secondary); font-variant-numeric: tabular-nums;">
          0 / ${frames.length} frames
        </div>
      </footer>
    `;

    document.getElementById("close-replay-btn")?.addEventListener("click", () => dialog.close());

    let frameIndex = 0;
    let isPlaying = false;
    let playTimer = null;
    const screen = document.getElementById("replay-screen");
    const progress = document.getElementById("replay-progress");
    const playBtn = document.getElementById("play-replay-btn");

    const renderFrame = () => {
      if (frameIndex >= frames.length) {
        isPlaying = false;
        clearInterval(playTimer);
        if (playBtn) playBtn.textContent = "▶ Replay";
        return;
      }
      const frame = frames[frameIndex];
      const frameText = typeof frame === "string" ? frame : (frame.data || JSON.stringify(frame));
      screen.textContent += frameText;
      screen.scrollTop = screen.scrollHeight;
      frameIndex += 1;
      if (progress) progress.textContent = `${frameIndex} / ${frames.length} frames`;
    };

    playBtn?.addEventListener("click", () => {
      if (isPlaying) {
        isPlaying = false;
        clearInterval(playTimer);
        playBtn.textContent = "▶ Play";
      } else {
        if (frameIndex >= frames.length) {
          frameIndex = 0;
          screen.textContent = "";
        }
        isPlaying = true;
        playBtn.textContent = "⏸ Pause";
        playTimer = setInterval(renderFrame, 200);
      }
    });

    document.getElementById("step-replay-btn")?.addEventListener("click", () => {
      if (isPlaying) {
        isPlaying = false;
        clearInterval(playTimer);
        if (playBtn) playBtn.textContent = "▶ Play";
      }
      renderFrame();
    });

  } catch (error) {
    dialog.innerHTML = `
      <header><h2>Replay Error</h2><button type="button" onclick="this.closest('dialog').close()" class="quiet-button">✕</button></header>
      <div style="padding: var(--space-4);" class="form-error">Failed to load recording replay: ${escapeHtml(error.message)}</div>
    `;
  }
}
