import { Transform } from "./redaction.js";
import { RunWriter } from "./runfile.js";
export interface RecorderOptions {
    dir?: string;
    agent?: string;
    metadata?: Record<string, unknown>;
    /** Transform applied to every payload value before it touches disk. */
    redact?: Transform;
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
export declare class Recorder {
    readonly writer: RunWriter;
    readonly path: string;
    readonly runId: string;
    private readonly redact?;
    constructor(options?: RecorderOptions);
    private emit;
    log(message: string, level?: string): void;
    event(kind: string, payload?: Record<string, unknown>): void;
    recordLLM(record: LLMRecord): void;
    recordTool(name: string, result: unknown, durationMs: number, error?: string): void;
    /** Wrap any function so calls are recorded as tool steps. Sync and
     *  async: a returned Promise is awaited, so the resolved value (not the
     *  Promise) is recorded with the real duration. */
    tool<T extends (...args: never[]) => unknown>(name: string, fn: T): T;
    /** Run `body` inside a named span (async-safe, nests arbitrarily). */
    span<T>(name: string, body: () => Promise<T> | T): Promise<T>;
    close(): void;
}
