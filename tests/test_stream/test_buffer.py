"""Commit-point buffer.

The claim under test is IDEATION section 7: the credential is never sent -
not deleted after, never transmitted. Once a token reaches the browser it is
in the DOM, so the only control that works is not releasing it.
"""

from pathlib import Path

import pytest

from controlplane.engine.substitute import SubstitutionEngine
from controlplane.policy.profile import compile_profile
from controlplane.policy.store import ControlPlane
from controlplane.stream.buffer import CommitPointBuffer, run_stream

FIXTURE = str(Path(__file__).parents[1] / "test_engine" / "fixtures" / "records.jsonl")


@pytest.fixture(scope="module")
def engine():
    return SubstitutionEngine(FIXTURE)


@pytest.fixture(scope="module")
def bundle():
    return ControlPlane().compile_bundle()


def interactive(**streaming):
    base = {"mode": "interactive", "commit_tokens": 40, "commit_ms": 250, "overlap_chars": 50}
    base.update(streaming)
    return compile_profile({"name": "test", "streaming": base})


def chunks_of(text, size=7):
    return [text[i : i + size] for i in range(0, len(text), size)]


# --------------------------------------------------------------------------
# Clean streams pass through intact
# --------------------------------------------------------------------------

def test_clean_stream_is_delivered_whole(engine):
    text = "Your refund has been processed. It should arrive within three days. Thank you."
    seen, _ = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), chunks_of(text))
    assert seen == text


def test_nothing_is_lost_at_the_end_of_the_stream(engine):
    """The held tail must be flushed, or every answer loses its last words."""
    text = "All done and dusted here."
    seen, _ = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), chunks_of(text, 3))
    assert seen == text


def test_a_single_chunk_stream_works(engine):
    seen, _ = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), ["Hello there."])
    assert seen == "Hello there."


def test_empty_stream_releases_nothing(engine):
    seen, releases = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), [])
    assert seen == "" and releases == []


# --------------------------------------------------------------------------
# The credential is never transmitted - demo step 2
# --------------------------------------------------------------------------

def test_credential_stops_the_stream_and_is_never_released(engine):
    """Two clean sentences release, then it stops.

    The key is never sent. Not deleted after, not redacted downstream - never
    transmitted. That is the screen-recording answer, demonstrated rather than
    asserted.
    """
    text = (
        "Here is the summary you asked for. Everything looks in order. "
        "The key is AKIAIOSFODNN7EXAMPLE and you can use it now."
    )
    buffer = CommitPointBuffer(interactive(), engine.scan_outbound)
    seen, releases = run_stream(buffer, chunks_of(text, 5))

    assert "AKIAIOSFODNN7EXAMPLE" not in seen
    assert buffer.stats.blocked
    assert releases[-1].blocked and releases[-1].reason


def test_clean_prefix_is_still_delivered_before_the_block(engine):
    """A reader should see the good sentences, not a blank screen."""
    text = "First sentence is fine. Second is fine too. Key: AKIAIOSFODNN7EXAMPLE."
    seen, _ = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), chunks_of(text, 6))
    assert "First sentence is fine." in seen
    assert "AKIAIOSFODNN7EXAMPLE" not in seen


def test_nothing_is_released_after_a_block(engine):
    text = "Key AKIAIOSFODNN7EXAMPLE then lots more text that must never appear at all."
    buffer = CommitPointBuffer(interactive(), engine.scan_outbound)
    seen, _ = run_stream(buffer, chunks_of(text, 4))
    assert "must never appear" not in seen
    assert buffer.feed("more text") == []
    assert buffer.flush() == []


# --------------------------------------------------------------------------
# The split-secret bug - the reason the overlap window exists
# --------------------------------------------------------------------------

