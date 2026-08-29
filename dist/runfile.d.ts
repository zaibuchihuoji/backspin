export declare const FILE_SUFFIX = ".backspin.jsonl";
export declare const SCHEMA_VERSION = 1;
/** Keep in sync with package.json (see RELEASE.md). */
export declare const VERSION = "0.5.1";
export type EventKind = "llm" | "tool" | "log" | "error" | "span" | string;
export interface RunEvent {
    kind: EventKind;
    seq?: number;
    ts?: number;
    spanId?: string;
    depth?: number;
    provider?: string;
    fingerprint?: string;
    durationMs?: number;
    [key: string]: unknown;
}
export declare function newRunId(): string;
/** JSON with sorted keys — the stable serialization used for fingerprints. */
export declare function canonicalJson(obj: unknown): string;
export declare function fingerprintRequest(model: unknown, messages: unknown): string;
export interface Run {
    header: Record<string, unknown>;
    events: RunEvent[];
    path: string;
}
export declare function loadRun(path: string): Run;
/** Streaming writer for a run file (header first, then ordered steps). */
export declare class RunWriter {
    readonly path: string;
    readonly runId: string;
    private fd;
    private seq;
    constructor(dir: string, agent: string, metadata?: Record<string, unknown>);
    writeRaw(ev: Record<string, unknown>): void;
    writeStep(ev: Record<string, unknown>): void;
    close(): void;
}
