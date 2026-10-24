from fastapi.testclient import TestClient

from laya_service.app import create_app
from laya_service.registry import Registry

BODY = {"strategy": "english-only", "text": "hi", "max_len": 512,
        "questions": {"q": {"type": "noul", "instructions": "x"}}}


class FakeEngine:
    def predict(self, text, questions, max_len):
        return {"answers": {"q": {"noul": 0.5, "answer_confidence": 0.9}}, "usage": {"input_tokens": len(text)}}


def client(token=None, loader=lambda checkpoint: FakeEngine()):
    return TestClient(create_app(Registry(loader), token))


def test_ask_loads_a_model_once_and_reports_each_call():
    loads = []
    c = client(loader=lambda m: loads.append(m) or FakeEngine())
    body = c.post("/v1/ask", json=BODY).json()
    assert body["answers"]["q"]["noul"] == 0.5
    assert body["calls"][0]["model"] == "convaiinnovations/laya" and body["calls"][0]["input_tokens"] == 2
    c.post("/v1/ask", json=BODY)
    assert loads == ["convaiinnovations/laya"]
    assert c.get("/health").json()["models"] == {"convaiinnovations/laya": True, "typed-decisions": False}


def test_token_is_required_when_configured():
    c = client(token="s3cret")
    assert c.post("/v1/ask", json=BODY).status_code == 401
    assert c.post("/v1/ask", json=BODY, headers={"X-Internal-Token": "s3cret"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_engine_failure_is_a_generic_500():
    class Broken:
        def predict(self, *args, **kwargs):
            raise RuntimeError("secret path C:/x")

    r = client(loader=lambda m: Broken()).post("/v1/ask", json=BODY)
    assert r.status_code == 500 and "secret" not in r.text


def test_a_failed_request_still_reports_the_calls_it_made():
    class Cut:
        def predict(self, *args, **kwargs):
            return {"answers": {}, "usage": {"truncated": True, "input_tokens": 9}}

    r = client(loader=lambda m: Cut()).post("/v1/ask", json=BODY)
    assert r.status_code == 413 and r.json()["detail"]["calls"][0]["ok"] is False


def test_thresholds_and_ratios_are_validated():
    c = client()
    assert c.post("/v1/ask", json={**BODY, "thresholds": {"4": {"laya-english": 0.5}}}).status_code == 422
    assert c.post("/v1/ask", json={**BODY, "prune_ratio": 1}).status_code == 422


def voter(pick, confidence, probabilities):
    return {"type": "choice", "choice": pick, "probabilities": probabilities, "answer_confidence": confidence}


def test_combine_restricts_averages_and_compares_the_voters():
    voters = {"laya-english": voter("a", 0.5, {"a": 0.5, "b": 0.45, "c": 0.05}),
              "jev": voter("b", 0.6, {"a": 0.2, "b": 0.7, "c": 0.1})}
    r = client().post("/v1/combine", json={"voters": voters, "options": ["a", "b", "c"]}).json()
    assert r["kept"] == ["a", "b"] and r["final"]["answered_by"] == "laya-english+jev" and r["final"]["uncertain"] is True
    narrowed = client().post("/v1/combine", json={"voters": voters, "options": ["a", "b"]}).json()
    assert abs(sum(narrowed["voters"]["jev"]["probabilities"].values()) - 1) < 1e-9


def test_combine_with_one_voter_has_no_final_and_bad_voters_are_422():
    one = {"jev": voter("a", 0.5, {"a": 0.5, "b": 0.5})}
    assert "final" not in client().post("/v1/combine", json={"voters": one}).json()
    assert client().post("/v1/combine", json={"voters": {"jev": {"type": "choice"}}}).status_code == 422


def test_validate_is_the_one_definition_of_a_valid_question_set():
    c = client()
    good = {"q": {"type": "choice", "instructions": "Which?", "criteria": {"a": "A", "b": "B"}}}
    assert c.post("/v1/validate", json={"questions": good}).json() == {"ok": True}
    bad = [
        {}, {f"q{i}": good["q"] for i in range(9)}, {"q": "oops"}, {"q": {**good["q"], "type": "multi"}},
        {"q": {**good["q"], "instructions": ""}}, {"q": {**good["q"], "extra": 1}},
        {"q": {**good["q"], "criteria": {"a": "only one"}}},
        {"q": {**good["q"], "criteria": {f"o{i}": "d" for i in range(11)}}},
        {"q": {**good["q"], "criteria": ["a", "b"]}}, {"q": {**good["q"], "criteria": {"a": 1, "b": "B"}}},
        {"q": {"type": "score", "instructions": "x", "criteria": {"a": "A", "b": "B"}}},
        {"q": {"type": "score", "instructions": "x", "criteria": ["only"]}},
        {"q": {"type": "noul", "instructions": "x", "criteria": {"yes": "y", "no": "n"}}}, [], "text",
    ]
    for questions in bad:
        assert c.post("/v1/validate", json={"questions": questions}).status_code == 422, questions
    message = c.post("/v1/validate", json={"questions": bad[6]}).json()["detail"]
    assert "criteria must be an object of 2 to 10 option: description strings" in message
    assert c.post("/v1/ask", json={**BODY, "questions": bad[3]}).status_code == 422
