import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  Recorder,
  captureOpenAI,
  Cassette,
  stubClient,
  diffRuns,
  loadRun,
  fingerprintRequest,
  redactStrings,
  mask,
} from "../index.js";

function tmp(): string {
  return mkdtempSync(join(tmpdir(), "backspin-test-"));
}

/** Scripted OpenAI-shaped client. */
function fakeClient(responses: any[], failOn = -1): any {
  let call = 0;
  return {
    chat: {
      completions: {
        create: async (kwargs: any) => {
          const i = call++;
          if (i === failOn) throw new Error("mock upstream down");
          if (kwargs.stream) {
            const text: string = responses[i] ?? "";
            async function* gen() {
              for (const piece of [text.slice(0, 3), text.slice(3), ""]) {
                yield {
                  model: "gpt-4o-mini",
                  choices: [
                    { index: 0, delta: piece ? { content: piece } : {}, finish_reason: piece ? null : "stop" },
                  ],
                  usage: piece ? undefined : { prompt_tokens: 12, completion_tokens: 7 },
                };
              }
            }
            return gen();
          }
          return {
            model: kwargs.model ?? "gpt-4o-mini",
            choices: [{ message: { role: "assistant", content: responses[i] ?? "" }, finish_reason: "stop" }],
            usage: { prompt_tokens: 12, completion_tokens: 7 },
          };
        },
      },
    },
  };
}

const MSGS = [{ role: "user", content: "hello" }];

test("record then load: header, sequence, fingerprint", () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  rec.log("hi");
  rec.recordLLM({ request: { model: "m", messages: MSGS }, durationMs: 5 });
  rec.close();

  const run = loadRun(rec.path);
  assert.equal(run.events.length, 2);
  assert.equal(run.events[0].seq, 1);
  assert.equal(run.events[1].fingerprint, fingerprintRequest("m", MSGS));
});

test("captureOpenAI records sync and streaming calls", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const client = captureOpenAI(rec, fakeClient(["plain answer", "streamed answer"]));

  const resp = await client.chat.completions.create({ model: "gpt-4o-mini", messages: MSGS });
  assert.equal(resp.choices[0].message.content, "plain answer");

  const chunks: any[] = [];
  const stream = await client.chat.completions.create({
    model: "gpt-4o-mini", messages: MSGS, stream: true, stream_options: { include_usage: true },
  });
  for await (const chunk of stream) chunks.push(chunk);
  assert.equal(chunks.length, 3); // passthrough preserved
  rec.close();

  const run = loadRun(rec.path);
  const llm = run.events.filter((e) => e.kind === "llm");
  assert.equal(llm.length, 2);
  assert.equal((llm[0].response as any).choices[0].message.content, "plain answer");
  assert.equal((llm[1].response as any).reconstructed_from_stream, true);
  assert.equal(
    (llm[1].response as any).choices[0].message.content,
    "streamed answer",
  );
  assert.equal((llm[1].usage as any).prompt_tokens, 12);
});

test("captureOpenAI records errors", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const client = captureOpenAI(rec, fakeClient([], 0));
  await assert.rejects(() => client.chat.completions.create({ model: "m", messages: MSGS }));
  rec.close();

  const run = loadRun(rec.path);
  assert.match(String(run.events[0].error), /mock upstream down/);
});

test("spans nest and stay isolated across concurrent tasks", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });

  await rec.span("outer", async () => {
    await Promise.all([
      rec.span("branch-a", () => {
        rec.log("in a");
        return 1;
      }),
      rec.span("branch-b", () => {
        rec.log("in b");
        return 2;
      }),
    ]);
  });
  rec.close();

  const run = loadRun(rec.path);
  const logs = run.events.filter((e) => e.kind === "log") as any[];
  const enters = run.events.filter((e) => e.kind === "span" && e.phase === "enter") as any[];
  const enterByName = new Map(enters.map((e) => [e.name, e]));
  assert.notEqual(enterByName.get("branch-a")!.spanId, enterByName.get("branch-b")!.spanId);
  assert.equal(
    logs.find((l) => l.message === "in a")!.spanId,
    enterByName.get("branch-a")!.spanId,
  );
  assert.equal(
    logs.find((l) => l.message === "in b")!.spanId,
    enterByName.get("branch-b")!.spanId,
  );
});

