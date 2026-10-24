from fastapi.testclient import TestClient

from laya_service.app import create_app
from laya_service.registry import Registry

ENGLISH, TYPED = "convaiinnovations/laya", "typed-decisions"
CHOICE = {"type": "choice", "instructions": "Which?", "criteria": {"a": "A", "b": "B", "c": "C"}}
NOUL = {"type": "noul", "instructions": "True?"}


def choice(pick, conf, probs=None):
    probs = probs or {o: (conf if o == pick else (1 - conf) / 2) for o in "abc"}
    return {"choice": pick, "probabilities": probs, "answer_confidence": conf}


class Engine:
    """Answers question qid from script[qid]: a dict, or a list consumed one call at a time."""

    def __init__(self, **script):
        self.script, self.calls = script, []

    def predict(self, text, questions, max_len):
        self.calls.append(list(questions))
        answers = {}
        for qid, spec in questions.items():
            raw = self.script[qid]
            if isinstance(raw, list):
                raw = raw.pop(0) if len(raw) > 1 else raw[0]
            if spec["type"] == "choice" and set(raw["probabilities"]) != set(spec["criteria"]):
                probs = {o: raw["probabilities"].get(o, 0.0) for o in spec["criteria"]}
                raw = {"choice": max(probs, key=probs.get), "probabilities": probs,
                       "answer_confidence": raw["answer_confidence"]}
            answers[qid] = raw
        return {"answers": answers, "usage": {"input_tokens": 4}}


def ask(english, typed, strategy, questions=None, **extra):
    engines = {ENGLISH: english, TYPED: typed}
    client = TestClient(create_app(Registry(lambda m: engines[m])))
    return client.post("/v1/ask", json={"strategy": strategy, "text": "t", "questions": questions or {"q": CHOICE}, **extra})


def one(response):
    assert response.status_code == 200, response.text
    return response.json()["answers"]["q"]


def test_english_only_never_loads_typed():
    r = one(ask(Engine(q=choice("a", 0.9)), None, "english-only"))
    assert r["choice"] == "a" and r["uncertain"] is False and r["answered_by"] == "laya-english"


def test_typed_only_marks_a_low_confidence_answer_uncertain():
    r = one(ask(None, Engine(q=choice("b", 0.4)), "typed-only"))
    assert r["choice"] == "b" and r["uncertain"] is True


def test_english_then_typed_stops_at_a_sure_english_answer():
    typed = Engine(q=choice("b", 0.99))
    assert one(ask(Engine(q=choice("a", 0.8)), typed, "english-then-typed"))["answered_by"] == "laya-english"
    assert typed.calls == []


def test_english_then_typed_accepts_typed_when_it_agrees():
    r = one(ask(Engine(q=choice("a", 0.6)), Engine(q=choice("a", 0.6)), "english-then-typed"))
    assert r["answered_by"] == "laya-english+laya-typed" and r["uncertain"] is False


def test_disagreement_narrows_the_options_and_asks_again():
    english = Engine(q=[choice("a", 0.5, {"a": 0.5, "b": 0.45, "c": 0.05}), choice("a", 0.95, {"a": 0.95, "b": 0.05})])
    typed = Engine(q=choice("b", 0.4, {"a": 0.4, "b": 0.5, "c": 0.1}))
    answer = one(ask(english, typed, "english-then-typed", trace=True))
    assert english.calls[1] == ["q"] and answer["eliminated"] == ["c"] and answer["resolved_by"] == "narrowed"
    assert answer["choice"] == "a" and answer["probabilities"]["c"] == 0.0


def test_unsettled_answer_is_uncertain_with_also_check():
    english = Engine(q=choice("a", 0.5, {"a": 0.5, "b": 0.5, "c": 0.0}))
    typed = Engine(q=choice("b", 0.5, {"a": 0.5, "b": 0.5, "c": 0.0}))
    r = one(ask(english, typed, "english-then-typed"))
    assert r["uncertain"] is True and (r.get("unknown") or r["also_check"])


def test_auto_skips_english_for_noul_but_english_then_typed_does_not():
    english, typed = Engine(q={"noul": 0.9, "answer_confidence": 0.95}), Engine(q={"noul": 0.1, "answer_confidence": 0.9})
    auto = one(ask(english, typed, "auto", {"q": NOUL}))
    assert auto["answered_by"] == "laya-typed" and english.calls == []
    assert one(ask(english, typed, "english-then-typed", {"q": NOUL}))["answered_by"] == "laya-english"


def test_most_confident_takes_the_stronger_model_and_reports_disagreement():
    r = one(ask(Engine(q=choice("a", 0.7)), Engine(q=choice("b", 0.95)), "most-confident"))
    assert r["choice"] == "b" and r["answered_by"] == "laya-typed"
    assert r["disagreement"] == {"laya-english": "a", "laya-typed": "b"}


def test_average_picks_the_best_mean_probability():
    english = Engine(q=choice("a", 0.5, {"a": 0.5, "b": 0.4, "c": 0.1}))
    typed = Engine(q=choice("b", 0.6, {"a": 0.1, "b": 0.6, "c": 0.3}))
    r = one(ask(english, typed, "average"))
    assert r["choice"] == "b" and r["answered_by"] == "laya-english+laya-typed"


def test_consensus_needs_agreement_and_both_sure():
    assert one(ask(Engine(q=choice("a", 0.9)), Engine(q=choice("a", 0.9)), "consensus"))["uncertain"] is False
    split = one(ask(Engine(q=choice("a", 0.9)), Engine(q=choice("b", 0.9)), "consensus"))
    assert split["uncertain"] is True and split["unknown"] is True and sorted(split["candidates"]) == ["a", "b"]


def test_min_confidence_replaces_every_threshold():
    assert one(ask(Engine(q=choice("a", 0.5)), None, "english-only", min_confidence=0.4))["uncertain"] is False


def test_unknown_strategy_and_bad_question_are_422():
    assert ask(None, None, "vote").status_code == 422
    bad = {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "only"}}}
    assert ask(None, None, "english-only", bad).status_code == 422


def test_truncated_input_is_413():
    class Cut:
        def predict(self, *args, **kwargs):
            return {"answers": {}, "usage": {"truncated": True}}

    assert ask(Cut(), None, "english-only").status_code == 413


def test_strategies_endpoint_lists_all():
    body = TestClient(create_app(Registry(lambda m: None))).get("/v1/strategies").json()
    assert body["default"] == "auto" and {"english-only", "typed-only", "consensus"} <= set(body["strategies"])


def test_thresholds_prune_and_pair_ratios_are_applied_per_request():
    english = Engine(q=choice("a", 0.8))
    sure = ask(english, None, "english-only", thresholds={"3+": {"laya-english": 0.85}})
    assert one(sure)["uncertain"] is True  # 0.8 is under the 0.85 asked for
    english = Engine(q=choice("a", 0.8))
    assert one(ask(english, None, "english-only", thresholds={"2": {"laya-english": 0.5}}))["uncertain"] is False


def test_prune_ratio_zero_never_drops_an_option():
    english = Engine(q=choice("a", 0.5, {"a": 0.5, "b": 0.45, "c": 0.05}))
    typed = Engine(q=choice("b", 0.4, {"a": 0.4, "b": 0.5, "c": 0.1}))
    answer = one(ask(english, typed, "english-then-typed", trace=True, prune_ratio=0))
    assert "eliminated" not in answer and english.calls == [["q"]]
