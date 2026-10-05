# Cost Model: When Does the HPZ440 Beat a Hosted Model?

Measured 2026-10-05 on the RTX 3060 12GB with Qwen2.5-7B-Instruct Q4_K_M.
Source data: `benchmarks/stress-20261005-091820.json`. Regenerate with
`uv --directory bench run python -m bench.report --sweep <file>` — pass an **absolute** path
to `<file>`: `--directory bench` moves the process's working directory into `bench/`, so a
path like `benchmarks/stress-<stamp>.json` typed relative to the repo root resolves to
`bench/benchmarks/...` and fails with `FileNotFoundError`.

## The question

"Tokens per dollar of hardware" is unbounded for a box you already own — run it longer and
the figure improves without limit. The decision-relevant form is the break-even volume: the
monthly token volume at which paying a hosted provider costs the same as amortized hardware
plus electricity.

## Assumptions

| Input | Value | Source |
| --- | --- | --- |
| Capex | $300 | RTX 3060 12GB, purchased 2026-09-29 |
| Amortization | 36 months | Assumption |
| Electricity | $0.17/kWh | Conrad's rate, 2026-10 |
| Powered hours | 720/month | The HPZ440 stays on |
| Token mix | 1000 in / 300 out per request | Jarvis triage shape: a message body in, a short classification out |
| Baseline GPU draw, model resident | 13.66 W | Measured, `nvidia-smi`, weights loaded, no requests in flight. The state the box sits in 24/7, not a cold-idle card |
| Load GPU draw | 168.07 W | Measured, peak sweep mean (1 slot; see Throughput below) |
| Endpoint | `/v1/chat/completions` | Verified live on 2026-10-05 to honour `ignore_eos` (`bench/bench/load.py`) |

## Throughput

| Slots | Ctx/slot | Prompt tok | Aggregate tok/s | Per-client tok/s | Prefill tok/s | TTFT p50 | TTFT p95 | GPU W mean | VRAM MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2048 | 1000 | 58.7 | 58.7 | 2223 | 519 ms | 524 ms | 168.07 | 4565.0 |
| 2 | 2048 | 1002 | 99.0 | 49.5 | 1124 | 1018 ms | 1024 ms | 166.25 | 4673.0 |
| 4 | 2048 | 1005 | 127.3 | 31.8 | 879 | 1589 ms | 2031 ms | 166.6 | 4899.0 |
| 8 | 2048 | 1007 | 145.7 | 18.2 | 771 | 2839 ms | 4144 ms | 164.88 | 5347.0 |

All four rows ran `--requests-per-client 5`, so percentiles come from `slots x 4` measured
requests (the first round discarded as warm-up): 4 samples at 1 slot, 32 at 8. The 1-slot p95
above is the slowest of four requests, not a tail latency in the usual sense.

All four rows passed the cache check: cached tokens stayed at roughly 2.6% of prompt tokens
across the sweep (105/4000 at 1 slot, up to 837/32236 at 8), well under the 25% contamination
threshold `bench/bench/metrics.py` enforces. Every `prefill_tps` figure above is a real
measurement, not a cache-inflated one.

Throughput did not stop scaling by 8 slots, but it stopped scaling proportionally well before
then. Aggregate output rose 58.7 -> 145.7 tok/s (2.48x) from 1 to 8 slots, but the GPU never
got more than 2.48x busier — the 4 -> 8 step bought only +14% more aggregate throughput for
+104% worse TTFT p95 (2031 ms -> 4144 ms) and a near-doubling of per-request latency (9.4 s ->
16.4 s median). Most of the usable gain is already in by 4 slots (127.3 tok/s, 2.17x), and
every slot added after that trades latency for a shrinking throughput return. For a
latency-sensitive workload like Jarvis triage (target: one message classified in under 10 s,
`docs/models.md`), 4 slots is already at that latency budget's edge (TTFT p95 2.0 s, request
latency p50 9.4 s); 8 slots exceeds it for the median request. Prefill also degraded as slots
rose (2223 -> 771 tok/s): prompt processing competes with decode for the same GPU across
slots, so per-request prefill throughput falls even as total output throughput rises. No
8-slot OOM occurred — VRAM peaked at 5347 MB of 12 GB, well inside headroom.

GPU power barely moved across the sweep (168.07 W at 1 slot down to 164.88 W at 8) — the card
is already close to saturated at one slot, and adding slots fills idle gaps rather than
drawing meaningfully more power. That is why the break-even model below uses the single peak
mean across the sweep (168.07 W, at 1 slot) rather than a per-slot-count figure: more
concurrency is nearly free in watts, so the watts term in the cost model does not need to vary
with the slot count chosen in production.

## Break-even

