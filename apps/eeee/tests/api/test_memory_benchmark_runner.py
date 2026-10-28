"""Model review benchmark requires opt-in and never changes local memories."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.conversation_imports.evaluation_runner import main, run_benchmark


class FakeProvider:
    model="fake-benchmark"
    def __init__(self, raw: str):
        self.raw=raw
        self.prompts=[]

    def stream(self, prompt):
        self.prompts.append(prompt)
        yield self.raw


class FakeHub:
    def __init__(self, raw: str):
        self.available={"gpt":True,"claude":False}
        self.model=FakeProvider(raw)
    def select(self, provider,prompt):
        assert provider=="gpt"
        return self.model


def _fixture() -> list[dict]:
    path=Path(__file__).resolve().parents[4]/"docs"/"architecture"/"memory-review-benchmark.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_runner_never_calls_model_without_explicit_consent():
    cases=_fixture()
    hub=FakeHub('{"verdict":"new"}')
    with pytest.raises(PermissionError):
        run_benchmark(cases,provider="gpt",hub=hub,limit=1,consent=False)
    with pytest.raises(ValueError):
        run_benchmark(cases,provider="claude",hub=hub,limit=1,consent=True)
    assert hub.model.prompts==[]


def test_runner_uses_same_scoped_prompt_and_scores_valid_reference():
    cases=_fixture()
    first=cases[0]
    hub=FakeHub(json.dumps({
        "verdict":first["expectedVerdict"],
        "suggestedText":first["candidate"],
        "reason":"Matches prior stack",
        "relatedMemoryIds":first["expectedRelatedIds"],
    }))
    predictions=run_benchmark(cases,provider="gpt",hub=hub,limit=1,consent=True)
    assert predictions[0]["verdict"]==first["expectedVerdict"]
    assert predictions[0]["relatedMemoryIds"]==first["expectedRelatedIds"]
    assert len(hub.model.prompts)==1
    text=hub.model.prompts[0][1]["content"]
    assert first["candidate"] in text
    assert first["approvedMemories"][0]["text"] in text
    assert "elapsedMs" in predictions[0]


def test_runner_rejects_hallucinated_reference_without_scoring_as_success():
    hub=FakeHub(json.dumps({
        "verdict":"conflict","suggestedText":"Use anything",
        "reason":"Unsupported source","relatedMemoryIds":["not-in-gold"],
    }))
    predictions=run_benchmark(_fixture(),provider="gpt",hub=hub,limit=1,consent=True)
    assert predictions[0]["verdict"]=="invalid"


def test_runner_dry_run_cannot_trigger_external_provider(tmp_path,monkeypatch,capsys):
    path=Path(__file__).resolve().parents[4]/"docs"/"architecture"/"memory-review-benchmark.json"
    monkeypatch.setattr(sys,"argv",[
        "evaluation_runner","--gold",str(path),"--provider","gpt",
    ])
    main()
    out=json.loads(capsys.readouterr().out)
    assert out["networkCalls"]==0
    assert out["plannedCases"]==4
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("malformed", [
    "[]", "null", '"hello"',
    json.dumps({
        "verdict": "new", "suggestedText": "Use React",
        "reason": "Model response", "relatedMemoryIds": ["nonexistent"],
    }),
])
def test_runner_marks_invalid_payload_without_crashing(malformed):
    result = run_benchmark(
        _fixture(), provider="gpt", hub=FakeHub(malformed), limit=1, consent=True,
    )
    assert result[0]["verdict"] == "invalid"
    assert result[0]["relatedMemoryIds"] == []


@pytest.mark.parametrize("verdict,related_ids,suggestion", [
    ("duplicate", [], "Use React"),
    ("conflict", [], "Use Flask"),
    ("new", [], ""),
])
def test_runner_downgrades_unsubstantiated_memory_claims(verdict, related_ids, suggestion):
    hub = FakeHub(json.dumps({
        "verdict": verdict, "suggestedText": suggestion,
        "reason": "Not enough support", "relatedMemoryIds": related_ids,
    }))
    result = run_benchmark(_fixture(), provider="gpt", hub=hub, limit=1, consent=True)
    assert result[0]["verdict"] == "uncertain"
