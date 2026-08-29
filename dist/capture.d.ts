/**
 * captureOpenAI: patch an OpenAI-SDK-shaped client so chat.completions
 * calls are recorded. Handles promises and streamed responses.
 */
import { Recorder } from "./recorder.js";
import { fingerprintRequest } from "./runfile.js";
export declare function captureOpenAI(recorder: Recorder, client: any): any;
export { fingerprintRequest };
