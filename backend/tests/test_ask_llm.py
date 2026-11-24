"""Ask with an LLM chosen from the models installed in Ollama. A small fake Ollama server stands in for the
real one (same HTTP API: /api/tags, /api/ps, /api/generate), so the seam is the HTTP interface."""
import json
import threading
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TINY = Path(__file__).parent / "fixtures" / "tiny"


class FakeOllama:
    def __init__(self):
        self.reply, self.delay, self.prompts = "", 0.0, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, body):
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._json({"models": [
                        {"name": "qwen2.5-coder:3b", "size": 1_900_000_000, "details": {"parameter_size": "3.1B", "family": "qwen2", "quantization_level": "Q4_K_M"}},
                        {"name": "llama3.2:1b", "size": 1_300_000_000, "details": {"parameter_size": "1.2B", "family": "llama", "quantization_level": "Q8_0"}}]})
                elif self.path == "/api/ps":
                    self._json({"models": [{"name": "qwen2.5-coder:3b"}]})
                else:
                    self.send_error(404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if body.get("prompt"):
                    fake.prompts.append(body)
                    time.sleep(fake.delay)
                self._json({"response": fake.reply})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture(scope="module")
def ollama():
    f = FakeOllama()
    yield f
    f.server.shutdown()


@pytest.fixture()
def client(ollama, monkeypatch):
    from kg2analyzer import server

    monkeypatch.setenv("KG2A_OLLAMA_URL", ollama.url)
    c = TestClient(server.app)
    c.post("/api/reset-all")
    files = [("files", (str(p.relative_to(TINY)), p.read_bytes(), "text/turtle")) for p in sorted(TINY.rglob("*.ttl"))]
    assert c.post("/api/pipeline", data={"reset": "true", "decider": "ml"}, files=files).status_code == 200
    assert c.post("/api/mdkgs/from-build", params={"ws": "ask"}).status_code == 200
    yield c
    c.post("/api/translator", params={"ws": "ask"}, json={"spec": "rules"})


def test_the_installed_ollama_models_are_listed(client):
    r = client.get("/api/llm/models", params={"ws": "ask"}).json()
    assert r["reachable"] and [m["name"] for m in r["models"]] == ["llama3.2:1b", "qwen2.5-coder:3b"]
    qwen = r["models"][1]
    assert (qwen["parameters"], qwen["size_gb"], qwen["loaded"]) == ("3.1B", 1.9, True)


def test_a_model_that_is_not_installed_is_refused_with_the_pull_command(client):
    r = client.post("/api/translator", params={"ws": "ask"}, json={"spec": "ollama:mistral:7b"})
    assert r.status_code == 400 and "ollama pull mistral:7b" in r.json()["detail"]


def test_the_chosen_model_answers_and_its_sparql_is_validated(client, ollama):
    from kg2analyzer import server

    ask = server.WORKSPACES["ask"]
    grounded = ask.nl.parser.translate("Total transfer amount by branch")  # a valid query for the fake to return
    ollama.reply, ollama.delay = f"```sparql\n{grounded}\n```", 0
    assert client.post("/api/translator", params={"ws": "ask"}, json={"spec": "ollama:llama3.2:1b"}).json()["translator"] == "ollama:llama3.2:1b"
    a = client.post("/api/ask", params={"ws": "ask"}, json={"question": "Total transfer amount by branch"}).json()
    assert a["status"] == "executed" and a["attempts"][0]["translator"] == "ollama:llama3.2:1b"
    assert {r["branch_label"]: Decimal(str(r["total"])) for r in a["rows"]} == {"Gulshan": Decimal("5000"), "Agrabad": Decimal("325")}
    sent = ollama.prompts[-1]
    assert sent["model"] == "llama3.2:1b" and sent["keep_alive"] and sent["options"]["temperature"] == 0


def poll(client, job, until=10.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < until:
        r = client.get(f"/api/ask/jobs/{job}", params={"ws": "ask"}).json()
        if r["state"] != "running":
            return r
        time.sleep(0.2)
    raise AssertionError("LLM job still running")


def test_a_slow_model_answers_later_while_the_parser_answers_at_once(client, ollama):
    from kg2analyzer import server

    ask = server.WORKSPACES["ask"]
    ollama.reply = f"<think>The user wants fees per branch...</think>\n```sparql\n{ask.nl.parser.translate('Total fees per branch in the bank')}\n```"
    ollama.delay = 1.5
    client.post("/api/translator", params={"ws": "ask"}, json={"spec": "ollama:qwen2.5-coder:3b"})
    ask.nl.patience = 0.2
    t0 = time.perf_counter()
    first = client.post("/api/ask", params={"ws": "ask"}, json={"question": "Total fees per branch in the bank"}).json()
    assert time.perf_counter() - t0 < 1.0  # the grounded parser's answer, at once
    assert first["status"] == "executed" and {r["branch_label"] for r in first["rows"]} == {"Gulshan", "Agrabad"}
    assert first["trace"]["llm"] == "ollama:qwen2.5-coder:3b" and first["trace"]["llm_job"]
    later = poll(client, first["trace"]["llm_job"])
    assert later["state"] == "done" and later["answer"]["attempts"][0]["translator"] == "ollama:qwen2.5-coder:3b"
    assert {r["branch_label"]: Decimal(str(r["total"])) for r in later["answer"]["rows"]} == {"Gulshan": Decimal("15"), "Agrabad": Decimal("3.5")}
    assert ollama.prompts[-1]["think"] is False  # thinking models are asked not to think first
    again = client.post("/api/ask", params={"ws": "ask"}, json={"question": "Total fees per branch in the bank"}).json()
    assert again["trace"].get("cached") and again["attempts"][0]["translator"] == "ollama:qwen2.5-coder:3b"


def test_a_model_that_never_answers_in_time_is_dropped(client, ollama):
    from kg2analyzer import server

    ollama.reply, ollama.delay = "", 3.0
    client.post("/api/translator", params={"ws": "ask"}, json={"spec": "ollama:qwen2.5-coder:3b"})
    nl = server.WORKSPACES["ask"].nl
    nl.patience, nl.budget = 0.2, 0.6
    first = client.post("/api/ask", params={"ws": "ask"}, json={"question": "Total transfer amount by branch"}).json()
    assert first["status"] == "executed" and first["rows"]
    assert poll(client, first["trace"]["llm_job"])["state"] == "timeout"
