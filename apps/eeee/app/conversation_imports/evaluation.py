"""Offline, reproducible comparison of project-memory review model outputs.

Consumes manually curated gold labels and recorded JSON predictions.
It DOES NOT call providers, upload transcripts, or change project memory.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

VERDICTS = frozenset({"new","duplicate","conflict","uncertain"})


def score_reviews(gold: list[dict], predictions: list[dict]) -> dict:
    if not gold:
        raise ValueError("Gold benchmark must not be empty")
    cases: dict[str, dict] = {}
    for case in gold:
        key = case.get("caseId")
        expected = case.get("expectedVerdict")
        if not isinstance(key,str) or not key or key in cases or expected not in VERDICTS:
            raise ValueError("Malformed or duplicate gold case")
        refs = case.get("expectedRelatedIds", [])
        allowed = case.get("approvedMemoryIds",[])
        if not isinstance(refs,list) or not isinstance(allowed,list) or any(
            not isinstance(x,str) for x in refs+allowed
        ):
            raise ValueError("Invalid gold reference IDs")
        if not set(refs).issubset(set(allowed)):
            raise ValueError("Gold references are not supplied approved memories")
        cases[key]=case
    grouped: dict[str,dict[str,dict]] = defaultdict(dict)
    for item in predictions:
        name=item.get("provider")
        key=item.get("caseId")
        if not isinstance(name,str) or not name or key not in cases:
            raise ValueError("Unknown provider or case")
        if key in grouped[name]:
            raise ValueError("Duplicate provider/case prediction")
        grouped[name][key]=item
    summary:dict[str,dict]={}
    for provider,results in sorted(grouped.items()):
        matched=0
        valid=0
        reference_exact=0
        hallucinated=0
        predicted_conflict=0
        true_positive_conflict=0
        actual_conflicts=sum(
            case["expectedVerdict"]=="conflict" for case in cases.values()
        )
        for key,gold_case in cases.items():
            prediction=results.get(key)
            if prediction is None:
                continue
            verdict=prediction.get("verdict")
            references=prediction.get("relatedMemoryIds")
            if verdict not in VERDICTS or not isinstance(references,list) or any(
                not isinstance(ref,str) for ref in references
            ):
                continue
            valid+=1
            if verdict==gold_case["expectedVerdict"]:
                matched+=1
            if set(references)==set(gold_case.get("expectedRelatedIds",[])):
                reference_exact+=1
            hallucinated+=sum(
                ref not in gold_case.get("approvedMemoryIds",[])
                for ref in references
            )
            if verdict=="conflict":
                predicted_conflict+=1
                if gold_case["expectedVerdict"]=="conflict":
                    true_positive_conflict+=1
        total=len(cases)
        summary[provider]={
            "caseCount":total,
            "submittedCount":len(results),
            "validCount":valid,
            "coverage":round(valid/total,4),
            # Missing/invalid predictions are treated as incorrect.
            "verdictAccuracy":round(matched/total,4),
            "referenceExactRate":round(reference_exact/total,4),
            "unsupportedReferenceCount":hallucinated,
            "conflictPrecision":(
                round(true_positive_conflict/predicted_conflict,4)
                if predicted_conflict else None
            ),
            "conflictRecall":(
                round(true_positive_conflict/actual_conflicts,4)
                if actual_conflicts else None
            ),
        }
    return {"benchmarkSize":len(cases),"providers":summary}


def _load_array(path:Path)->list[dict]:
    # Do not evaluate arbitrarily large dumps of actual user conversations.
    if path.stat().st_size>1_000_000:
        raise ValueError("Evaluation file must be 1 MB or smaller")
    with path.open(encoding="utf-8") as handle:
        result=json.load(handle)
    if not isinstance(result,list) or any(not isinstance(x,dict) for x in result):
        raise ValueError("Evaluation file must be an array of objects")
    return result


def main()->None:
    parser=argparse.ArgumentParser(description="Evaluate stored AI memory-review predictions, offline")
    parser.add_argument("--gold",type=Path,required=True)
    parser.add_argument("--predictions",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(
        score_reviews(_load_array(args.gold),_load_array(args.predictions)),
        ensure_ascii=False,indent=2,
    ))


if __name__=="__main__":
    main()
