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
export declare function redactStrings(transform: (s: string) => string): Transform;
/** Build a string transform that replaces regex matches. */
export declare function mask(pattern: RegExp, repl?: string): (s: string) => string;
export declare const STRUCTURAL_FIELDS: Set<string>;
