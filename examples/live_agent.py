"""Record a REAL agent run (needs OPENAI_API_KEY) and replay it offline.

    pip install openai
    export OPENAI_API_KEY=sk-...
    python examples/live_agent.py
"""
from openai import OpenAI

from backspin import Cassette, Recorder, load_run, patch_openai


def run_agent(client):
    """The agent under test: any code that talks to chat.completions."""
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "In one sentence: why is replay testing useful?"}],
    )


def main():
    # 1. Record the live run.
    rec = Recorder(dir="runs", agent="live-bot")
    with rec:
        resp = run_agent(rec.capture_openai(OpenAI()))
    print("live     :", resp.choices[0].message.content[:80], "...")

    # 2. Replay offline: OpenAI() is patched to answer from the cassette.
    cassette = Cassette.from_run(load_run(rec.path))
    with patch_openai(cassette):
        resp2 = run_agent(OpenAI())
    assert resp2.choices[0].message.content == resp.choices[0].message.content
    print("replayed : identical, with zero API calls")


if __name__ == "__main__":
    main()
