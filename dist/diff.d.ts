/**
 * diffRuns: align two runs step by step and find the first divergence.
 */
import { Run } from "./runfile.js";
export interface StepDiff {
    index: number;
    kind: string;
    a: string | null;
    b: string | null;
    same: boolean | null;
}
export interface DiffReport {
    identical: boolean;
    firstDivergence: number | null;
    steps: StepDiff[];
    totalsA: Record<string, number>;
    totalsB: Record<string, number>;
}
export declare function diffRuns(a: Run | string, b: Run | string): DiffReport;
