# @backspin/sdk

**The flight recorder for AI agents — TypeScript edition.** Record every
LLM call and tool call of an agent run into one portable
`*.backspin.jsonl` file, replay the run deterministically with zero API
access, and diff two runs to find the exact step where behavior diverged.
100% local, zero runtime dependencies.

Run files are the same format as the [Python package](https://github.com/zaibuchihuoji/backspin):
Python recordings replay in TypeScript and vice versa.

```ts
import { Recorder, captureOpenAI, Cassette, stubClient, loadRun } from "@backspin/sdk";

const rec = new Recorder({ agent: "support-bot" });
const client = captureOpenAI(rec, new OpenAI());  // your agent, unchanged
// ... run the agent ...
rec.close();
```

## API

- `new Recorder({ dir?, agent?, metadata?, redact? })` — start a run file.
- `rec.log(message)`, `rec.event(kind, payload)`, `rec.recordTool(...)`, `rec.recordLLM(...)`.
- `rec.tool(name, fn)` — wrap a function (sync or async) so every call is recorded.
- `await rec.span(name, body)` — nested spans, isolated per async context.
- `captureOpenAI(rec, client)` — record sync/async/streaming `chat.completions` calls.
- `redactStrings(transform)` + `mask(regex)` — keep secrets out of recordings.
- `loadRun(path)`, `Cassette.fromRun(run)`, `stubClient(cassette)` — deterministic replay.
- `diffRuns(a, b)` — first-divergence diffing.

## License

MIT — see [LICENSE](LICENSE).
