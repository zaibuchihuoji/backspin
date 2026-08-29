/**
 * Recorder: writes a run file as the agent executes. `span()` uses
 * AsyncLocalStorage, so concurrent async branches keep their own stacks.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import { RunWriter, fingerprintRequest } from "./runfile.js";

export interface RecorderOptions {
  dir?: string;
  agent?: string;
  metadata?: Record<string, unknown>;
}

export interface LLMRecord {
  request?: Record<string, unknown>;
  response?: unknown;
  usage?: Record<string, number> | null;
  model?: string | null;
  durationMs?: number;
  error?: string | null;
  provider?: string;
}

interface SpanFrame {
  id: string;
}

const spanStack = new AsyncLocalStorage<SpanFrame[]>();

const round10 = (ms: number) => Math.round(ms * 10) / 10;

export class Recorder {
  readonly writer: RunWriter;
  readonly path: string;
  readonly runId: string;

  constructor(options: RecorderOptions = {}) {
    const dir = options.dir ?? "runs";
    this.writer = new RunWriter(dir, options.agent ?? "agent", options.metadata);
    this.path = this.writer.path;
    this.runId = this.writer.runId;
  }

  private emit(kind: string, payload: Record<string, unknown> = {}): void {
    const stack = spanStack.getStore() ?? [];
    const ev: Record<string, unknown> = { kind, ts: Date.now() / 1000, ...payload };
    if (stack.length) {
      // span events carry their own ids/depths; regular events inherit the
      // innermost open span
      if (ev.spanId === undefined) ev.spanId = stack[stack.length - 1].id;
      if (ev.depth === undefined) ev.depth = stack.length;
    }
    this.writer.writeStep(ev);
  }

  log(message: string, level = "info"): void {
    this.emit("log", { level, message });
  }

  event(kind: string, payload: Record<string, unknown> = {}): void {
    this.emit(kind, payload);
  }

  recordLLM(record: LLMRecord): void {
    const request = record.request ?? {};
    this.emit("llm", {
      duration_ms: round10(record.durationMs ?? 0),
      model: record.model ?? request["model"] ?? null,
      request,
      response: record.response ?? null,
      usage: record.usage ?? null,
      error: record.error ?? null,
      provider: record.provider ?? null,
      fingerprint: fingerprintRequest(request["model"], request["messages"]),
    });
  }

  recordTool(name: string, result: unknown, durationMs: number, error?: string): void {
    this.emit("tool", {
      name,
      result,
      duration_ms: round10(durationMs),
      error: error ?? null,
    });
  }

  /** Wrap any function so calls are recorded as tool steps. */
  tool<T extends (...args: never[]) => unknown>(name: string, fn: T): T {
    const wrapped = (...args: never[]): unknown => {
      const t0 = performance.now();
      try {
        const result = fn(...args);
        this.recordTool(name, result, performance.now() - t0);
        return result;
      } catch (err) {
        this.recordTool(name, null, performance.now() - t0, String(err));
        throw err;
      }
    };
    return wrapped as T;
  }

  /** Run `body` inside a named span (async-safe, nests arbitrarily). */
  async span<T>(name: string, body: () => Promise<T> | T): Promise<T> {
    const id = randomBytes(4).toString("hex");
    const stack = spanStack.getStore() ?? [];
    const parent = stack.length ? stack[stack.length - 1].id : null;
    const depth = stack.length;
    this.emit("span", { phase: "enter", name, spanId: id, parent, depth });
    const t0 = performance.now();
    let result: T;
    try {
      result = await spanStack.run(stack.concat({ id }), body);
    } catch (err) {
      this.emit("span", {
        phase: "exit", name, spanId: id, parent, depth,
        duration_ms: round10(performance.now() - t0),
        error: String(err),
      });
      throw err;
    }
    this.emit("span", {
      phase: "exit", name, spanId: id, parent, depth,
      duration_ms: round10(performance.now() - t0),
    });
    return result;
  }

  close(): void {
    this.writer.close();
  }
}
