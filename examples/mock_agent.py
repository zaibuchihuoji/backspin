"""Zero-setup demo: record a fake agent run, replay it deterministically,
then diff the two runs — no API key, no network.

    python examples/mock_agent.py
"""
from backspin import Cassette, Recorder, diff_runs, load_run, stub_client
from backspin.testing import FakeOpenAI

# The "model" is scripted: two assistant turns for our little weather agent.
SCRIPT = [
    "The user wants the weather; I should call get_weather.",
    "It is 22C and sunny in Paris right now -- a fine day for a walk.",
]


def run_agent(client, rec):
    """A two-step 'agent': ask the model, call a tool, ask again."""
    rec.log("user asks: what's the weather in Paris?")

    first = client.chat.completions.create(
        model="demo-4o",
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
    )
    rec.log("assistant decides: " + first.choices[0].message.content)

    @rec.tool
    def get_weather(city: str) -> str:
        return f"{city}: 22C, sunny"

    weather = get_weather("Paris")
    rec.log("tool result: " + weather)

    rec.log("feeding the tool result back to the model")
    second = client.chat.completions.create(
        model="demo-4o",
        messages=[
            {"role": "user", "content": "What's the weather in Paris?"},
            {"role": "assistant", "content": first.choices[0].message.content},
            {"role": "user", "content": "tool result: " + weather},
        ],
    )
    return second.choices[0].message.content


def main():
    # 1. Record the live run.
    rec = Recorder(dir="runs", agent="weather-bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(SCRIPT))
        answer = run_agent(client, rec)
    print("recorded :", rec.path)
    print("answer   :", answer)

    # 2. Replay it deterministically -- same agent code, zero LLM/network.
    run = load_run(rec.path)
    cassette = Cassette.from_run(run)
    rec2 = Recorder(dir="runs", agent="weather-bot", metadata={"replay_of": run.run_id})
    with rec2:
        stub = rec2.capture_openai(stub_client(cassette))
        answer2 = run_agent(stub, rec2)
    print("replayed :", rec2.path)
    assert answer == answer2, "replay diverged!"

    # 3. Diff the two runs: the replay must be a perfect mirror.
    report = diff_runs(run, load_run(rec2.path))
    print("identical:", report.identical)
    assert report.identical

    print("\nbrowse both runs with:  backspin ui")


if __name__ == "__main__":
    main()
