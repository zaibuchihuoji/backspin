/**
 * backspin viewer strings. Default language is Chinese (zh); toggle with the
 * EN/中文 button in the header — the choice persists in localStorage.
 */
"use strict";

const LANG_KEY = "backspin-lang";
let LANG = "zh";
try {
  LANG = localStorage.getItem(LANG_KEY) || "zh";
} catch (e) { /* storage disabled — stay with default */ }

const STRINGS = {
  "logo.sub":        { zh: "· agent 飞行记录仪", en: "· agent flight recorder" },
  "btn.compare":     { zh: "对比…",             en: "Compare with…" },
  "btn.closeDiff":   { zh: "关闭对比",           en: "Close diff" },
  "tip.compare":     { zh: "与另一次运行对比",    en: "Compare with another run" },
  "tip.close":       { zh: "关闭",               en: "Close" },
  "tip.lang":        { zh: "切换语言 / switch language", en: "切换语言 / switch language" },
  "side.runs":       { zh: "运行记录",           en: "Runs" },
  "side.timeline":   { zh: "时间线",             en: "Timeline" },
  "side.diff":       { zh: "对比",               en: "Diff" },
  "empty.title":     { zh: "尚未选择运行",       en: "No run selected" },
  "empty.pick":      { zh: "从左侧选择一次运行,或者先录制一次:", en: "Pick a run on the left, or record one:" },
  "empty.then":      { zh: "然后运行",           en: "Then run" },
  "empty.refresh":   { zh: "并刷新本页。",       en: "and refresh." },
  "tab.request":     { zh: "请求",               en: "Request" },
  "tab.response":    { zh: "响应",               en: "Response" },
  "tab.raw":         { zh: "原始",               en: "Raw" },
  "card.agent":      { zh: "智能体",             en: "agent" },
  "card.steps":      { zh: "步骤",               en: "steps" },
  "card.llm":        { zh: "LLM 调用",           en: "llm calls" },
  "card.tools":      { zh: "工具调用",           en: "tool calls" },
  "card.tokens":     { zh: "Token 数",           en: "tokens" },
  "card.duration":   { zh: "录制步骤耗时",       en: "recorded step time" },
  "card.cost":       { zh: "预估成本",           en: "est. cost" },
  "unit.steps":      { zh: "步",                 en: "steps" },
  "unit.in":         { zh: "入",                 en: "in" },
  "unit.out":        { zh: "出",                 en: "out" },
  "timeline.title":  { zh: "时间线",             en: "Timeline" },
  "diff.pick":       { zh: "— 选择要对比的运行 —", en: "— pick a run to compare —" },
  "diff.kind":       { zh: "类型",               en: "kind" },
  "badge.same":      { zh: "相同",               en: "same" },
  "badge.diff":      { zh: "不同",               en: "DIFF" },
  "badge.solo":      { zh: "单侧",               en: "solo" },
  "banner.identical":{ zh: "完全一致。两次运行以相同顺序发起了相同的请求({n} 步)。", en: "Identical. Both runs made the same requests in the same order ({n} steps)." },
  "banner.diverged": { zh: "在第 #{n} 步分岔({kind}:{a} vs {b})。之前的步骤全部匹配。", en: "Diverged at step #{n} ({kind}: {a} vs {b}). Everything before this step matches." },
  "banner.shape":    { zh: "请求相同,但形状不同:某次运行多出或缺少了步骤。", en: "Same requests, different shape. One run has extra or missing steps." },
  "kind.llm":        { zh: "LLM",                en: "LLM" },
  "kind.tool":       { zh: "工具",               en: "tool" },
  "kind.log":        { zh: "日志",               en: "log" },
  "kind.span":       { zh: "区间",               en: "span" },
  "insp.request":    { zh: "请求",               en: "Request" },
  "insp.response":   { zh: "响应",               en: "Response" },
};

function t(key, vars) {
  let text = (STRINGS[key] && (STRINGS[key][LANG] ?? STRINGS[key].en)) || key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll("{" + k + "}", String(v));
    }
  }
  return text;
}

function applyI18n() {
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
  });
}