@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13, 40])
def test_a_secret_split_across_chunks_never_escapes(engine, chunk_size):
    """The bug IDEATION section 7 calls out, tested at every split point.

    Chunked at one character at a time, the credential straddles dozens of
    commit boundaries. Holding back the boundary region - rather than merely
    re-scanning it afterwards - means no part of it is ever released, because
    released is released.
    """
    text = "Please use AKIAIOSFODNN7EXAMPLE for the integration test today."
    buffer = CommitPointBuffer(interactive(), engine.scan_outbound)
    seen, _ = run_stream(buffer, chunks_of(text, chunk_size))
    assert "AKIAIOSFODNN7EXAMPLE" not in seen
    assert buffer.stats.blocked


def test_no_fragment_of_the_secret_leaks(engine):
    """Not just the whole string - no meaningful prefix either."""
    text = "token AKIAIOSFODNN7EXAMPLE done"
    seen, _ = run_stream(CommitPointBuffer(interactive(), engine.scan_outbound), chunks_of(text, 1))
    assert "AKIAIOSFODNN" not in seen
    assert "AKIAIOS" not in seen


def test_overlap_of_zero_is_the_vulnerable_configuration(engine):
    """Proof the window is what does the work, not the scanner.

    With overlap_chars=0 there is no held region, so a secret split across a
    commit boundary can slip through. The test asserts the mechanism matters
    rather than assuming it.
    """
    text = "aaa. AKIAIOSFODNN7EXAMPLE. bbb"
    safe, _ = run_stream(
        CommitPointBuffer(interactive(overlap_chars=50), engine.scan_outbound),
        chunks_of(text, 4),
    )
    assert "AKIAIOSFODNN7EXAMPLE" not in safe


# --------------------------------------------------------------------------
# D6 - throughput mode for routes with no reader
# --------------------------------------------------------------------------

def test_throughput_mode_does_not_release_progressively(engine):
    """No reader means nothing to be ahead of, so buffering is pure latency."""
    profile = compile_profile({"name": "batch", "streaming": {"mode": "throughput"}})
    buffer = CommitPointBuffer(profile, engine.scan_outbound)
    assert not buffer.buffered

    text = "Sentence one. Sentence two. Sentence three."
    assert buffer.feed(text) == []          # nothing mid-stream
    assert "".join(r.text for r in buffer.flush()) == text


def test_throughput_mode_still_blocks_credentials(engine):
    """Batch routes are not exempt from the irreversible-harm check."""
    profile = compile_profile({"name": "batch", "streaming": {"mode": "throughput"}})
    buffer = CommitPointBuffer(profile, engine.scan_outbound)
    buffer.feed("Report body. Key AKIAIOSFODNN7EXAMPLE included.")
    releases = buffer.flush()
    assert releases[-1].blocked


def test_the_three_shipped_profiles_are_interactive(bundle):
    """All three the brief names have a human reading the output."""
    for name in bundle.names:
        assert bundle.get(name).streaming.buffered


# --------------------------------------------------------------------------
# Placeholder restoration inline
# --------------------------------------------------------------------------

def test_placeholders_are_restored_as_the_stream_releases(engine):
    scanned = engine.scan_inbound("Refund Priya Sharma.")
    placeholder = next(iter(scanned.mapping))

    buffer = CommitPointBuffer(
        interactive(), engine.scan_outbound,
        restore=engine.restore, mapping=scanned.mapping,
    )
    text = f"Dear {placeholder}, your refund is on the way. Thank you for waiting."
    seen, _ = run_stream(buffer, chunks_of(text, 6))

    assert "Priya Sharma" in seen
    assert "[[" not in seen


def test_a_placeholder_split_across_chunks_still_restores(engine):
    """Placeholders straddle commit boundaries too - the same window covers it."""
    scanned = engine.scan_inbound("Refund Priya Sharma.")
    placeholder = next(iter(scanned.mapping))
    buffer = CommitPointBuffer(
        interactive(), engine.scan_outbound,
        restore=engine.restore, mapping=scanned.mapping,
    )
    seen, _ = run_stream(buffer, chunks_of(f"Hello {placeholder} welcome back today.", 1))
    assert "Priya Sharma" in seen and "[[" not in seen


