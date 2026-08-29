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

**放进测试**,就是确定性的 agent 回归测试:录一次,断言到永远,零 token 成本。pytest 插件连断言都帮你写好了:

```python
def test_my_agent(backspin):                       # 装了包即自动加载
    with backspin.record(agent="t") as rec:
        run_agent(rec.capture_openai(client))
    backspin.assert_replays_identically()          # 严格模式:指纹必须精确匹配
```

## What-if 分支:改一个回答,看下游

调试器的核心超能力:固定其它一切,只改某一步的模型回答,看看时间线如何变化。

```python
from backspin import branch, diff_runs, load_run

branch_path = branch("runs/live.backspin.jsonl", {0: {"content": "Rome it is."}})
report = diff_runs(load_run("runs/live.backspin.jsonl"), load_run(branch_path), llm_only=True)
print(report.first_divergence)   # 两条时间线从哪一步开始分岔
```

命令行等价:`backspin branch runs/live.jsonl --step 0 --content "Rome it is."` —— 写出一个 `branch_of` 标记的分支 run 并打印分岔报告。

## Span:结构化层级,不是平铺列表

```python
with rec.span("research", meta={"topic": "weather"}):
    with rec.span("tool:search"):
        ...
    resp = client.chat.completions.create(...)   # 记录在 span 内部
```

span 内的每个事件都带 `span_id` 和嵌套 `depth`;并发安全(asyncio 每个任务独立栈);查看器渲染成树。span 的耗时不会重复计入总时长。

## 零侵入接入:`backspin proxy`

不方便改代码?跑一个 OpenAI 兼容的本地代理,把 agent 的 base_url 指过来——任何框架、任何语言:

```bash
backspin proxy --upstream https://api.openai.com --port 8840
# 客户端: base_url = http://127.0.0.1:8840/v1   ← 接入到此为止
```

所有调用被转发并录制,流式同样支持。同一个代理翻到**回放模式**,就能把录制的 run 作为 API 供出去——任何语言写的 agent 都能确定性回放,无需 SDK:

```bash
backspin proxy --replay runs/live.backspin.jsonl --port 8840
```

## 多模型:OpenAI、Anthropic、以及一切 OpenAI 兼容接口

Claude 原生接口?同样两行搞定:

```python
rec.capture_anthropic(Anthropic())   # 同步/异步/流式,含 tool_use
```

Anthropic 的事件带 `provider: "anthropic"` 标记,usage 归一化到同一套 token 字段——成本和 diff 天然跨厂商可用。代理同时支持 `/v1/messages` 协议,Claude 原生 agent 同样零代码录制/回放。

一切说 OpenAI 协议的模型(DeepSeek、通义千问、Kimi、智谱 GLM、vLLM/Ollama、OpenRouter……)开箱即被 `capture_openai` / 代理覆盖。

## 导出、分享、终端界面

```bash
backspin export runs/live.jsonl --format sft -o train.jsonl   # 导出评测/SFT 数据集
backspin share runs/live.jsonl        # 打包成单个 HTML:run + 查看器
backspin tui                          # 键盘驱动的终端查看器
```

`share` 把查看器和运行记录打进一个 `.html` 文件——发给同事,浏览器打开就能逐步查看,不需要装任何东西,数据不上传任何地方。

## 成本

内置价格表(gpt-4o、claude、gemini、deepseek……)把 token 变成钱:`run.totals()["cost_usd"]`、查看器的成本卡片、`backspin show` 里的 `~$0.0142`。补充价格表就是一个字典的 PR。

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

backspin 还很年轻(v0.4)——录制 → 回放 → what-if → 对比 → 查看全链路可用,横跨 OpenAI 与 Anthropic 协议、Python 与 TypeScript 双 SDK,全部通过真实 SDK 集成测试。接下来:

- [x] ~~异步+流式采集、span、脱敏、成本、pytest 插件~~(0.2/0.3 已发布)
- [x] ~~框架无关的旁路代理(录制 + 回放双模式)~~(0.3 已发布)
- [x] ~~Anthropic 原生:SDK 捕获 + 代理 /v1/messages;TypeScript SDK;导出/分享/TUI~~(0.4 已发布)
- [ ] agent 级 what-if(对整个 agent 重放变异后的 cassette,而非仅请求序列)
- [ ] 确定性时钟/随机数桩,实现完整边界捕获
- [ ] 带可运行示例的文档站

## 开发

```bash
pip install -e ".[dev]"
pytest
python examples/mock_agent.py   # 零依赖演示:录制 → 回放 → 对比
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。
