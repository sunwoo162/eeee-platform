"""Deterministic scoring without making paid API calls or fabricating measurements."""
import json
from pathlib import Path

import pytest

from app.conversation_imports.evaluation import score_reviews


def fixture_cases():
    path=Path(__file__).resolve().parents[4]/"docs"/"architecture"/"memory-review-benchmark.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_curated_cases_are_complete():
    cases=fixture_cases()
    assert len(cases)>=8
    assert all(item.get("candidate") and item.get("approvedMemories") is not None
               for item in cases)
    assert len({x["caseId"] for x in cases})==len(cases)


def test_eval_reports_missing_invalid_and_unsupported_references():
    cases=fixture_cases()
    predictions=[
        {"caseId":cases[0]["caseId"],"provider":"gpt",
         "verdict":cases[0]["expectedVerdict"],"relatedMemoryIds":cases[0]["expectedRelatedIds"]},
        {"caseId":cases[1]["caseId"],"provider":"gpt",
         "verdict":"conflict","relatedMemoryIds":["other-project-memory"]},
        {"caseId":cases[0]["caseId"],"provider":"claude",
         "verdict":"uncertain","relatedMemoryIds":[]},
    ]
    scores=score_reviews(cases,predictions)
    assert scores["benchmarkSize"]==len(cases)
    assert scores["providers"]["gpt"]["submittedCount"]==2
    assert scores["providers"]["gpt"]["unsupportedReferenceCount"]==1
    assert scores["providers"]["gpt"]["coverage"]==round(2/len(cases),4)
    assert scores["providers"]["gpt"]["verdictAccuracy"]==round(2/len(cases),4)
    assert scores["providers"]["claude"]["verdictAccuracy"]==0


def test_eval_disallows_unknown_cases_duplicate_and_broken_gold():
    cases=fixture_cases()
    pred={"caseId":cases[0]["caseId"],"provider":"gpt","verdict":"new","relatedMemoryIds":[]}
    with pytest.raises(ValueError,match="Duplicate"):
        score_reviews(cases,[pred,pred])
    with pytest.raises(ValueError,match="Unknown"):
        score_reviews(cases,[dict(pred,caseId="foreign")])
    with pytest.raises(ValueError,match="Malformed"):
        score_reviews([dict(cases[0],expectedVerdict="anything")],[])
