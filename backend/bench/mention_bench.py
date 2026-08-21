"""Benchmark the mention classifier prompt across providers.

Measures the decision the pipeline actually makes (skip vs tag) rather than raw
label accuracy, because a wrong skip silently drops a business task while a
wrong tag only costs one extra message.

Usage:
    backend/.venv/bin/python -m bench.mention_bench --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from openai import AsyncOpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.services.mention_classifier import (
    CLASSIFIER_PROMPT,
    PROMPT_VERSION,
    MentionClassificationResult,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).with_name("mention_golden.jsonl")
SKIP_LABELS = {"ACKNOWLEDGEMENT", "FYI"}
# OpenAI strict mode demands additionalProperties:false on every object; the raw
# pydantic schema omits it, so use the SDK's own normalizer for all providers.
STRICT_SCHEMA = to_strict_json_schema(MentionClassificationResult)
FPT_BASE_URL = "https://mkp-api.fptcloud.com"


def env(name: str) -> str:
    for candidate in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return ""


@dataclass(frozen=True)
class ModelConfig:
    key: str
    model: str
    base_url: str | None
    api_key_env: str
    # USD per token, from FPT /v1/models; None when we have no authoritative price.
    price_in: float | None = None
    price_out: float | None = None
    extra: dict = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)


CONFIGS = [
    ModelConfig(
        key="gpt-5.4-nano",
        model="gpt-5.4-nano-2026-03-17",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        extra={"reasoning_effort": "none", "max_completion_tokens": 4000},
    ),
    ModelConfig(
        key="deepseek-v4-flash",
        model="DeepSeek-V4-Flash",
        base_url=FPT_BASE_URL,
        api_key_env="FPTAI_API_KEY",
        price_in=0.00000014,
        price_out=0.00000028,
        extra={"temperature": 0, "max_tokens": 4000},
    ),
    ModelConfig(
        key="deepseek-v4-flash-nothink",
        model="DeepSeek-V4-Flash",
        base_url=FPT_BASE_URL,
        api_key_env="FPTAI_API_KEY",
        price_in=0.00000014,
        price_out=0.00000028,
        extra={"temperature": 0, "max_tokens": 4000},
        extra_body={"chat_template_kwargs": {"thinking": False}},
    ),
    ModelConfig(
        key="gpt-oss-20b",
        model="gpt-oss-20b",
        base_url=FPT_BASE_URL,
        api_key_env="FPTAI_API_KEY",
        price_in=0.00000005,
        price_out=0.00000020,
        extra={"temperature": 0, "max_tokens": 4000},
    ),
]


def load_cases() -> list[dict]:
    cases = []
    for line in GOLDEN.read_text().splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def build_payload(case: dict) -> dict:
    """Mirror _prepare_job so the bench exercises the production payload shape."""
    base = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    conversation = []
    for index, (sender, text) in enumerate(case["conversation"]):
        conversation.append(
            {
                "message_id": f"m{index + 1}",
                "sent_at": (base + timedelta(minutes=index)).isoformat(),
                "sender": sender,
                "text": text,
            }
        )
    return {
        "prompt_version": PROMPT_VERSION,
        "current_message_id": conversation[-1]["message_id"],
        "targets": [{"target_id": label} for label in sorted(case["targets"])],
        "conversation": conversation,
    }


@dataclass
class Attempt:
    case_id: str
    ok: bool
    error: str | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    decisions: dict[str, tuple[str, float]] = field(default_factory=dict)


async def run_one(client: AsyncOpenAI, config: ModelConfig, case: dict) -> Attempt:
    payload = build_payload(case)
    started = perf_counter()
    try:
        response = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "mention_classification",
                    "strict": True,
                    "schema": STRICT_SCHEMA,
                },
            },
            extra_body=config.extra_body or None,
            **config.extra,
        )
    except Exception as exc:  # noqa: BLE001 - bench reports, never crashes
        return Attempt(case["id"], False, f"{type(exc).__name__}: {exc}"[:160],
                       round((perf_counter() - started) * 1000), 0, 0)

    latency = round((perf_counter() - started) * 1000)
    usage = response.usage
    message = response.choices[0].message
    # FPT's proxy puts the guided-decoding output in reasoning_content and leaves
    # content null for DeepSeek unless thinking is disabled. Accept either slot.
    body = message.content or getattr(message, "reasoning_content", None) or ""
    try:
        parsed = MentionClassificationResult.model_validate_json(body)
    except ValidationError as exc:
        return Attempt(case["id"], False, f"SCHEMA_INVALID: {str(exc)[:120]}", latency,
                       usage.prompt_tokens, usage.completion_tokens)

    return Attempt(
        case["id"], True, None, latency, usage.prompt_tokens, usage.completion_tokens,
        {d.target_id: (d.classification.value, d.confidence) for d in parsed.decisions},
    )


async def run_config(config: ModelConfig, cases: list[dict], repeats: int,
                     concurrency: int) -> list[Attempt]:
    key = env(config.api_key_env)
    if not key:
        print(f"  !! {config.api_key_env} rong, bo qua {config.key}", file=sys.stderr)
        return []
    client = AsyncOpenAI(api_key=key, base_url=config.base_url, timeout=90.0, max_retries=2)
    gate = asyncio.Semaphore(concurrency)

    async def guarded(case: dict) -> Attempt:
        async with gate:
            return await run_one(client, config, case)

    jobs = [guarded(case) for _ in range(repeats) for case in cases]
    attempts = await asyncio.gather(*jobs)
    await client.close()
    return list(attempts)


def score(config: ModelConfig, cases: list[dict], attempts: list[Attempt],
          thresholds: list[float]) -> dict:
    by_id = {case["id"]: case for case in cases}
    valid = [a for a in attempts if a.ok]
    latencies = sorted(a.latency_ms for a in valid) or [0]

    per_threshold = {}
    for tau in thresholds:
        false_skip: list[str] = []
        correct_skip = 0
        missed_skip = 0
        missing = 0
        for attempt in valid:
            case = by_id[attempt.case_id]
            for target, expected in case["targets"].items():
                got = attempt.decisions.get(target)
                # A missing decision is fail-safe in production: process_classification
                # only skips when a decision exists, so the target still gets tagged.
                if got is None:
                    missing += 1
                    skipped = False
                else:
                    label, confidence = got
                    skipped = label in SKIP_LABELS and confidence >= tau
                if expected in SKIP_LABELS:
                    correct_skip += skipped
                    missed_skip += not skipped
                elif skipped:
                    label, confidence = got
                    false_skip.append(f"{attempt.case_id}/{target}:{label}@{confidence:.2f}")
        per_threshold[tau] = {
            "false_skip": len(false_skip),
            "false_skip_detail": sorted(set(false_skip)),
            "correct_skip": correct_skip,
            "missed_skip": missed_skip,
            "missing_decisions": missing,
        }

    label_hits = 0
    label_total = 0
    confusion: dict[str, int] = defaultdict(int)
    for attempt in valid:
        case = by_id[attempt.case_id]
        for target, expected in case["targets"].items():
            label_total += 1
            got = attempt.decisions.get(target)
            label = got[0] if got else "MISSING"
            allowed = {expected, *case.get("also_ok", {}).get(target, [])}
            label_hits += label in allowed
            if label not in allowed:
                confusion[f"{expected}->{label}"] += 1

    # Stability: same case, different repeats, same label?
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for attempt in valid:
        for target, (label, _) in attempt.decisions.items():
            grouped[(attempt.case_id, target)].add(label)
    unstable = sum(1 for labels in grouped.values() if len(labels) > 1)

    tokens_in = sum(a.input_tokens for a in valid)
    tokens_out = sum(a.output_tokens for a in valid)
    cost = None
    if config.price_in is not None and valid:
        cost = (tokens_in * config.price_in + tokens_out * config.price_out) / len(valid)

    return {
        "key": config.key,
        "model": config.model,
        "calls": len(attempts),
        "schema_ok": len(valid),
        "schema_ok_pct": 100 * len(valid) / len(attempts) if attempts else 0,
        "errors": sorted({a.error for a in attempts if a.error})[:5],
        "label_acc_pct": 100 * label_hits / label_total if label_total else 0,
        "confusion": dict(sorted(confusion.items(), key=lambda kv: -kv[1])),
        "unstable_targets": unstable,
        "total_targets": len(grouped),
        "p50_ms": latencies[len(latencies) // 2],
        "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "avg_in": tokens_in / len(valid) if valid else 0,
        "avg_out": tokens_out / len(valid) if valid else 0,
        "usd_per_call": cost,
        "thresholds": per_threshold,
    }


def report(results: list[dict], thresholds: list[float], default_tau: float) -> str:
    out = []
    out.append(f"## Ket qua (tau mac dinh = {default_tau})\n")
    header = ("| model | schema ok | label acc | false skip | correct skip | missed skip "
              "| thieu decision | khong on dinh | p50 | p95 | tok in/out | USD/1k call |")
    out.append(header)
    out.append("|" + "---|" * 12)
    for r in results:
        t = r["thresholds"][default_tau]
        cost = f"{r['usd_per_call'] * 1000:.3f}" if r["usd_per_call"] is not None else "n/a"
        out.append(
            f"| {r['key']} | {r['schema_ok_pct']:.0f}% | {r['label_acc_pct']:.1f}% "
            f"| **{t['false_skip']}** | {t['correct_skip']} | {t['missed_skip']} "
            f"| {t['missing_decisions']} | {r['unstable_targets']}/{r['total_targets']} "
            f"| {r['p50_ms']}ms | {r['p95_ms']}ms "
            f"| {r['avg_in']:.0f}/{r['avg_out']:.0f} | {cost} |"
        )
    out.append("\n## Quet nguong confidence (false_skip / correct_skip)\n")
    out.append("| model | " + " | ".join(f"tau={t}" for t in thresholds) + " |")
    out.append("|" + "---|" * (len(thresholds) + 1))
    for r in results:
        cells = [f"{r['thresholds'][t]['false_skip']} / {r['thresholds'][t]['correct_skip']}"
                 for t in thresholds]
        out.append(f"| {r['key']} | " + " | ".join(cells) + " |")
    out.append("\n## Chi tiet\n")
    for r in results:
        out.append(f"### {r['key']} ({r['model']})")
        if r["errors"]:
            out.append(f"- loi: {r['errors']}")
        out.append(f"- nham nhan: {r['confusion'] or 'khong'}")
        t = r["thresholds"][default_tau]
        out.append(f"- FALSE SKIP @tau={default_tau}: {t['false_skip_detail'] or 'khong co'}")
        out.append("")
    return "\n".join(out)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--tau", type=float, default=0.65)
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    thresholds = [0.5, 0.65, 0.75, 0.85, 0.95]
    if args.tau not in thresholds:
        thresholds = sorted({*thresholds, args.tau})

    cases = load_cases()
    targets = sum(len(c["targets"]) for c in cases)
    configs = [c for c in CONFIGS if not args.only or c.key in args.only.split(",")]
    print(f"{len(cases)} case / {targets} target / {args.repeats} lan lap "
          f"/ {len(configs)} model\n", file=sys.stderr)

    results = []
    for config in configs:
        print(f"-> {config.key}", file=sys.stderr)
        attempts = await run_config(config, cases, args.repeats, args.concurrency)
        if attempts:
            results.append(score(config, cases, attempts, thresholds))

    text = report(results, thresholds, args.tau)
    print(text)
    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n(raw: {out})", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
