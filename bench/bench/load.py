"""Concurrent load generator for the llama.cpp OpenAI-compatible server.

One invocation measures one slot count. scripts/stress-test.ps1 owns the sweep,
the container restarts, and the GPU telemetry; this process only generates load
and prints a summary JSON object on stdout.

Endpoint: `/v1/chat/completions` (verified live on 2026-10-05 that llama.cpp's
OpenAI-compat layer honours `ignore_eos` — a "Say hi." prompt with
`max_tokens: 300, ignore_eos: true` returned `completion_tokens: 300` and
`finish_reason: "length"` instead of stopping early). The `/completion` native
fallback described in the task brief was not needed.

Three details decide whether the numbers mean anything:

* ignore_eos with a fixed max_tokens, so every request emits an identical token
  count. Without it you measure the model's verbosity.
* A distinct prompt per client, so llama.cpp's prefix cache cannot serve one
  slot's prefill from another's.
* Streaming, so time to first token is observable at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time

import httpx

from bench.metrics import RequestSample, summarize

# Ordinary words, so the tokenizer behaves as it would on real text; a repeated
# single character would not. The body is drawn from the seed rather than being a
# fixed string, which matters more than it looks: see build_prompt.
_WORDS = (
    "server model token latency cache prompt decode prefill throughput slot context "
    "window kernel memory bandwidth quantize weight tensor batch stream request reply "
    "inbox message draft classify archive journal policy gate agent briefing household "
    "electricity meter amortize capex median listing provider hosted rented owned"
).split()

# Measured on this model's tokenizer via the server's /tokenize endpoint on
# 2026-10-05: 6.21 chars/token at 250 requested tokens, settling to 6.56-6.58 from
# 1000 upward. The naive 4.0 used before made --prompt-tokens 1000 send only 610
# tokens, a 39% undershoot that would have mislabelled every row of the writeup.
_CHARS_PER_TOKEN = 6.55


def build_prompt(seed: int, approx_tokens: int) -> str:
    """A prompt of ~approx_tokens tokens sharing no long run of text with any other seed.

    Every word comes from the seed, not just an opening line. A varying head on a
    fixed body is NOT enough, and the difference is not subtle: measured against this
    server on 2026-10-05, prompts built that way were served 99.9% from llama.cpp's
    cache across two clients and reported a prefill rate of 55,934 tok/s against a
    real 2,340 -- a 24x fiction. Seed-derived bodies measured 4.2% cached.

    Deterministic in the seed, so a rerun of the same sweep point is comparable.
    """
    rng = random.Random(seed)
    target_chars = int(approx_tokens * _CHARS_PER_TOKEN)
    parts = [f"Note {rng.randrange(10 ** 9)}. Summarize these notes."]
    size = len(parts[0])
    while size < target_chars:
        word = rng.choice(_WORDS)
        parts.append(word)
        size += len(word) + 1
    return " ".join(parts)[:target_chars]


async def one_request(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> RequestSample:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.0,
    }

    started = time.perf_counter()
    ttft: float | None = None
    usage: dict = {}
    timings: dict = {}
    deltas = 0

    async with client.stream(
        "POST", f"{base_url}/v1/chat/completions", json=payload
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            chunk = line[len("data: ") :].strip()
            if chunk == "[DONE]":
                break
            event = json.loads(chunk)
            choices = event.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content"):
                deltas += 1
                if ttft is None:
                    ttft = (time.perf_counter() - started) * 1000.0
            if event.get("usage"):
                usage = event["usage"]
            if event.get("timings"):
                timings = event["timings"]

    latency_ms = (time.perf_counter() - started) * 1000.0
    if ttft is None:
        raise RuntimeError("stream produced no content deltas")

    output_tokens = int(usage.get("completion_tokens") or timings.get("predicted_n") or deltas)
    prompt_tokens = int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)

    return RequestSample(
        ttft_ms=ttft,
        latency_ms=latency_ms,
        output_tokens=output_tokens,
        prompt_tokens=prompt_tokens,
        prompt_ms=float(timings.get("prompt_ms") or 0.0),
        cached_tokens=cached,
    )


async def run_slot_point(
    base_url: str,
    model: str,
    slots: int,
    ctx_per_slot: int,
    requests_per_client: int,
    prompt_tokens: int,
    max_tokens: int,
) -> dict:
    """Drive `slots` concurrent clients and summarize the measured requests.

    Each client's first request is discarded as warm-up, so the returned sample
    count is slots * (requests_per_client - 1).
    """
    if requests_per_client < 2:
        raise ValueError("requests_per_client must be at least 2 (one is warm-up)")

    collected: list[RequestSample] = []
    spans: list[tuple[float, float]] = []

    async def client_loop(index: int, client: httpx.AsyncClient) -> None:
        for round_index in range(requests_per_client):
            prompt = build_prompt(index * 1000 + round_index, prompt_tokens)
            started = time.perf_counter()
            sample = await one_request(client, base_url, model, prompt, max_tokens)
            finished = time.perf_counter()
            if round_index > 0:  # discard warm-up
                collected.append(sample)
                spans.append((started, finished))

    # Separate clients so each concurrent stream gets its own connection.
    clients = [httpx.AsyncClient(timeout=httpx.Timeout(600.0)) for _ in range(slots)]
    try:
        await asyncio.gather(*(client_loop(i, clients[i]) for i in range(slots)))
    finally:
        await asyncio.gather(*(c.aclose() for c in clients), return_exceptions=True)

    if not spans:
        raise RuntimeError("no measured requests completed")
    # Wall time of the measured window: earliest measured start to latest
    # measured end. Warm-up requests are excluded from both ends, so the window
    # covers only the period when every slot was already loaded.
    measured_wall_s = max(end for _, end in spans) - min(start for start, _ in spans)
    return summarize(collected, measured_wall_s, slots, ctx_per_slot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One slot-count load point.")
    parser.add_argument("--base-url", default="http://hpz440:8080")
    parser.add_argument("--model", required=True, help="llama.cpp container model path")
    parser.add_argument("--slots", type=int, required=True)
    parser.add_argument("--ctx-per-slot", type=int, required=True)
    parser.add_argument("--requests-per-client", type=int, default=5)
    parser.add_argument("--prompt-tokens", type=int, default=1000)
    parser.add_argument("--max-tokens", type=int, default=300)
    args = parser.parse_args(argv)

    result = asyncio.run(
        run_slot_point(
            base_url=args.base_url,
            model=args.model,
            slots=args.slots,
            ctx_per_slot=args.ctx_per_slot,
            requests_per_client=args.requests_per_client,
            prompt_tokens=args.prompt_tokens,
            max_tokens=args.max_tokens,
        )
    )
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