test("cassette replay is deterministic and mutable", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const client = captureOpenAI(rec, fakeClient(["first", "second"]));
  await client.chat.completions.create({ model: "m", messages: MSGS });
  await client.chat.completions.create({ model: "m", messages: [{ role: "user", content: "two" }] });
  rec.close();

  const cassette = Cassette.fromRun(loadRun(rec.path));
  assert.equal(cassette.length, 2);

  const stub = stubClient(cassette);
  const r1 = await stub.chat.completions.create({ model: "m", messages: MSGS });
  assert.equal(r1.choices[0].message.content, "first");

  const mutated = cassette.mutate(0, "WHAT-IF");
  const stub2 = stubClient(mutated);
  const r2 = await stub2.chat.completions.create({ model: "m", messages: MSGS });
  assert.equal(r2.choices[0].message.content, "WHAT-IF");
});

test("diffRuns finds the first divergence", async () => {
  const dirA = tmp();
  const dirB = tmp();
  const recA = new Recorder({ dir: dirA, agent: "d" });
  const recB = new Recorder({ dir: dirB, agent: "d" });

  const clientA = captureOpenAI(recA, fakeClient(["same", "split-A"]));
  await clientA.chat.completions.create({ model: "m", messages: MSGS });
  await clientA.chat.completions.create({
    model: "m", messages: [...MSGS, { role: "assistant", content: "same" }],
  });

  const clientB = captureOpenAI(recB, fakeClient(["same", "split-B"]));
  await clientB.chat.completions.create({ model: "m", messages: MSGS });
  await clientB.chat.completions.create({
    model: "m", messages: [...MSGS, { role: "assistant", content: "split-B" }],
  });

  recA.close();
  recB.close();

  const report = diffRuns(loadRun(recA.path), loadRun(recB.path));
  assert.equal(report.identical, false);
  assert.equal(report.firstDivergence, 1);
});

test("tool() awaits async functions and records the resolved value", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const lookup = rec.tool("lookup", async (id: string) => {
    await new Promise((r) => setTimeout(r, 15));
    return `order-${id}`;
  });
  const result = await lookup("42");
  assert.equal(result, "order-42");
  rec.close();

  const ev = loadRun(rec.path).events.find((e) => e.kind === "tool") as any;
  assert.equal(ev.result, "order-42"); // resolved value, not {} from a Promise
  assert.equal(ev.error, null);
  assert.ok(ev.duration_ms >= 10, `duration should cover the await, got ${ev.duration_ms}`);
});

test("tool() records async rejections with the error", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const boom = rec.tool("boom", async () => {
    throw new Error("async tool failed");
  });
  await assert.rejects(() => boom());
  rec.close();

  const ev = loadRun(rec.path).events.find((e) => e.kind === "tool") as any;
  assert.match(String(ev.error), /async tool failed/);
  assert.equal(ev.result, null);
});

test("a stream abandoned mid-loop still gets recorded", async () => {
  const dir = tmp();
  const rec = new Recorder({ dir, agent: "ts-bot" });
  const client = captureOpenAI(rec, fakeClient(["a streamed answer that is long"]));
  const stream = await client.chat.completions.create({
    model: "gpt-4o-mini", messages: MSGS, stream: true,
  });
  for await (const _chunk of stream) break; // consumer bails after one chunk
  rec.close();

  const ev = loadRun(rec.path).events.find((e) => e.kind === "llm") as any;
  assert.ok(ev, "partial stream must still be recorded");
  assert.equal((ev.response as any).reconstructed_from_stream, true);
});

test("redact keeps secrets out of recordings, structural fields readable", async () => {
  const dir = tmp();
  const rec = new Recorder({
    dir,
    agent: "ts-bot",
    redact: redactStrings(mask(/sk-[A-Za-z0-9]{8,}/g)),
  });
  const client = captureOpenAI(rec, fakeClient(["answer"]));
  await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "my key is sk-abcdefgh12345678 ok?" }],
  });
  rec.close();

  const raw = await (await import("node:fs/promises")).readFile(rec.path, "utf-8");
  assert.ok(!raw.includes("sk-abcdefgh12345678"), "secret must not appear in the file");

  const ev = loadRun(rec.path).events.find((e) => e.kind === "llm") as any;
  assert.equal(ev.model, "gpt-4o-mini"); // structural field untouched
  assert.ok(ev.fingerprint, "fingerprint untouched");
});
