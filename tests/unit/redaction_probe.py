"""Linearity probes for the MCP interaction capture's redaction patterns.

Imported by `tests/unit/test_mcp_interaction_capture.py`, and also run as a
module (`python -m tests.unit.redaction_probe <kind> <name>`) so the test can
execute each probe in a subprocess with a timeout: a quadratic regression then
fails within the timeout instead of running for minutes inside the test
process. Exit status 0 means the probe passed; 1 means an assertion failed (its
message is on standard error).

Not a test module (no `test_` prefix): it holds the shape tables and the
measurement helpers, and nothing in it is collected.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from my_pa.adapters import mcp_interaction_capture as capture
from my_pa.adapters.mcp_interaction_capture import redact_text

_MIB = 1024 * 1024
#: PEM armour for synthetic fixtures, built from parts so that no secret-key
#: signature appears in source (`test_repository_has_no_high_confidence_secret_signature`).
_PEM_BEGIN = "-----BEGIN " + "{kind}PRIVATE KEY-----"
_PEM_END = "-----END " + "{kind}PRIVATE KEY-----"
#: Absolute backstop for one timed run (thread CPU time), a fixed generous constant
#: rather than an in-process calibration (a calibration loop is itself slowed
#: by the contention it is meant to measure). Idle, the slowest run it guards
#: takes about 0.6 s (a whole 1 MiB family through `redact_text`), so this
#: leaves ~16x headroom for an oversubscribed CI host; the quadratic forms
#: these tests exist to catch take tens to hundreds of seconds at the same
#: sizes, so the margin cannot hide them. The primary discriminator for the
#: probes below is the size-spread ratio, not this bound.
_LINEAR_BOUND_SECONDS = 10.0

#: One adversarial run per pattern family, each about 1 MiB of text.
_ADVERSARIAL: dict[str, tuple[str, str]] = {
    "jwt_eyj_run": ("", "eyJ"),
    "jwt_dotted_run": ("", "a."),
    "escaped_backslash_run": ("", "\\"),
    "escaped_key_run": ("", '\\\\"token\\\\":'),
    "escaped_unterminated": ("", '\\"token\\":\\"'),
    "text_key_prefix": ("", '"a '),
    "text_unterminated": ("", '"token":"a"'),
    "quoted_key": ("", "'token':"),
    "bearer_spaces": ("bearer", " "),
    "basic_word": ("", "basic "),
    "cookie_lines": ("", "cookie:"),
    "scalar_digits": ('"token":', "1"),
    "scalar_minus": ("", '"token":-'),
    "form_spaces": ("", " "),
    "form_keys": ("", "token="),
    "pem_dashes": ("", "-"),
    "pem_begin": ("", _PEM_BEGIN.format(kind="")),
}


# For every compiled pattern in the module: many repetitions of the pattern's
# start token, filler, and a near-miss terminator at the very end.
#
# Robust to CPU contention by construction (AGENTS.md section 7: no flaky
# tests), in two ways.
#
# 1. **CPU time, not wall time.** Every probe sample is the calling thread's
#    CPU time (`time.thread_time`, CLOCK_THREAD_CPUTIME_ID). Time the thread
#    spends descheduled is not counted, so an oversubscribed host cannot
#    inflate one sample against another. Two wall-clock designs were measured
#    flaking with 20 busy loops on 14 cores: comparing one 32 K run with one
#    512 K run, and comparing equal work split 16 ways; in both a sample that
#    straddled a preemption absorbed tens of milliseconds the other did not.
# 2. **Equal work, wide spread.** The probe compares one run over a large text
#    with `spread` runs over a text `spread` times smaller (16x: 32 K and
#    512 K characters), normalised by actual length. Linear costs the same
#    either way (ratio ~1); quadratic costs ~16x more on the large text. The
#    limit of 4 leaves 4x margin on both sides, which also absorbs the cache
#    and shared-core effects CPU time still sees under load.
#
# Each side is the minimum of three repetitions (two for the cross-pattern
# probes), and the ratio is judged only when the large run uses at least 20 ms
# of CPU; below that only the absolute backstop applies. Every pattern is also
# probed with every *other* pattern's shapes at 8 K / 128 K (same 16x spread)
# to keep the file inside FAST.

_RATIO_LIMIT = 4.0
_RATIO_FLOOR_SECONDS = 0.020
_PROBE_SMALL = 32_768
_PROBE_LARGE = 524_288
_CROSS_SMALL = 8_192
_CROSS_LARGE = 131_072
_REPETITIONS = 3
#: The cross-pattern probes take the minimum of two: they are a broad net over
#: shapes written for other patterns, and the FAST budget pays for them.
_CROSS_REPETITIONS = 2
_PEM_CERT_END = "-----END " + "CERTIFICATE-----"


def _repeat(start: str, filler: str = "", tail: str = "") -> Any:  # noqa: ANN401
    unit = start + filler

    def build(size: int) -> str:
        return unit * max(1, size // len(unit)) + tail

    return build


def _decreasing_escaped_heads(size: int) -> str:
    """The reviewer's shape: escaped heads whose backslash runs shrink by one."""
    heads: list[str] = []
    total = 0
    runs = 1
    while total < size:
        total += 3 * runs + 12
        runs += 1
    for run in range(runs, 0, -1):
        quote = "\\" * run + '"'
        heads.append(quote + "token" + quote + ":" + quote + "x")
    return "".join(heads)