| Provider / model | Active h/month | Owning $/month | Hosted $/mixed Mtok | Break-even Mtok/month | Break-even requests/month |
| --- | --- | --- | --- | --- | --- |
| Together AI meta-llama/Meta-Llama-3.1-8B-Instruct | 30 | $10.79 | $0.1800 | 60.0 | 46,123 |
| DeepInfra meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo | 30 | $10.79 | $0.0246 | 438.5 | 337,275 |
| Together AI meta-llama/Meta-Llama-3.1-8B-Instruct | 100 | $12.63 | $0.1800 | 70.2 | 53,976 |
| DeepInfra meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo | 100 | $12.63 | $0.0246 | 513.1 | 394,696 |
| Together AI meta-llama/Meta-Llama-3.1-8B-Instruct | 300 | $17.88 | $0.1800 | 99.3 | 76,411 |
| DeepInfra meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo | 300 | $17.88 | $0.0246 | 726.4 | 558,757 |
| Together AI meta-llama/Meta-Llama-3.1-8B-Instruct | 720 | $28.91 | $0.1800 | 160.6 | 123,526 |
| DeepInfra meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo | 720 | $28.91 | $0.0246 | 1174.3 | 903,284 |

The headline, stated plainly: at Jarvis's actual load — roughly a couple of hundred emails a
month, call it 200 requests — the box does not win on price, by a wide margin. 200 requests at
the 1000/300 mix is 0.26 mixed Mtok/month, against a break-even of 60.0 Mmix/month for
Together AI at the 30 active-hours-a-month row — the **lowest** activity level modelled, and
therefore the one most favorable to owning the box (idle watts dominate the cost at low
activity, and 30 h/month is as low as this table goes). Even against that most-favorable row,
the box would need to run roughly **230x** its actual Jarvis volume before owning it beats
renting from Together. Jarvis's real duty cycle is in fact well below even 30 active
hours/month — 200 requests at the 8-slot median latency of 16.4 s is under an hour of active
GPU time — so 230x is a floor on the gap, not a point estimate: the true multiple, modelled at
Jarvis's real (lower) activity level, would be larger still. Against DeepInfra's $0.02/$0.04
pricing the gap is worse: break-even is 438.5 Mmix/month, roughly **1,690x** actual load.
Owning this GPU is not the cheaper way to run triage at this household's volume under either
hosted comparison. The reasons the box exists anyway are not dollar reasons — see "What this
does not say" below.

## What this does not say

- **GPU-only watts.** `nvidia-smi` reports the card, not the HP Z440 around it. Whole-box
  draw is materially higher, so the owning cost above is a **lower bound** and the real
  break-even volume is **higher** than the table says. A wall meter would close this.
- **The baseline is not a cold-idle GPU.** It is measured with the model resident in VRAM,
  because that is how the box runs. A card with no model loaded would draw less.
- **Quality is not matched to frontier models.** Every hosted row is a Llama-3.1-8B-class
  instruct model — the same tier as what runs here. Frontier APIs are excluded on purpose:
  quoting their $/Mtok beside a 7B's throughput would be a comparison of two different things.
- **Local-hardware rows are published figures, not measured here.** Only the RTX 3060 row in
  `bench/prices.json` has `measured_here: true`.
- **Hosted prices move.** Every price in `bench/prices.json` carries the URL it came from and
  the date it was read. Re-read them before relying on this.
- **Non-price reasons are not modelled.** Mail staying on the LAN, no per-token metering, and
  no dependency on someone else's uptime are the reasons this box exists. They do not appear
  in a dollar figure.

## Hardware comparison

| Hardware | Price | Price note | Published 7B Q4 decode tok/s | Tok/s per dollar | Price source | Benchmark source |
| --- | --- | --- | --- | --- | --- | --- |
| RTX 3060 12GB (this box, **measured here**) | $300.00 | purchase price paid | 61.9 | 0.2063 | Conrad's purchase, 2026-09-29 | `benchmarks/benchmark-20260930-131153.json` |
| NVIDIA RTX 4090 24GB | $4,674.00 | median of 16 listings on Newegg's category page, $4,395.00-$5,299.99 (discontinued, no current MSRP) | 90.3 | 0.0193 | <https://www.newegg.com/p/pl?N=100007709+601408874> | <https://markaicode.com/benchmarks/llamacpp-llama-31-rtx-4090-throughput-benchmark/> |
| NVIDIA DGX Spark (128GB) | $6,950.00 | current list price | — | — | <https://www.servethehome.com/nvidia-dgx-spark-64gb-launched-and-big-128gb-gb10-price-increases/> | — |

The RTX 3060's 61.9 tok/s above is the single-request benchmark cited in `bench/prices.json`
(`benchmarks/benchmark-20260930-131153.json`, 8192 context), not the sweep's 1-slot row
(58.7 tok/s, 2048 context, 1000-token prompts) — it is kept because the 4090's published
figure is also a single-stream measurement, so the two are like-for-like. The DGX Spark has no
published Q4 decode figure for a 7B model, only Q8_0, so its throughput and tok/s-per-dollar
cells are left empty rather than estimated.

Two systems a reader might expect here could not be sourced and are deliberately absent. As of
2026-10-05: **Groq** has no public price for a Llama-3.1-8B-class model, and the **Mac mini
M4** is discontinued from Apple's own storefront, with third-party listings spanning
$449-$1099 and no defensible single figure. Their absence is a sourcing gap, not a finding
that they are worse or better.
