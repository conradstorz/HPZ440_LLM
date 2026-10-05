import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from bench import load


CHUNK_DELAY_S = 0.02
CHUNKS = 5


class _StubHandler(BaseHTTPRequestHandler):
    """Emits CHUNKS SSE deltas then a final chunk carrying usage and timings."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence the test output
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        assert body["stream"] is True
        assert body["ignore_eos"] is True

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(payload: dict) -> None:
            data = f"data: {json.dumps(payload)}\n\n".encode()
            self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()

        import time

        for i in range(CHUNKS):
            time.sleep(CHUNK_DELAY_S)
            write({"choices": [{"delta": {"content": f"t{i} "}}]})

        write(
            {
                "choices": [{"delta": {}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": CHUNKS,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
                "timings": {"prompt_n": 1000, "prompt_ms": 500.0, "predicted_n": CHUNKS},
            }
        )
        data = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _shares_long_run(a: str, b: str, run: int = 200) -> bool:
    """Does any 200-character window of a appear anywhere in b?"""
    return any(a[i : i + run] in b for i in range(0, len(a) - run, run))


def test_build_prompt_is_distinct_per_seed():
    a = load.build_prompt(0, 1000)
    b = load.build_prompt(1, 1000)
    assert a != b
    assert a[:50] != b[:50]


def test_build_prompt_shares_no_long_run_between_seeds():
    """The property that makes the prefill measurement real.

    A differing opening is not enough. Two prompts sharing a long body let
    llama.cpp serve almost the whole prefill from cache -- measured at 99.9%,
    inflating the reported prefill rate 24x.
    """
    a = load.build_prompt(0, 1000)
    b = load.build_prompt(1, 1000)
    assert not _shares_long_run(a, b)
    assert not _shares_long_run(b, a)


def test_build_prompt_is_deterministic():
    """The same sweep point must be rerunnable and comparable."""
    assert load.build_prompt(7, 1000) == load.build_prompt(7, 1000)


def test_build_prompt_of_different_sizes_shares_no_long_run():
    """A size change must not produce a prefix-extension of the smaller prompt.

    Seeding on the seed alone did exactly that, so re-running a sweep at a new
    --prompt-tokens value on a server that had not restarted was served 62.3% from
    the previous run's cache, rising to 99.9% on a repeat.
    """
    short = load.build_prompt(7, 600)
    long = load.build_prompt(7, 1000)
    assert not _shares_long_run(short, long)
    assert not long.startswith(short[:400])


def test_build_prompt_is_roughly_the_requested_length():
    prompt = load.build_prompt(0, 1000)
    # Sized by the measured 6.55 chars/token, so 1000 tokens is ~6550 characters.
    # The live check that this lands near 1000 real tokens is the server's tokenizer,
    # not this test; this only pins that the calibration is being applied at all.
    assert 6200 < len(prompt) < 6900


def test_one_request_measures_ttft_and_usage(stub_server):
    async def go():
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await load.one_request(
                client, stub_server, "stub-model", "hello", max_tokens=CHUNKS
            )

    sample = asyncio.run(go())
    assert sample.output_tokens == CHUNKS
    assert sample.prompt_tokens == 1000
    assert sample.prompt_ms == pytest.approx(500.0)
    assert sample.cached_tokens == 3
    # First delta arrives after one chunk delay; the whole stream takes CHUNKS of them.
    assert sample.ttft_ms >= CHUNK_DELAY_S * 1000 * 0.5
    assert sample.latency_ms > sample.ttft_ms


def test_run_slot_point_summarizes_all_clients(stub_server):
    out = asyncio.run(
        load.run_slot_point(
            base_url=stub_server,
            model="stub-model",
            slots=2,
            ctx_per_slot=2048,
            requests_per_client=3,
            prompt_tokens=100,
            max_tokens=CHUNKS,
        )
    )
    # 3 requests per client, first discarded as warm-up: 2 clients x 2 = 4 samples.
    assert out["requests"] == 4
    assert out["slots"] == 2
    assert out["output_tokens_total"] == 4 * CHUNKS
    assert out["prefill_valid"] is True