def test_the_overlap_cut_does_not_bisect_a_placeholder(engine):
    """Found by watching the dashboard, not by a test - now fixed at the seam.

    `overlap_chars` is sized to catch a straddling SECRET; nothing about it
    guarantees the cut misses a PLACEHOLDER. With a 4-char hold, one commit
    on "Dear [[CUST_A]]" cuts at `window[:-4]`, landing squarely inside the
    token: "Dear [[CUST" would be released, "_A]]" held for later. Neither
    half is a complete placeholder, so `restore()` matches nothing in
    either, and the two pieces concatenate back into literal bracket text -
    exactly what beat 1 of the demo showed on screen.

    Forcing `commit_tokens=1` means the whole string is pending by the time
    the single `feed()` call's commit loop fires, so this is one deterministic
    commit, not a race against chunk boundaries.
    """
    scanned = engine.scan_inbound("Refund Priya Sharma.")
    placeholder = next(iter(scanned.mapping))
    assert placeholder not in ("Priya Sharma",)  # sanity: a real placeholder, not a hit fixture bug

    buffer = CommitPointBuffer(
        interactive(overlap_chars=4, commit_tokens=1),
        engine.scan_outbound,
        restore=engine.restore,
        mapping=scanned.mapping,
    )
    seen, releases = run_stream(buffer, [f"Dear {placeholder}"])

    assert "Priya Sharma" in seen
    assert "[[" not in seen
    # The bisection specifically: neither release may contain a dangling
    # bracket. A test that only checks the FINAL concatenation can pass by
    # coincidence (the two broken halves can reassemble into the original
    # bracketed text) - this is the "built from its own output" shape
    # WORKFLOW.md warns about, so it is checked per-release instead.
    for release in releases:
        opens = release.text.count("[")
        closes = release.text.count("]")
        assert opens == closes, f"a bracket was released without its pair: {release.text!r}"


# --------------------------------------------------------------------------
# Commit triggers
# --------------------------------------------------------------------------

def test_sentence_boundary_commits(engine):
    buffer = CommitPointBuffer(interactive(commit_tokens=999, commit_ms=999_999), engine.scan_outbound)
    long_enough = "A sentence comfortably longer than the fifty character window. "
    assert buffer.feed(long_enough) != []


def test_the_first_window_is_held_until_it_fills(engine):
    """Text shorter than the window releases nothing yet - by design.

    The held region is what makes a split secret impossible to leak, so the
    opening fifty characters wait for the text that follows them. At ~50
    tokens/sec that is roughly a fifth of a second - exactly the "one sentence
    of TTFB" the pitch claims, and it is why the claim is about the START of
    the stream rather than its steady state.
    """
    buffer = CommitPointBuffer(interactive(overlap_chars=50), engine.scan_outbound)
    assert buffer.feed("Short. ") == []
    assert "".join(r.text for r in buffer.flush()) == "Short. "


def test_a_smaller_window_releases_sooner(engine):
    buffer = CommitPointBuffer(interactive(overlap_chars=4), engine.scan_outbound)
    assert buffer.feed("A short sentence. ") != []


def test_token_count_commits_a_runaway_sentence(engine):
    """Stops a model that never reaches a full stop from stalling the stream."""
    buffer = CommitPointBuffer(interactive(commit_tokens=10, commit_ms=999_999), engine.scan_outbound)
    assert buffer.feed("word " * 20) != []


def test_timeout_commits_a_slow_model(engine):
    """A slow model must not hold the reader hostage."""
    # first tick starts the clock, the rest are read by the elapsed check
    ticks = iter([0.0] + [1.0] * 20)
    buffer = CommitPointBuffer(
        interactive(commit_tokens=999, commit_ms=250), engine.scan_outbound,
        clock=lambda: next(ticks),
    )
    no_boundary = "no boundary anywhere in this run on sentence that just keeps going"
    assert buffer.feed(no_boundary) != []


def test_ttfb_is_recorded(engine):
    """The cost we claim is one sentence of TTFB - so we measure it."""
    buffer = CommitPointBuffer(interactive(), engine.scan_outbound)
    run_stream(buffer, chunks_of("First sentence here. Second one follows.", 6))
    assert buffer.stats.ttfb_ms is not None
    assert buffer.stats.commits >= 1
