/**
 * Recorder: writes a run file as the agent executes. `span()` uses
 * AsyncLocalStorage, so concurrent async branches keep their own stacks.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import { STRUCTURAL_FIELDS } from "./redaction.js";
import { RunWriter, fingerprintRequest } from "./runfile.js";
const spanStack = new AsyncLocalStorage();
const round10 = (ms) => Math.round(ms * 10) / 10;
export class Recorder {
    writer;
    path;
    runId;
    redact;
    constructor(options = {}) {
        const dir = options.dir ?? "runs";
        this.redact = options.redact;
        this.writer = new RunWriter(dir, options.agent ?? "agent", options.metadata);
        this.path = this.writer.path;
        this.runId = this.writer.runId;
    }
    emit(kind, payload = {}) {
        const stack = spanStack.getStore() ?? [];
        const ev = { kind, ts: Date.now() / 1000, ...payload };
        if (this.redact) {
            for (const key of Object.keys(ev)) {
                // structural fields stay in clear: viewer, differ and replay
                // matching depend on them (same rule as the Python Recorder)
                if (!STRUCTURAL_FIELDS.has(key))
                    ev[key] = this.redact(ev[key]);
            }
        }
        if (stack.length) {
            // span events carry their own ids/depths; regular events inherit
            // the innermost open span
            if (ev.spanId === undefined)
                ev.spanId = stack[stack.length - 1].id;
            if (ev.depth === undefined)
                ev.depth = stack.length;
        }
        this.writer.writeStep(ev);
    }
    log(message, level = "info") {
        this.emit("log", { level, message });
    }
    event(kind, payload = {}) {
        this.emit(kind, payload);
    }
    recordLLM(record) {
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
    recordTool(name, result, durationMs, error) {
        this.emit("tool", {
            name,
            result,
            duration_ms: round10(durationMs),
            error: error ?? null,
        });
    }
    /** Wrap any function so calls are recorded as tool steps. Sync and
     *  async: a returned Promise is awaited, so the resolved value (not the
     *  Promise) is recorded with the real duration. */
    tool(name, fn) {
        const wrapped = (...args) => {
            const t0 = performance.now();
            try {
                const result = fn(...args);
                if (result != null && typeof result.then === "function") {
                    return result.then((v) => {
                        this.recordTool(name, v, performance.now() - t0);
                        return v;
                    }, (err) => {
                        this.recordTool(name, null, performance.now() - t0, String(err));
                        throw err;
                    });
                }
                this.recordTool(name, result, performance.now() - t0);
                return result;
            }
            catch (err) {
                this.recordTool(name, null, performance.now() - t0, String(err));
                throw err;
            }
        };
        return wrapped;
    }
    /** Run `body` inside a named span (async-safe, nests arbitrarily). */
    async span(name, body) {
        const id = randomBytes(4).toString("hex");
        const stack = spanStack.getStore() ?? [];
        const parent = stack.length ? stack[stack.length - 1].id : null;
        const depth = stack.length;
        this.emit("span", { phase: "enter", name, spanId: id, parent, depth });
        const t0 = performance.now();
        let result;
        try {
            result = await spanStack.run(stack.concat({ id }), body);
        }
        catch (err) {
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
    close() {
        this.writer.close();
    }
}
