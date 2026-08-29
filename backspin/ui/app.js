/* backspin viewer — zero-dependency, zero-build. 中文/EN via i18n.js. */
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

applyI18n();
$("#btn-lang").addEventListener("click", () => {
  const next = LANG === "zh" ? "en" : "zh";
  try { localStorage.setItem(LANG_KEY, next); } catch (e) { /* ignore */ }
  location.reload();
});

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
  if (window.__BACKSPIN_EMBED__) {
    state.runs = [window.__BACKSPIN_EMBED__];
  } else {
    state.runs = await api("/api/runs");
  }
  const ul = $("#run-list");
  ul.innerHTML = "";
  for (const r of state.runs) {
    const li = document.createElement("li");
    li.dataset.name = r.name;
    const totals = r.totals || {};
    li.innerHTML = `
      <div class="name">${esc(r.name)}</div>
      <div class="meta">${esc(r.agent || "?")} · ${totals.steps ?? "?"} ${t("unit.steps")} · ${totals.total_tokens ?? "?"} tok · ${esc(fmtDate(r.created_at))}</div>`;
    li.addEventListener("click", () => selectRun(r.name));
    ul.appendChild(li);
  }
  const diffSelect = $("#diff-select");
  diffSelect.innerHTML =
    `<option value="">${esc(t("diff.pick"))}</option>` +
    state.runs.map((r) => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join("");
}

function markActiveRun() {
  document.querySelectorAll("#run-list li").forEach((li) => {
    li.classList.toggle("active", state.current && li.dataset.name === state.current.name);
  });
}

/* ---------- run view ---------- */

async function selectRun(name) {
  if (window.__BACKSPIN_EMBED__) {
    state.current = window.__BACKSPIN_EMBED__;
  } else {
    state.current = await api("/api/run/" + encodeURIComponent(name));
  }
  state.selectedSeq = null;
  state.compareWith = null;
  state.diff = null;
  hideInspector();
  markActiveRun();
  renderRun();
}

function renderRun() {
  const run = state.current;
  const totals = run.totals || {};
  $("#empty").hidden = true;
  $("#diff-table-wrap").hidden = true;
  $("#banner").hidden = true;
  $("#btn-diff").disabled = !!window.__BACKSPIN_EMBED__;
  $("#btn-close-diff").hidden = true;
  $("#diff-select").hidden = true;

  $("#summary").hidden = false;
  const cards = [
    card("card.agent", esc(run.agent || "?")),
    card("card.steps", totals.steps),
    card("card.llm", totals.llm_calls),
    card("card.tools", totals.tool_calls),
    card("card.tokens", `${totals.prompt_tokens ?? 0}<small>${t("unit.in")}</small> + ${totals.completion_tokens ?? 0}<small>${t("unit.out")}</small>`),
    card("card.duration", fmtMs(totals.duration_ms || 0)),
  ];
  if (totals.cost_usd != null && totals.cost_usd > 0) {
    cards.push(card("card.cost", `$${totals.cost_usd.toFixed(4)}` + (totals.cost_complete ? "" : "<small>+ partial</small>")));
  }
  $("#summary").innerHTML = cards.join("");

  $("#waterfall-wrap").hidden = false;
  $("#wf-title").textContent = `${t("timeline.title")} — ${run.name}`;
  renderWaterfall(run.events);
}

function card(key, v) {
  return `<div class="card"><div class="k">${esc(t(key))}</div><div class="v">${v}</div></div>`;
}

function renderWaterfall(events) {
  const wf = $("#waterfall");
  const visible = events.filter(
    (e) => !(e.kind === "span" && e.phase === "enter")
  );
  const maxDur = Math.max(1, ...visible.map((e) => e.duration_ms || 0));
  wf.innerHTML = "";
  for (const ev of visible) {
    const row = document.createElement("div");
    const kind = ev.kind || "custom";
    row.className = `row kind-${kind}` + (ev.error ? " error" : "");
    row.dataset.seq = ev.seq;
    const label =
      kind === "llm" ? ev.model || "llm"
      : kind === "tool" ? ev.name || "tool"
      : kind === "span" ? (ev.phase === "exit" ? "↳ " : "") + (ev.name || "span")
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
    row.style.marginLeft = (ev.depth || 0) * 16 + "px";
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
  const kindLabel = { llm: t("kind.llm"), tool: t("kind.tool"), span: t("kind.span"), log: t("kind.log") }[kind] || kind;
  const title =
    kind === "llm" ? `#${ev.seq} ${t("kind.llm")} · ${ev.model || "?"}`
    : kind === "tool" ? `#${ev.seq} ${t("kind.tool")} · ${ev.name || "?"}`
    : `#${ev.seq} ${kindLabel}`;
  $("#insp-title").textContent = title;
  const bits = [];
  if (ev.duration_ms != null) bits.push(fmtMs(ev.duration_ms));
  if (ev.usage) bits.push(`${ev.usage.prompt_tokens} ${t("unit.in")} / ${ev.usage.completion_tokens} ${t("unit.out")}`);
  if (ev.fingerprint) bits.push("fp " + ev.fingerprint);
  if (ev.error) bits.push("ERROR: " + ev.error);
  $("#insp-meta").textContent = bits.join(" · ");

  const tabs = ["request", "response"].filter((tb) => ev[tb] != null);
  document.querySelectorAll("#insp-tabs .tab").forEach((btn) => {
    const tb = btn.dataset.tab;
    btn.style.display = tb === "raw" || tabs.includes(tb) ? "" : "none";
    if (tb !== "raw" && !tabs.includes(tb) && state.tab === tb) state.tab = "raw";
    btn.classList.toggle("active", tb === state.tab);
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
    banner.innerHTML = `<b>${esc(t("badge.same"))}.</b> ` + esc(
      t("banner.identical", { n: rep.a.totals.steps }));
  } else if (rep.first_divergence != null) {
    banner.classList.remove("ok");
    const s = rep.steps[rep.first_divergence];
    banner.innerHTML = `<b>${t("banner.diverged", {
      n: rep.first_divergence,
      kind: esc(s.kind),
      a: esc(s.a ? s.a.label : "—"),
      b: esc(s.b ? s.b.label : "—"),
    })}</b>`;
  } else {
    banner.classList.remove("ok");
    banner.textContent = t("banner.shape");
  }

  const table = $("#diff-table");
  const rows = rep.steps.map((s) => {
    const la = s.a ? `${s.a.label} · ${fmtMs(s.a.duration_ms)}` : "—";
    const lb = s.b ? `${s.b.label} · ${fmtMs(s.b.duration_ms)}` : "—";
    const badge = s.same === true ? `<span class="badge-yes">${esc(t("badge.same"))}</span>`
      : s.same === false ? `<span class="badge-no">${esc(t("badge.diff"))}</span>`
      : `<span class="badge-solo">${esc(t("badge.solo"))}</span>`;
    const cls = s.same === false ? "diverged" : (s.same == null ? "solo" : "");
    return `<tr class="${cls}"><td>#${s.index}</td><td>${esc(s.kind)}</td><td>${esc(la)}</td><td>${esc(lb)}</td><td>${badge}</td></tr>`;
  }).join("");
  const ta = rep.a.totals, tb = rep.b.totals;
  table.innerHTML = `
    <thead><tr><th>#</th><th>${esc(t("diff.kind"))}</th><th>${esc(a)}</th><th>${esc(b)}</th><th></th></tr></thead>
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
