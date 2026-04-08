import argparse
import json
import time
from pathlib import Path

import httpx


def stream_chat(base_url: str, question: str, thread_id: str) -> dict:
    final_answer = ""
    done_payload = {}

    with httpx.stream(
        "POST",
        f"{base_url}/chat",
        json={"message": question, "thread_id": thread_id},
        timeout=60.0,
    ) as resp:
        resp.raise_for_status()

        event_type = None
        for line in resp.iter_lines():
            if not line:
                if event_type == "done":
                    break
                continue

            if line.startswith("event:"):
                event_type = line.replace("event:", "", 1).strip()
                continue

            if line.startswith("data:"):
                data = json.loads(line.replace("data:", "", 1).strip())
                if event_type == "token":
                    final_answer += data.get("text", "")
                elif event_type == "done":
                    done_payload = data

    return {
        "answer": final_answer,
        "done": done_payload,
    }


def evaluate_case(base_url: str, case: dict, idx: int) -> dict:
    started = time.perf_counter()
    result = stream_chat(base_url, case["question"], f"eval_{idx}")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    answer = (result.get("answer") or "").lower()
    done = result.get("done") or {}

    expected = [k.lower() for k in case.get("expected_keywords", [])]
    keyword_hits = sum(1 for k in expected if k in answer)
    keyword_score = keyword_hits / len(expected) if expected else 1.0

    required_status = case.get("required_status", "ok")
    actual_status = done.get("status", "error")
    status_ok = required_status == actual_status

    factuality_like = 1.0 if (status_ok and keyword_score >= 0.6) else 0.0

    return {
        "question": case["question"],
        "required_status": required_status,
        "actual_status": actual_status,
        "keyword_score": round(keyword_score, 2),
        "factuality_like": factuality_like,
        "latency_ms": elapsed_ms,
        "cache_hit": done.get("cache_hit", False),
        "tools_used": done.get("tools_used", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight offline eval against local /chat SSE endpoint")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--dataset", default=str(Path(__file__).parent / "sample_dataset.json"), help="Path to JSON dataset")
    parser.add_argument("--factuality-threshold", type=float, default=0.98, help="Target threshold before demo")
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    rows = [evaluate_case(args.base_url, case, i) for i, case in enumerate(dataset, start=1)]

    avg_factuality = sum(r["factuality_like"] for r in rows) / max(len(rows), 1)
    p90_latency = sorted(r["latency_ms"] for r in rows)[int(max(len(rows) - 1, 0) * 0.9)] if rows else 0.0

    print("=== Evaluation Report ===")
    for r in rows:
        print(
            f"- status={r['actual_status']:<14} factuality={r['factuality_like']:.2f} "
            f"keywords={r['keyword_score']:.2f} latency={r['latency_ms']}ms q={r['question']}"
        )

    print("\n=== Summary ===")
    print(f"Avg factuality-like score: {avg_factuality:.2%}")
    print(f"P90 latency: {p90_latency} ms")
    print(f"Threshold: {args.factuality_threshold:.2%}")

    if avg_factuality < args.factuality_threshold:
        raise SystemExit("FAIL: Factuality threshold not met")

    print("PASS: Factuality threshold met")


if __name__ == "__main__":
    main()
