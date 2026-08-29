/**
 * captureOpenAI: patch an OpenAI-SDK-shaped client so chat.completions
 * calls are recorded. Handles promises and streamed responses.
 */
import { Recorder } from "./recorder.js";
import { fingerprintRequest } from "./runfile.js";

const KEEP = [
  "model", "messages", "tools", "tool_choice", "temperature", "top_p",
  "max_tokens", "stop", "n", "stream", "stream_options", "response_format",
  "seed", "user", "metadata",
];

function clean(kwargs: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(kwargs)) {
    if (KEEP.includes(k)) out[k] = v;
  }
  return out;
}

function plainCopy(value: unknown): unknown {
  if (value == null || typeof value !== "object") return value;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value);
  }
}

interface ToolSlot {
  id: string;
  type: string;
  function: { name: string; arguments: string };
}

interface Accumulator {
  content: string[];
  tools: Map<number, ToolSlot>;
  usage: Record<string, unknown> | null;
  finish: string | null;
  model: string | null;
}

function absorbChunk(acc: Accumulator, chunk: Record<string, any>): void {
  if (chunk.model) acc.model = chunk.model;
  if (chunk.usage) acc.usage = plainCopy(chunk.usage) as Record<string, unknown> | null;
  for (const choice of chunk.choices ?? []) {
    const delta = choice.delta ?? {};
    if (delta.content) acc.content.push(delta.content);
    for (const tc of delta.tool_calls ?? []) {
      const idx = tc.index ?? 0;
      const slot =
        acc.tools.get(idx) ??
        { id: "", type: "function", function: { name: "", arguments: "" } };
      acc.tools.set(idx, slot);
      if (tc.id) slot.id = tc.id;
      if (tc.function?.name) slot.function.name = tc.function.name;
      if (tc.function?.arguments) slot.function.arguments += tc.function.arguments;
    }
    if (choice.finish_reason) acc.finish = choice.finish_reason;
  }
}

function accPayload(acc: Accumulator): Record<string, unknown> {
  const message: Record<string, unknown> = { role: "assistant" };
  if (acc.content.length) message.content = acc.content.join("");
  if (acc.tools.size) message.tool_calls = [...acc.tools.entries()].map(([i, t]) => ({ index: i, ...t }));
  return {
    object: "chat.completion",
    model: acc.model,
    reconstructed_from_stream: true,
    choices: [{ index: 0, finish_reason: acc.finish ?? "stop", message }],
    usage: acc.usage,
  };
}

class StreamRecorder implements AsyncIterable<Record<string, any>> {
  private acc: Accumulator;
  private t0 = performance.now();
  private done = false;

  constructor(
    private recorder: Recorder,
    private kwargs: Record<string, unknown>,
    private stream: AsyncIterable<Record<string, any>>,
  ) {
    this.acc = { content: [], tools: new Map(), usage: null, finish: null, model: kwargs["model"] as string | null };
  }

  private finalize(error?: unknown): void {
    if (this.done) return;
    this.done = true;
    const ms = performance.now() - this.t0;
    if (error) {
      this.recorder.recordLLM({
        request: clean(this.kwargs), model: (this.kwargs["model"] as string) ?? this.acc.model,
        error: String(error), durationMs: ms,
      });
      return;
    }
    this.recorder.recordLLM({
      request: clean(this.kwargs), response: accPayload(this.acc),
      usage: this.acc.usage as Record<string, number> | null,
      model: this.acc.model ?? (this.kwargs["model"] as string | null), durationMs: ms,
    });
  }

  async *[Symbol.asyncIterator](): AsyncIterator<Record<string, any>> {
    try {
      for await (const chunk of this.stream) {
        absorbChunk(this.acc, chunk);
        yield chunk;
      }
    } catch (err) {
      this.finalize(err);
      throw err;
    } finally {
      // also fires when the consumer breaks out of the loop early —
      // finalize() is idempotent, so the double call is safe
      this.finalize();
    }
  }
}

export function captureOpenAI(recorder: Recorder, client: any): any {
  const completions = client.chat.completions;
  const original = completions.create.bind(completions);
  completions.create = async (...args: any[]) => {
    const kwargs: Record<string, unknown> = args[0] ?? {};
    const t0 = performance.now();
    let resp: unknown;
    try {
      resp = await original(...args);
    } catch (err) {
      recorder.recordLLM({
        request: clean(kwargs), model: (kwargs["model"] as string) ?? null,
        error: String(err), durationMs: performance.now() - t0,
      });
      throw err;
    }
    if (kwargs["stream"]) {
      return new StreamRecorder(recorder, kwargs, resp as AsyncIterable<Record<string, any>>);
    }
    recorder.recordLLM({
      request: clean(kwargs), response: plainCopy(resp),
      usage: (resp as any)?.usage
        ? (plainCopy((resp as any).usage) as Record<string, number> | null)
        : null,
      model: (resp as any)?.model ?? (kwargs["model"] as string | null),
      durationMs: performance.now() - t0,
    });
    return resp;
  };
  return client;
}

export { fingerprintRequest };
