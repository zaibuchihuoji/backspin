import { fingerprintRequest } from "./runfile.js";
const KEEP = [
    "model", "messages", "tools", "tool_choice", "temperature", "top_p",
    "max_tokens", "stop", "n", "stream", "stream_options", "response_format",
    "seed", "user", "metadata",
];
function clean(kwargs) {
    const out = {};
    for (const [k, v] of Object.entries(kwargs)) {
        if (KEEP.includes(k))
            out[k] = v;
    }
    return out;
}
function plainCopy(value) {
    if (value == null || typeof value !== "object")
        return value;
    try {
        return JSON.parse(JSON.stringify(value));
    }
    catch {
        return String(value);
    }
}
function absorbChunk(acc, chunk) {
    if (chunk.model)
        acc.model = chunk.model;
    if (chunk.usage)
        acc.usage = plainCopy(chunk.usage);
    for (const choice of chunk.choices ?? []) {
        const delta = choice.delta ?? {};
        if (delta.content)
            acc.content.push(delta.content);
        for (const tc of delta.tool_calls ?? []) {
            const idx = tc.index ?? 0;
            const slot = acc.tools.get(idx) ??
                { id: "", type: "function", function: { name: "", arguments: "" } };
            acc.tools.set(idx, slot);
            if (tc.id)
                slot.id = tc.id;
            if (tc.function?.name)
                slot.function.name = tc.function.name;
            if (tc.function?.arguments)
                slot.function.arguments += tc.function.arguments;
        }
        if (choice.finish_reason)
            acc.finish = choice.finish_reason;
    }
}
function accPayload(acc) {
    const message = { role: "assistant" };
    if (acc.content.length)
        message.content = acc.content.join("");
    if (acc.tools.size)
        message.tool_calls = [...acc.tools.entries()].map(([i, t]) => ({ index: i, ...t }));
    return {
        object: "chat.completion",
        model: acc.model,
        reconstructed_from_stream: true,
        choices: [{ index: 0, finish_reason: acc.finish ?? "stop", message }],
        usage: acc.usage,
    };
}
class StreamRecorder {
    recorder;
    kwargs;
    stream;
    acc;
    t0 = performance.now();
    done = false;
    constructor(recorder, kwargs, stream) {
        this.recorder = recorder;
        this.kwargs = kwargs;
        this.stream = stream;
        this.acc = { content: [], tools: new Map(), usage: null, finish: null, model: kwargs["model"] };
    }
    finalize(error) {
        if (this.done)
            return;
        this.done = true;
        const ms = performance.now() - this.t0;
        if (error) {
            this.recorder.recordLLM({
                request: clean(this.kwargs), model: this.kwargs["model"] ?? this.acc.model,
                error: String(error), durationMs: ms,
            });
            return;
        }
        this.recorder.recordLLM({
            request: clean(this.kwargs), response: accPayload(this.acc),
            usage: this.acc.usage,
            model: this.acc.model ?? this.kwargs["model"], durationMs: ms,
        });
    }
    async *[Symbol.asyncIterator]() {
        try {
            for await (const chunk of this.stream) {
                absorbChunk(this.acc, chunk);
                yield chunk;
            }
        }
        catch (err) {
            this.finalize(err);
            throw err;
        }
        finally {
            // also fires when the consumer breaks out of the loop early —
            // finalize() is idempotent, so the double call is safe
            this.finalize();
        }
    }
}
export function captureOpenAI(recorder, client) {
    const completions = client.chat.completions;
    const original = completions.create.bind(completions);
    completions.create = async (...args) => {
        const kwargs = args[0] ?? {};
        const t0 = performance.now();
        let resp;
        try {
            resp = await original(...args);
        }
        catch (err) {
            recorder.recordLLM({
                request: clean(kwargs), model: kwargs["model"] ?? null,
                error: String(err), durationMs: performance.now() - t0,
            });
            throw err;
        }
        if (kwargs["stream"]) {
            return new StreamRecorder(recorder, kwargs, resp);
        }
        recorder.recordLLM({
            request: clean(kwargs), response: plainCopy(resp),
            usage: resp?.usage
                ? plainCopy(resp.usage)
                : null,
            model: resp?.model ?? kwargs["model"],
            durationMs: performance.now() - t0,
        });
        return resp;
    };
    return client;
}
export { fingerprintRequest };
