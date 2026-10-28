"""Opt-in GPT/Claude review benchmark runner. Never executes on import.

A run explicitly transmits supplied test cases to the chosen API provider.
By default this CLI only prints the planned calls, with no network request.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.conversation_imports.evaluation import _load_array, score_reviews
from app.conversation_imports.prompts import build_review_prompt
from app.conversations.multimodel import BlockedProvider, ProviderHub

SUPPORTED = ("gpt","claude")
MAX_ANSWER = 12000


def run_benchmark(
    cases: list[dict], *, provider: str, hub: Any,
    limit: int, consent: bool,
) -> list[dict]:
    if not consent:
        raise PermissionError("An explicit billable API consent is required")
    if provider not in SUPPORTED or limit < 1 or limit > 8:
        raise ValueError("Supported: GPT/Claude with 1-8 cases per invocation")
    if not hub.available.get(provider,False):
        raise ValueError("Provider is not configured. No fallback is allowed")
    limit = min(limit, len(cases))
    results = []
    for case in cases[:limit]:
        refs = case.get("approvedMemories",[])
        if not isinstance(refs,list) or any(
            not isinstance(x,dict) or not isinstance(x.get("id"),str)
            or not isinstance(x.get("text"),str) for x in refs
        ):
            raise ValueError("Benchmark has invalid reference notes")
        candidate = case.get("candidate")
        if not isinstance(candidate,str) or not candidate:
            raise ValueError("Benchmark has invalid candidate text")
        allowed = {r["id"] for r in refs[:12]}
        prompt=build_review_prompt(candidate, refs)
        model=hub.select(provider,prompt)
        started=time.perf_counter()
        # The only network call in this module, gated by explicit consent.
        output=[]
        length=0
        try:
            for chunk in model.stream(prompt):
                if not isinstance(chunk,str):
                    continue
                length+=len(chunk)
                if length>MAX_ANSWER:
                    raise ValueError("Model answer is too long")
                output.append(chunk)
            raw="".join(output).strip()
            match=re.fullmatch(
                r"\s*```(?:json)?\s*(\{.*\})\s*```\s*",raw,
                flags=re.DOTALL|re.IGNORECASE,
            )
            if match:
                raw=match.group(1)
            result=json.loads(raw)
            if not isinstance(result,dict):
                raise TypeError("Model response must be a JSON object")
            verdict=result.get("verdict")
            ids=result.get("relatedMemoryIds")
            suggested=result.get("suggestedText")
            reason=result.get("reason")
            if (
                verdict not in {"new","duplicate","conflict","uncertain"}
                or not isinstance(ids,list) or len(ids)>12
                or any(not isinstance(x,str) or x not in allowed for x in ids)
                or not isinstance(suggested,str) or len(suggested)>2000
                or not isinstance(reason,str) or len(reason)>500
            ):
                raise ValueError("Model response violates review contract")
            # Match the live review policy: unsupported conflict/duplicate
            # claims and empty 'new' suggestions are not confirmed labels.
            if verdict in {"duplicate","conflict"} and not ids:
                verdict="uncertain"
            if verdict=="new" and not suggested.strip():
                verdict="uncertain"
        except (ValueError,TypeError,KeyError,json.JSONDecodeError):
            verdict="invalid"
            ids=[]
        elapsed=round((time.perf_counter()-started)*1000)
        results.append({
            "caseId":case["caseId"], "provider":provider,
            "model":getattr(model,"model",None),
            "verdict":verdict, "relatedMemoryIds":ids,
            "elapsedMs":elapsed,
            "evaluatedAt":datetime.now(UTC).isoformat(),
        })
    return results


def main()->None:
    parser=argparse.ArgumentParser(description="Preview or explicitly run memory review API benchmark")
    parser.add_argument("--gold",type=Path,required=True)
    parser.add_argument("--provider",required=True,choices=SUPPORTED)
    parser.add_argument("--max-cases",type=int,default=4)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--confirm-api-charges",action="store_true")
    args=parser.parse_args()
    cases=_load_array(args.gold)
    if not 1<=args.max_cases<=8:
        parser.error("--max-cases must be between 1 and 8")
    count=min(len(cases),args.max_cases)
    if not args.execute:
        print(json.dumps({
            "mode":"dry-run","networkCalls":0,"plannedProvider":args.provider,
            "plannedCases":count,
            "notice":"Use --execute --confirm-api-charges --output FILE to invoke the provider.",
        },ensure_ascii=False,indent=2))
        return
    if not args.confirm_api_charges:
        parser.error("Real API usage requires --confirm-api-charges")
    if args.output is None:
        parser.error("Real API usage requires --output FILE")
    if args.output.exists():
        parser.error("Output already exists; choose a new file to avoid data loss")
    hub=ProviderHub.from_environment(
        BlockedProvider("auto","Automatic model routing is disabled in this benchmark")
    )
    if not hub.available.get(args.provider,False):
        parser.error("Provider API key is not configured; no model call was made")
    output=run_benchmark(
        cases,provider=args.provider,hub=hub,
        limit=args.max_cases,consent=True,
    )
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "output":str(args.output),
        "score":score_reviews(cases,output),
        "note":"Latency is measured; API token usage and actual charges are not available.",
    },ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
