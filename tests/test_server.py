import pytest

from backspin import Recorder
from backspin.fakes import message_data

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from backspin.server import create_app  # noqa: E402


def make_run(dir_path, agent="srv-bot", prompts=("x", "y")):
    rec = Recorder(dir=str(dir_path), agent=agent)
    with rec:
        for i, content in enumerate(prompts):
            rec.record_llm(
                request={"model": "m", "messages": [{"role": "user", "content": content}]},
                response=message_data(f"reply-{i}"),
                duration_ms=10.0,
                usage={"prompt_tokens": 1, "completion_tokens": 2},
            )
    return rec.path


@pytest.fixture
def client(tmp_path):
    make_run(tmp_path)
    return TestClient(create_app(str(tmp_path)))


def test_runs_list(client):
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 1
    assert runs[0]["agent"] == "srv-bot"
    assert runs[0]["totals"]["llm_calls"] == 2


def test_get_run(client):
    name = client.get("/api/runs").json()[0]["name"]
    res = client.get(f"/api/run/{name}")
    assert res.status_code == 200
    assert len(res.json()["events"]) == 2


def test_diff_endpoint(client, tmp_path):
    make_run(tmp_path, agent="srv-bot-2")
    runs = client.get("/api/runs").json()
    a, b = runs[0]["name"], runs[1]["name"]
    res = client.get(f"/api/diff?a={a}&b={b}")
    assert res.status_code == 200
    assert res.json()["identical"] is True


def test_traversal_blocked(client):
    assert client.get("/api/run/secret.txt").status_code == 404
    assert client.get("/api/run/%2e%2e%2fescape.backspin.jsonl").status_code == 404
    assert client.get("/api/run/sub%2Fdir.backspin.jsonl").status_code == 404


def test_ui_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "backspin" in res.text


def test_corrupt_run_returns_422(client, tmp_path):
    (tmp_path / "corrupt.backspin.jsonl").write_text(
        '{"kind": "header"}\nnot json\n', encoding="utf-8"
    )
    res = client.get("/api/run/corrupt.backspin.jsonl")
    assert res.status_code == 422
