/**
 * Deterministic replay: answer LLM calls from a recorded run.
 */
import { Run } from "./runfile.js";
export interface CassetteEntry {
    request?: Record<string, unknown>;
    response?: Record<string, any>;
    fingerprint?: string;
    model?: string;
    seq?: number;
}
export declare class Cassette {
    entries: CassetteEntry[];
    private cursor;
    constructor(entries: CassetteEntry[]);
    static fromRun(run: Run): Cassette;
    get length(): number;
    /** Exact fingerprint match first, then next-in-order fallback. */
    match(fingerprint: string): {
        entry: CassetteEntry | null;
        exact: boolean;
    };
    /** What-if: return a copy with recording #index's text answer replaced. */
    mutate(index: number, content: string): Cassette;
}
/** A client-shaped stub: client.chat.completions.create(...) answers from the cassette. */
export declare function stubClient(cassette: Cassette): any;
export declare function loadCassette(path: string): Cassette;
