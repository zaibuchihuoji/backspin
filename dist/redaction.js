/** Build a deep redactor that applies `transform` to every string.
 *  Object keys are preserved (only values pass through); numbers, booleans
 *  and nested structures pass through recursively. */
export function redactStrings(transform) {
    const deep = (obj) => {
        if (typeof obj === "string")
            return transform(obj);
        if (Array.isArray(obj))
            return obj.map(deep);
        if (obj != null && typeof obj === "object") {
            const out = {};
            for (const [k, v] of Object.entries(obj)) {
                out[k] = deep(v);
            }
            return out;
        }
        return obj;
    };
    return deep;
}
/** Build a string transform that replaces regex matches. */
export function mask(pattern, repl = "[redacted]") {
    return (s) => s.replace(pattern, repl);
}
// Fields that stay in clear even under a redactor — the same set the
// Python Recorder protects (see `backspin/recorder.py`).
export const STRUCTURAL_FIELDS = new Set([
    "kind", "ts", "seq", "model", "name", "duration_ms", "fingerprint",
    "error_type", "level", "span_id", "spanId", "parent", "depth", "phase",
    "provider",
]);
