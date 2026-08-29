/**
 * diffRuns: align two runs step by step and find the first divergence.
 */
import { Run, canonicalJson, loadRun } from "./runfile.js";

export interface StepDiff {
  index: number;
  kind: string;
  a: string | null;
  b: string | null;
  same: boolean | null;
}

export interface DiffReport {
  identical: boolean;
  firstDivergence: number | null;
  steps: StepDiff[];
  totalsA: Record<string, number>;
  totalsB: Record<string, number>;
}

function totalsOf(run: Run): Record<string, number> {
  let prompt = 0;
  let completion = 0;
  let duration = 0;
  for (const e of run.events) {
    const usage = (e.usage ?? {}) as Record<string, number>;
    prompt += usage.prompt_tokens ?? 0;
    completion += usage.completion_tokens ?? 0;
    duration += (e.duration_ms as number) ?? 0;
  }
  return {
    steps: run.events.length,
    prompt_tokens: prompt,
    completion_tokens: completion,
    duration_ms: Math.round(duration * 10) / 10,
  };
}

function label(e: Record<string, unknown>): string {
  return String(e.model ?? e.name ?? e.message ?? e.kind ?? "?");
}

function signature(e: Record<string, unknown>): string {
  if (e.kind === "llm") {
    if (e.fingerprint) return "llm:" + e.fingerprint;
    const req = (e.request ?? {}) as Record<string, unknown>;
    return "llm:" + canonicalJson({ model: req["model"], messages: req["messages"] });
  }
  if (e.kind === "tool") return "tool:" + String(e.name);
  if (e.kind === "span") return `span:${e.phase}:${e.name}`;
  return `${e.kind}:${e.message ?? ""}`;
}

export function diffRuns(a: Run | string, b: Run | string): DiffReport {
  const ra = typeof a === "string" ? loadRun(a) : a;
  const rb = typeof b === "string" ? loadRun(b) : b;
  const n = Math.max(ra.events.length, rb.events.length);
  const steps: StepDiff[] = [];
  let firstDivergence: number | null = null;
  let identical = ra.events.length === rb.events.length;

  for (let i = 0; i < n; i++) {
    const ea = (ra.events[i] ?? null) as Record<string, unknown> | null;
    const eb = (rb.events[i] ?? null) as Record<string, unknown> | null;
    let same: boolean | null = null;
    if (ea && eb) {
      same = signature(ea) === signature(eb);
    }
    if (same === false && firstDivergence === null) firstDivergence = i;
    if (same !== true) identical = false;
    steps.push({
      index: i,
      kind: String((ea ?? eb ?? {})["kind"] ?? "?"),
      a: ea ? label(ea) : null,
      b: eb ? label(eb) : null,
      same,
    });
  }
  return {
    identical,
    firstDivergence,
    steps,
    totalsA: totalsOf(ra),
    totalsB: totalsOf(rb),
  };
}
