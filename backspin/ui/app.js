/* backspin viewer — zero-dependency, zero-build. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  runs: [],
  current: null,     // run summary+events
  compareWith: null, // run name for diff
  diff: null,        // diff report
  selectedSeq: null,
  tab: "raw",
};

/* ---------- utilities ---------- */

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmtMs(ms) {
  return ms >= 1000 ? (ms / 1000).toFixed(2) + "s" : Math.round(ms) + "ms";
}

function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function jsonBlock(obj) {
  return JSON.stringify(obj, null, 2) ?? "null";
}

/* ---------- sidebar ---------- */

async function loadRuns() {
  state.runs = await api("/api/runs");
  const ul = $("#run-list");
  ul.innerHTML = "";
  for (const r of state.runs) {
    const li = document.createElement("li");
    li.dataset.name = r.name;
    const t = r.totals || {};
    li.innerHTML = `
      <div class="name">${esc(r.name)}</div>
      <div class="meta">${esc(r.agent || "?")} · ${t.steps ?? "?"} steps · ${t.total_tokens ?? "?"} tok · ${esc(fmtDate(r.created_at))}</div>`;
    li.addEventListener("click", () => selectRun(r.name));
    ul.appendChild(li);
  }
  const diffSelect = $("#diff-select");
  diffSelect.innerHTML =
    `<option value="">— pick a run to compare —</option>` +
    state.runs.map((r) => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join("");
}

function markActiveRun() {
  document.querySelectorAll("#run-list li").forEach((li) => {
    li.classList.toggle("active", state.current && li.dataset.name === state.current.name);
  });
}

/* ---------- run view ---------- */

async function selectRun(name) {
  state.current = await api("/api/run/" + encodeURIComponent(name));
  state.selectedSeq = null;
  state.compareWith = null;
  state.diff = null;
  hideInspector();
  markActiveRun();
  renderRun();
}

function renderRun() {
  const run = state.current;
  const t = run.totals || {};
  $("#empty").hidden = true;
  $("#diff-table-wrap").hidden = true;
  $("#banner").hidden = true;
  $("#btn-diff").disabled = false;
  $("#btn-close-diff").hidden = true;
  $("#diff-select").hidden = true;

  $("#summary").hidden = false;
  $("#summary").innerHTML = [
    card("agent", run.agent || "?"),
    card("steps", t.steps),
    card("llm calls", t.llm_calls),
    card("tool calls", t.tool_calls),
    card("tokens", `${t.prompt_tokens ?? 0}<small>in</small> + ${t.completion_tokens ?? 0}<small>out</small>`),
    card("recorded step time", fmtMs(t.duration_ms || 0)),
  ].join("");

  $("#waterfall-wrap").hidden = false;
  $("#wf-title").textContent = `Timeline — ${run.name}`;
  renderWaterfall(run.events);
}

function card(k, v) {
  return `<div class="card"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`;
}

function renderWaterfall(events) {
  const wf = $("#waterfall");
  const maxDur = Math.max(1, ...events.map((e) => e.duration_ms || 0));
  wf.innerHTML = "";
  for (const ev of events) {
    const row = document.createElement("div");
    const kind = ev.kind || "custom";
    row.className = `row kind-${kind}` + (ev.error ? " error" : "");
    row.dataset.seq = ev.seq;
    const label =
      kind === "llm" ? ev.model || "llm"
      : kind === "tool" ? ev.name || "tool"
      : kind === "log" ? String(ev.message || "").slice(0, 60)
      : kind === "error" ? String(ev.message || "").slice(0, 60)
      : kind;
    const pct = Math.max(1.5, ((ev.duration_ms || 0) / maxDur) * 100);
    const usage = ev.usage || {};
    row.innerHTML = `
      <span class="seq">#${ev.seq}</span>
      <span class="lbl" title="${esc(label)}">${esc(label)}</span>
      <div class="track"><div class="bar" style="width:${pct}%"></div></div>
      <span class="dur">${ev.duration_ms != null ? fmtMs(ev.duration_ms) : ""}</span>
      <span class="tok">${usage.prompt_tokens != null ? usage.prompt_tokens + "+" + usage.completion_tokens : ""}</span>`;
    row.addEventListener("click", () => selectStep(ev));
    wf.appendChild(row);
  }
}

/* ---------- inspector ---------- */

function selectStep(ev) {
  state.selectedSeq = ev.seq;
  document.querySelectorAll("#waterfall .row").forEach((r) => {
    r.classList.toggle("selected", Number(r.dataset.seq) === ev.seq);
  });
  const insp = $("#inspector");
  insp.hidden = false;
  const kind = ev.kind || "custom";
  const title =
    kind === "llm" ? `#${ev.seq} LLM · ${ev.model || "?"}`
    : kind === "tool" ? `#${ev.seq} tool · ${ev.name || "?"}`
    : `#${ev.seq} ${kind}`;
  $("#insp-title").textContent = title;
  const bits = [];
  if (ev.duration_ms != null) bits.push(fmtMs(ev.duration_ms));
  if (ev.usage) bits.push(`${ev.usage.prompt_tokens} in / ${ev.usage.completion_tokens} out`);
  if (ev.fingerprint) bits.push("fp " + ev.fingerprint);
  if (ev.error) bits.push("ERROR: " + ev.error);
  $("#insp-meta").textContent = bits.join(" · ");

  const tabs = ["request", "response"].filter((t) => ev[t] != null);
  document.querySelectorAll("#insp-tabs .tab").forEach((btn) => {
    const t = btn.dataset.tab;
    btn.style.display = t === "raw" || tabs.includes(t) ? "" : "none";
    if (t !== "raw" && !tabs.includes(t) && state.tab === t) state.tab = "raw";
    btn.classList.toggle("active", t === state.tab);
  });
  renderInspectorBody(ev);
}

function renderInspectorBody(ev) {
  const body = $("#insp-body");
  if (state.tab === "raw") {
    body.textContent = jsonBlock(ev);
  } else {
    const v = ev[state.tab];
    body.textContent = v == null ? "" : jsonBlock(v);
  }
}

function hideInspector() {
  $("#inspector").hidden = true;
}

/* ---------- diff view ---------- */

async function renderDiff() {
  const a = state.current.name;
  const b = state.compareWith;
  if (!b || b === a) return;
  state.diff = await api(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const rep = state.diff;

  $("#waterfall-wrap").hidden = true;
  $("#diff-table-wrap").hidden = false;
  $("#btn-close-diff").hidden = false;
  hideInspector();

  const banner = $("#banner");
  banner.hidden = false;
  if (rep.identical) {
    banner.classList.add("ok");
    banner.innerHTML = `<b>Identical.</b> Both runs made the same requests in the same order (${rep.a.totals.steps} steps).`;
  } else if (rep.first_divergence != null) {
    banner.classList.remove("ok");
    const s = rep.steps[rep.first_divergence];
    banner.innerHTML = `<b>Diverged at step #${rep.first_divergence}</b> (${esc(s.kind)}: ` +
      `${esc(s.a ? s.a.label : "—")} vs ${esc(s.b ? s.b.label : "—")}). ` +
      `Everything before this step matches.`;
  } else {
    banner.classList.remove("ok");
    banner.innerHTML = `<b>Same requests, different shape.</b> One run has extra or missing steps.`;
  }

  const table = $("#diff-table");
  const rows = rep.steps.map((s) => {
    const la = s.a ? `${s.a.label} · ${fmtMs(s.a.duration_ms)}` : "—";
    const lb = s.b ? `${s.b.label} · ${fmtMs(s.b.duration_ms)}` : "—";
    const badge = s.same === true ? `<span class="badge-yes">same</span>`
      : s.same === false ? `<span class="badge-no">DIFF</span>`
      : `<span class="badge-solo">solo</span>`;
    const cls = s.same === false ? "diverged" : (s.same == null ? "solo" : "");
    return `<tr class="${cls}"><td>#${s.index}</td><td>${esc(s.kind)}</td><td>${esc(la)}</td><td>${esc(lb)}</td><td>${badge}</td></tr>`;
  }).join("");
  const ta = rep.a.totals, tb = rep.b.totals;
  table.innerHTML = `
    <thead><tr><th>#</th><th>kind</th><th>${esc(a)}</th><th>${esc(b)}</th><th></th></tr></thead>
    <tbody>${rows}</tbody>
    <tfoot><tr><td></td><td></td>
      <td>${ta.total_tokens} tok · ${fmtMs(ta.duration_ms)}</td>
      <td>${tb.total_tokens} tok · ${fmtMs(tb.duration_ms)}</td>
      <td></td></tr></tfoot>`;
}

function closeDiff() {
  state.compareWith = null;
  state.diff = null;
  $("#diff-select").value = "";
  renderRun();
}

/* ---------- wiring ---------- */

$("#btn-diff").addEventListener("click", () => {
  const sel = $("#diff-select");
  sel.hidden = !sel.hidden;
  if (!sel.hidden) sel.focus();
});
$("#diff-select").addEventListener("change", (e) => {
  state.compareWith = e.target.value;
  if (state.compareWith) renderDiff();
});
$("#btn-close-diff").addEventListener("click", closeDiff);
$("#insp-close").addEventListener("click", hideInspector);
document.querySelectorAll("#insp-tabs .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll("#insp-tabs .tab").forEach((b) =>
      b.classList.toggle("active", b === btn));
    if (state.current) {
      const seq = state.selectedSeq;
      const ev = (state.current.events || []).find((e) => e.seq === seq);
      if (ev) renderInspectorBody(ev);
    }
  });
});

loadRuns();
