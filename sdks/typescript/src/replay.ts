/**
 * Deterministic replay: answer LLM calls from a recorded run.
 */
import { loadRun, Run, fingerprintRequest } from "./runfile.js";

export interface CassetteEntry {
  request?: Record<string, unknown>;
  response?: Record<string, any>;
  fingerprint?: string;
  model?: string;
  seq?: number;
}

export class Cassette {
  entries: CassetteEntry[];
  private cursor = 0;

  constructor(entries: CassetteEntry[]) {
    this.entries = entries;
  }

  static fromRun(run: Run): Cassette {
    return new Cassette(
      run.events.filter((e) => e.kind === "llm" && e.response != null) as CassetteEntry[],
    );
  }

  get length(): number {
    return this.entries.length;
  }

  /** Exact fingerprint match first, then next-in-order fallback. */
  match(fingerprint: string): { entry: CassetteEntry | null; exact: boolean } {
    for (let i = this.cursor; i < this.entries.length; i++) {
      if (this.entries[i].fingerprint === fingerprint) {
        this.cursor = i + 1;
        return { entry: this.entries[i], exact: true };
      }
    }
    if (this.cursor < this.entries.length) {
      const entry = this.entries[this.cursor];
      this.cursor += 1;
      return { entry, exact: false };
    }
    return { entry: null, exact: false };
  }

  /** What-if: return a copy with recording #index's text answer replaced. */
  mutate(index: number, content: string): Cassette {
    if (index < 0 || index >= this.entries.length) {
      throw new Error(`recording #${index} out of range (cassette has ${this.entries.length})`);
    }
    const entries = JSON.parse(JSON.stringify(this.entries)) as CassetteEntry[];
    const choices = entries[index].response?.choices;
    if (!choices?.length) throw new Error("unrecognized response shape; cannot mutate");
    choices[0].message = { ...(choices[0].message ?? {}), content };
    return new Cassette(entries);
  }
}

/** A client-shaped stub: client.chat.completions.create(...) answers from the cassette. */
export function stubClient(cassette: Cassette): any {
  const state = { calls: 0, mismatches: [] as number[] };
  const completions = {
    state,
    create: async (kwargs: Record<string, unknown> = {}) => {
      state.calls += 1;
      const fp = fingerprintRequest(kwargs["model"], kwargs["messages"]);
      const { entry, exact } = cassette.match(fp);
      if (!entry) throw new Error(`cassette exhausted (call #${state.calls})`);
      if (!exact) state.mismatches.push(state.calls);
      return JSON.parse(JSON.stringify(entry.response));
    },
  };
  return { chat: { completions }, state };
}

export function loadCassette(path: string): Cassette {
  return Cassette.fromRun(loadRun(path));
}
