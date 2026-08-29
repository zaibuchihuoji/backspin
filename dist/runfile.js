/**
 * Run file format (mirror of Python `backspin.runfile`).
 *
 * A run is one UTF-8 JSONL file: line 1 is a header, every following line
 * is a step event. Fingerprints are sha256(canonicalJson({model, messages}))
 * truncated to 16 hex chars — identical to the Python implementation.
 */
import { createHash, randomBytes } from "node:crypto";
import { closeSync, mkdirSync, openSync, readFileSync, writeSync } from "node:fs";
import { join } from "node:path";
export const FILE_SUFFIX = ".backspin.jsonl";
export const SCHEMA_VERSION = 1;
/** Keep in sync with package.json (see RELEASE.md). */
export const VERSION = "0.5.1";
export function newRunId() {
    return randomBytes(6).toString("hex");
}
/** JSON with sorted keys — the stable serialization used for fingerprints. */
export function canonicalJson(obj) {
    if (obj === null || typeof obj !== "object")
        return JSON.stringify(obj) ?? "null";
    if (Array.isArray(obj))
        return "[" + obj.map(canonicalJson).join(",") + "]";
    const keys = Object.keys(obj).sort();
    return ("{" +
        keys
            .map((k) => JSON.stringify(k) + ":" + canonicalJson(obj[k]))
            .join(",") +
        "}");
}
export function fingerprintRequest(model, messages) {
    return createHash("sha256")
        .update(canonicalJson({ model, messages }))
        .digest("hex")
        .slice(0, 16);
}
export function loadRun(path) {
    const text = readFileSync(path, "utf-8");
    let header = null;
    const events = [];
    for (const line of text.split("\n")) {
        if (!line.trim())
            continue;
        const parsed = JSON.parse(line);
        if (!header) {
            if (parsed.kind !== "header")
                throw new Error(`${path}: first event must be a header`);
            header = parsed;
        }
        else {
            events.push(parsed);
        }
    }
    if (!header)
        throw new Error(`${path}: empty run file`);
    return { header, events, path };
}
/** Streaming writer for a run file (header first, then ordered steps). */
export class RunWriter {
    path;
    runId;
    fd;
    seq = 0;
    constructor(dir, agent, metadata) {
        this.runId = newRunId();
        mkdirSync(dir, { recursive: true });
        const slug = agent.replace(/[^A-Za-z0-9_-]/g, "-");
        const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15);
        this.path = join(dir, `${stamp}-${slug}-${this.runId}${FILE_SUFFIX}`);
        this.fd = openSync(this.path, "w");
        this.writeRaw({
            kind: "header",
            schema: SCHEMA_VERSION,
            run_id: this.runId,
            agent,
            created_at: Date.now() / 1000,
            backspin_version: VERSION + "-ts",
            metadata: metadata ?? {},
        });
    }
    writeRaw(ev) {
        writeSync(this.fd, JSON.stringify(ev) + "\n");
    }
    writeStep(ev) {
        this.seq += 1;
        this.writeRaw({ ...ev, seq: this.seq });
    }
    close() {
        closeSync(this.fd);
    }
}
