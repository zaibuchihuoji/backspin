/**
 * @backspin/sdk — the flight recorder for AI agents (TypeScript).
 *
 * Same run format as the Python package: record with `Recorder` /
 * `captureOpenAI`, replay with `Cassette` / `stubClient`, compare with
 * `diffRuns`. Run files are interchangeable across both SDKs.
 */
export * from "./runfile.js";
export * from "./recorder.js";
export * from "./capture.js";
export * from "./replay.js";
export * from "./diff.js";