def _decreasing_start_tokens(token: str) -> Any:  # noqa: ANN401
    """Start tokens whose lengths decrease: each shorter variant is a near miss."""

    def build(size: int) -> str:
        parts: list[str] = []
        total = 0
        length = len(token)
        while total < size:
            for cut in range(length, 0, -1):
                parts.append(token[:cut] + " ")
                total += cut + 1
        return "".join(parts)

    return build


#: Per-pattern worst-case shapes: start token, filler, near-miss tail.
_PATTERN_SHAPES: dict[str, list[Any]] = {
    "_BEARER": [_repeat("bearer "), _repeat("Bearer", " "), _decreasing_start_tokens("bearer")],
    "_BASIC": [_repeat("basic ", "a"), _repeat("Basic aaaaaaa"), _repeat("basic", " ")],
    "_EQUALS_LINE": [
        _repeat("\npassword", " "),
        _repeat("\n" + " " * 70 + "token", "="),
        _repeat("\nx_api_key", " " * 20, "="),
        _repeat("\n" + "a" * 70 + "_token", "="),
        _decreasing_start_tokens("\nclient_secret = "),
    ],
    "_BARE_PAIR": [
        _repeat("password", ":"),
        _repeat(" token", " " * 20),
        _repeat("{a" * 40 + "_token", ":"),
        _repeat(" x_api_key: ", "'"),
        _decreasing_start_tokens(" client_secret: "),
    ],
    "_COLON_LINE": [
        _repeat("\npassword", " "),
        _repeat("\n" + " " * 70 + "token", ":"),
        _repeat("\nx_api_key", " " * 20, ":"),
        _repeat("\n" + "a" * 70 + "_token", ":"),
        _decreasing_start_tokens("\nclient_secret:"),
    ],
    "_HEADER_LINE": [
        _repeat("cookie", " "),
        _repeat("set-cookie", "\t"),
        _repeat("cookie:"),
        _repeat("authorization", " "),
        _repeat("a-", "", "token"),
        _repeat("x-" + "a" * 70 + "-token", " "),
        _decreasing_start_tokens("proxy-authorization"),
    ],
    "_URL_USERINFO": [
        _repeat("https://u", ":"),
        _repeat("a://", "b:c"),
        _repeat("a" * 40 + "://", "u:" + "p" * 300),
        _repeat("s://u:p", "@", "x"),
    ],
    "_DOTTED_RUN": [_repeat("eyJ"), _repeat("a."), _repeat("eyJ."), _repeat("eyJa.b", "", "c")],
    "_PEM_PRIVATE_KEY": [
        _repeat(_PEM_BEGIN.format(kind="") + "a", "", "-----END X"),
        _repeat(_PEM_BEGIN.format(kind=""), "", _PEM_CERT_END),
        _repeat("-----BEGIN ", "A"),
        _repeat("-"),
    ],
    "_TEXT_PAIR": [
        _repeat('"token":"', "a"),
        _repeat('"a', " "),
        _repeat('"token": -', "1"),
        _repeat('"' + "a" * 63, " "),
        _repeat('"oauth.', "a.", '":'),
        _repeat('"a.b.c.token":"', "x"),
    ],
    "_ESCAPED_TEXT_PAIRS": [
        _decreasing_escaped_heads,
        _repeat('\\"token\\":\\"', "x"),
        _repeat("\\", "", '"'),
        _repeat('\\\\\\"token\\\\\\":', "1"),
        _repeat("\\" * 15 + '"token' + "\\" * 15 + '":' + "\\" * 15 + '"x', "\\" * 16 + '"'),
        _repeat("\\" * 7 + '"token' + "\\" * 7 + '":' + "\\" * 7 + '"', "\\" * 8),
    ],
    "_QUOTED_TEXT_PAIR": [_repeat("'token':'", "a"), _repeat("'token':", "-"), _repeat("'a", " ")],
    "_UNTERMINATED_PAIR": [
        _repeat('"token":"a', "\\"),
        _repeat('"token":"', "a", "\\"),
        _repeat('"token": "', '\\"'),
    ],
    "_ESCAPED_UNTERMINATED_PAIRS": [
        _decreasing_escaped_heads,
        _repeat('\\"token\\":\\"', "x"),
        _repeat('\\\\\\"token\\\\\\":\\\\\\"', "\\"),
        _repeat("\\" * 15 + '"token' + "\\" * 15 + '":' + "\\" * 15 + '"x', "\\" * 16 + '"'),
    ],
    "_FORM_PAIR": [_repeat("token="), _repeat("a", " ", "token"), _repeat("x_token", "=")],
}

