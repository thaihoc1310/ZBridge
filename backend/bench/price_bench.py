"""Measure the price-inquiry prompt against hand-written Vietnamese cases.

The cost here is the mirror of the mention classifier: a wrong TAG interrupts a
customer's group over the word "giá", so false positives are what this counts.

    backend/.venv/bin/python -m bench.price_bench --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import settings
from app.services.mention_classifier import (
    PRICE_CLASSIFIER_PROMPT,
    PRICE_PROMPT_VERSION,
    MentionClassification,
    classify_payload,
)

GOLDEN = Path(__file__).with_name("price_golden.jsonl")


def payload(text: str) -> dict:
    return {
        "prompt_version": PRICE_PROMPT_VERSION,
        "current_message_id": "m1",
        "targets": [{"target_id": "T1"}],
        "conversation": [
            {
                "message_id": "m1",
                "sent_at": "2026-08-21T09:00:00+00:00",
                "sender": "P1",
                "text": text,
            }
        ],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--tau", type=float, default=settings.llm_price_confidence)
    args = parser.parse_args()

    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    gate = asyncio.Semaphore(args.concurrency)

    async def run(case: dict) -> tuple[dict, str, float, str | None]:
        async with gate:
            try:
                result = await classify_payload(
                    payload(case["text"]), prompt=PRICE_CLASSIFIER_PROMPT
                )
            except Exception as exc:  # noqa: BLE001 - bench reports, never crashes
                return case, "ERROR", 0.0, f"{type(exc).__name__}: {exc}"[:80]
            decision = next(iter(result.decisions), None)
            if decision is None:
                return case, "MISSING", 0.0, None
            return case, decision.classification.value, decision.confidence, None

    outcomes = await asyncio.gather(
        *(run(case) for _ in range(args.repeats) for case in cases)
    )

    false_tag, missed_tag, correct = [], [], 0
    errors = []
    for case, label, confidence, error in outcomes:
        if error:
            errors.append(f"{case['id']}: {error}")
            continue
        tagged = label == MentionClassification.NEED_RESPONSE.value and confidence >= args.tau
        want = case["expect"] == "TAG"
        if tagged == want:
            correct += 1
        elif tagged:
            false_tag.append(f"{case['id']} ({label}@{confidence:.2f})")
        else:
            missed_tag.append(f"{case['id']} ({label}@{confidence:.2f})")

    total = len(outcomes)
    print(f"model={settings.llm_model} tau={args.tau} cases={len(cases)} runs={total}")
    print(f"  dung          : {correct}/{total} ({100 * correct / total:.1f}%)")
    print(f"  TAG SAI (spam): {len(false_tag)}  {sorted(set(false_tag)) or ''}")
    print(f"  bo sot        : {len(missed_tag)}  {sorted(set(missed_tag)) or ''}")
    if errors:
        print(f"  loi           : {sorted(set(errors))}")


if __name__ == "__main__":
    asyncio.run(main())
