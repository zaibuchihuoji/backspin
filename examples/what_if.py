"""What-if demo: change one recorded answer, see where timelines split.

    python examples/what_if.py
"""
from backspin import Recorder, branch, diff_runs, load_run
from backspin.testing import FakeOpenAI

SCRIPT = [
    "The user wants the weather; I should call get_weather.",
    "It is 22C and sunny in Paris right now -- a fine day for a walk.",
]


def run_agent(client, rec):
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

    return client.chat.completions.create(
        model="demo-4o",
        messages=[
            {"role": "user", "content": "What's the weather in Paris?"},
            {"role": "assistant", "content": first.choices[0].message.content},
            {"role": "user", "content": "tool result: " + weather},
        ],
    ).choices[0].message.content


def main():
    # 1. Record the live run.
    rec = Recorder(dir="runs", agent="whatif-bot")
    with rec:
        client = rec.capture_openai(FakeOpenAI(SCRIPT))
        answer = run_agent(client, rec)
    original = load_run(rec.path)
    print("live answer:", answer)

    # 2. What-if: the model's FIRST answer was "Rome it is." instead.
    branch_path = branch(rec.path, {0: {"content": "Rome it is."}}, dir="runs")
    branched = load_run(branch_path)
    print("mutated     : call #0 now answers 'Rome it is.'")

    # 3. The mutated answer flows into call #1's request -- that's where
    #    the two timelines split.
    report = diff_runs(original, branched, llm_only=True)
    print("first divergence at llm call:", report.first_divergence)
    assert report.first_divergence == 1
    assert original.llm_calls()[1]["request"]["messages"] != branched.llm_calls()[1][
        "request"
    ]["messages"]

    print("\nbrowse original vs branch with:  backspin ui")


if __name__ == "__main__":
    main()