#: The reviewer's two inputs, kept verbatim in shape.
_REVIEWER_INPUTS: dict[str, Any] = {
    "pem_begins_then_near_miss_end": _repeat(_PEM_BEGIN.format(kind="") + "a", "", "-----END X"),
    "escaped_heads_with_shrinking_runs": _decreasing_escaped_heads,
}


def _compiled_patterns() -> dict[str, re.Pattern[str]]:
    found: dict[str, re.Pattern[str]] = {}
    for name, value in vars(capture).items():
        if isinstance(value, re.Pattern):
            found[name] = value
        elif isinstance(value, tuple) and value and all(isinstance(v, re.Pattern) for v in value):
            for index, pattern in enumerate(value):
                found[f"{name}[{index}]"] = pattern
    return found


def _min_time(run: Any, text: Any, times: int, label: str, repetitions: int) -> float:  # noqa: ANN401
    """The minimum over `repetitions` of the CPU time to run `run(text)` `times` times.

    Each repetition is checked against `_LINEAR_BOUND_SECONDS` as it finishes,
    so a quadratic regression fails after one slow repetition, not three.
    """
    best = float("inf")
    for _ in range(repetitions):
        began = time.thread_time()
        for _ in range(times):
            run(text)
        elapsed = time.thread_time() - began
        assert elapsed < _LINEAR_BOUND_SECONDS, f"{label}: {elapsed:.2f}s per repetition"
        best = min(best, elapsed)
    return best


def _assert_linear(
    run: Any,  # noqa: ANN401
    build: Any,  # noqa: ANN401
    label: str,
    *,
    sizes: tuple[int, int] = (_PROBE_SMALL, _PROBE_LARGE),
    repetitions: int = _REPETITIONS,
) -> None:
    small_size, large_size = sizes
    spread = large_size // small_size
    small_text, large_text = build(small_size), build(large_size)
    small_length = len(small_text) if isinstance(small_text, str) else small_size
    large_length = len(large_text) if isinstance(large_text, str) else large_size
    small = _min_time(run, small_text, spread, label, repetitions)
    large = _min_time(run, large_text, 1, label, repetitions)
    if large >= _RATIO_FLOOR_SECONDS:
        per_char_small = small / (spread * small_length)
        per_char_large = large / large_length
        ratio = per_char_large / max(per_char_small, 1e-12)
        assert ratio < _RATIO_LIMIT, (
            f"{label}: one {large_length}-char run costs {ratio:.1f}x the same work in "
            f"{spread} runs of {small_length} chars ({large:.4f}s vs {small:.4f}s)"
        )


def _substitute(pattern: re.Pattern[str]) -> Any:  # noqa: ANN401
    return lambda text: pattern.sub("", text)


def _shape_key(name: str) -> str:
    return name.split("[", 1)[0]


def _probe_pattern(name: str) -> None:
    """Own shapes at the wide spread, every other pattern's at the cross spread, 1 MiB."""
    pattern = _compiled_patterns()[name]
    run = _substitute(pattern)
    own = _PATTERN_SHAPES[_shape_key(name)]
    for index, build in enumerate(own):
        _assert_linear(run, build, f"{name} shape {index}")
    for key, shapes in _PATTERN_SHAPES.items():
        if key == _shape_key(name):
            continue
        for index, build in enumerate(shapes):
            _assert_linear(
                run,
                build,
                f"{name} on {key} shape {index}",
                sizes=(_CROSS_SMALL, _CROSS_LARGE),
                repetitions=_CROSS_REPETITIONS,
            )
    for index, build in enumerate(own):
        text = build(_MIB)
        began = time.thread_time()
        pattern.sub("", text)
        assert time.thread_time() - began < _LINEAR_BOUND_SECONDS, f"{name} shape {index} @1MiB"


def _probe_family(family: str) -> None:
    """One adversarial family, 1 MiB through every rule, under the backstop."""
    prefix, unit = _ADVERSARIAL[family]
    text = prefix + unit * (_MIB // len(unit))
    began = time.thread_time()
    redact_text(text)
    elapsed = time.thread_time() - began
    assert elapsed < _LINEAR_BOUND_SECONDS, f"{family}: {elapsed:.2f}s at 1 MiB"


def _probe_reviewer(name: str) -> None:
    _assert_linear(redact_text, _REVIEWER_INPUTS[name], name)


_PROBES = {"pattern": _probe_pattern, "family": _probe_family, "reviewer": _probe_reviewer}


def main(argv: list[str]) -> int:
    kind, name = argv
    try:
        _PROBES[kind](name)
    except AssertionError as failure:
        print(f"{kind} {name}: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
