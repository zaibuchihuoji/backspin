# backspin

**AI Agent 的飞行记录仪。** 把一次 agent 运行中的每一次 LLM 调用、每一次工具调用,录制进一个可移植的文件;离线确定性回放这次运行;对比两次运行,精确定位行为开始分岔的那一步。100% 本地,核心零依赖。

*可以理解为 agent 版的 [rr](https://rr-project.org/)(Mozilla 的录制回放调试器)。*

```python
from backspin import Recorder

with Recorder(agent="my-agent") as rec:
    client = rec.capture_openai(OpenAI())   # 任何走 chat.completions 的代码
    ...                                     # 你的 agent,一行不用改
```

接入就这么多。agent 做过的一切——prompt、补全、工具调用、耗时、token 数——都进了单个 `runs/*.backspin.jsonl` 文件,可以打开、回放、对比,或直接当 bug 附件发出去。

## 为什么

你的 agent 调了四十次 LLM、用了三个工具,然后在凌晨两点做了点诡异的事。对着聊天记录,祝你好运。

云端可观测性工具(Langfuse、LangSmith、AgentOps……)在仪表盘上回答"**发生了什么**"。**backspin 回答"让它原样再发生一次"**。它是调试器,不是仪表盘:

- **录制(Record)** — 一个上下文管理器,捕获所有 OpenAI 形态的调用(同步、异步、流式),外加你自己的工具调用与日志。
- **回放(Replay)** — 运行记录变成一盘"磁带"(cassette):agent 离线重跑,LLM 响应从录制中注入,完全确定。做回归测试、复现 bug,不需要 API key,不花钱。
- **对比(Diff)** — 改完代码后重放同一 agent,diff 两次运行,backspin 直接指出第一步分岔在哪。
- **本地优先** — 运行记录就是普通 JSONL 文件。没有服务端、没有账号、没有遥测。"把失败的 run 发我一下"从此成为可操作的Debug仪式。

## 安装

```bash
pip install "backspin[ui]"     # SDK + CLI + 本地查看器
```

核心零依赖;`[ui]` 额外装 FastAPI + uvicorn(本地查看器用)。

## 录制

```python
from openai import OpenAI
from backspin import Recorder

rec = Recorder(agent="support-bot")

with rec:
    client = rec.capture_openai(OpenAI())

    @rec.tool
    def lookup_order(order_id: str) -> str:
        return "shipped"

    rec.log("user asks about order #1234")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Where is order #1234?"}],
    )

print(rec.path)   # runs/20260829-142300-support-bot-9f31c2.backspin.jsonl
```

流式与异步客户端同样支持;流式响应会在录制时透明地重组为一次完整补全。

## 回放

```python
from backspin import Cassette, load_run, stub_client

cassette = Cassette.from_run(load_run(rec.path))
stub = stub_client(cassette)

# 同样的 agent 代码,零网络:响应全部来自录制。
answer = run_agent(stub)
```

请求按指纹匹配(model + messages),匹配不上时按调用顺序回退并给出警告。没法注入 client 的话,用 `backspin.replay.patch_openai(cassette)` 直接 patch `openai.OpenAI`。

**放进测试**,就是确定性的 agent 回归测试:录一次,断言到永远,零 token 成本。

## 对比

```bash
backspin diff runs/live.backspin.jsonl runs/replay.backspin.jsonl
# runs diverge at step #14
#   #13  llm   gpt-4o-mini        gpt-4o-mini        yes
#   #14  llm   gpt-4o-mini        gpt-4o-mini        NO
```

步骤按"agent 决定做什么"(LLM 请求指纹 / 工具名)对齐并签名,第一个不匹配的步骤就是两次运行开始分岔的精确位置——耗时和 token 只是附带的增量信息。

## CLI 与本地查看器

```bash
backspin ls                  # 列出 runs:agent、步骤数、token 数
backspin show runs/...jsonl  # 打印一次运行的时间线
backspin show runs/... --step 7   # 单步导出 JSON
backspin diff a b            # 对比两次运行(有差异时退出码为 1)
backspin ui                  # http://127.0.0.1:8787 — 时间线、检查器、diff
```

查看器是零构建的原生 JS 应用,由 CLI 直接启动:瀑布时间线、步骤检查器(request / response / raw)、双 run 对比视图。

![backspin 时间线查看器](docs/ui-timeline.png)

![backspin 对比视图](docs/ui-diff.png)

## 别让敏感信息进录像

录像里包含完整的 prompt 和补全。如果有顾虑,给 Recorder 传一个 `redact` 函数——所有载荷值落盘前都会经过它:

```python
from backspin import Recorder
from backspin.redaction import mask, redact_strings

rec = Recorder(
    agent="support-bot",
    redact=redact_strings(mask(r"sk-[A-Za-z0-9]{8,}")),
)
```

结构字段(模型名、工具名、指纹、耗时)保持明文,查看器和 diff 才能正常工作;其余一切——包括未知的自定义字段——都会过 redactor。指纹在脱敏前计算,回放匹配不受影响。注意取舍:脱敏过的 run 仍可回放,但回放值是脱敏后的内容。

## run 文件格式

一次运行 = 一个自包含的 JSONL 文件。首行是 header,之后每行一个步骤:

```json
{"kind": "llm", "seq": 3, "ts": 1756448402.1, "model": "gpt-4o-mini",
 "duration_ms": 812.4, "fingerprint": "9f31c2ab77e01d44",
 "request": {"messages": [...]}, "response": {"choices": [...]},
 "usage": {"prompt_tokens": 120, "completion_tokens": 45}}
```

事件类型:`llm`、`tool`、`log`、`error`,以及通过 `rec.event(kind, **payload)` 记录的任意自定义事件。

## 与同类工具的关系

| | Langfuse / LangSmith / AgentOps | backspin |
|---|---|---|
| 回答的问题 | 发生了什么 | 让它原样再发生一次 |
| 位置 | 云端 SaaS | 你的机器,普通文件 |
| 用录制响应回放 | 否 | 是,确定性 |
| 首次分岔 diff | 否 | 是 |
| 接入成本 | SDK + 账号 + 上报 | 一个上下文管理器 |
| 调试的 token 成本 | 全价 | 录制后为零 |

两者完全可以共存:仪表盘照用,别人说"复现不了"的时候,甩一个 backspin run 过去。

## 状态与路线图

backspin 还很年轻(v0.2)——核心闭环(录制 → 回放 → 对比 → 查看)已完成,通过了真实 OpenAI SDK 的集成测试,并有边界场景与性能测试兜底。接下来:

- [ ] 原生异步录制 API 与结构化 span(工具 → 子 LLM 的嵌套层级)
- [ ] LangChain / Vercel AI SDK 适配器;TypeScript SDK
- [ ] 框架无关的**旁路代理模式**(任何 agent 指过来就能录,无需 SDK)
- [ ] 终端 TUI(`backspin tui`)
- [ ] 成本表、确定性时钟/随机数桩,实现完整边界捕获
- [ ] `pytest` fixture(`backspin.testing`)文档与 golden-run CI 模式

## 开发

```bash
pip install -e ".[dev]"
pytest
python examples/mock_agent.py   # 零依赖演示:录制 → 回放 → 对比
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。
