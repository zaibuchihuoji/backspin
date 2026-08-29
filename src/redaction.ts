/**
 * Sensitive-data redaction (mirror of Python `backspin.redaction`).
 *
 * Pass `redact` to the Recorder and every payload value is transformed
 * before it touches disk; structural fields (model, name, fingerprint,
 * durations, ...) stay readable so the viewer, differ and replay matching
 * keep working.
 */
export type Transform = (value: unknown) => unknown;

/** Build a deep redactor that applies `transform` to every string.
 *  Object keys are preserved (only values pass through); numbers, booleans
 *  and nested structures pass through recursively. */
export function redactStrings(transform: (s: string) => string): Transform {
  const deep = (obj: unknown): unknown => {
    if (typeof obj === "string") return transform(obj);
    if (Array.isArray(obj)) return obj.map(deep);
    if (obj != null && typeof obj === "object") {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
        out[k] = deep(v);
      }
      return out;
    }
    return obj;
  };
  return deep;
}

/** Build a string transform that replaces regex matches. */
export function mask(pattern: RegExp, repl = "[redacted]"): (s: string) => string {
  return (s: string) => s.replace(pattern, repl);
}

// Fields that stay in clear even under a redactor — the same set the
// Python Recorder protects (see `backspin/recorder.py`).
export const STRUCTURAL_FIELDS = new Set([
  "kind", "ts", "seq", "model", "name", "duration_ms", "fingerprint",
  "error_type", "level", "span_id", "spanId", "parent", "depth", "phase",
  "provider",
]);
