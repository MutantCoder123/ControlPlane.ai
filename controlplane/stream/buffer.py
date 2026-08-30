"""Commit-point buffer - the answer to the screen-recording problem.

IDEATION section 7. Tokens from the model are not passed straight through.
They accumulate until a commit point, are scanned, and only then released.

WHY THE DELAY IS INVISIBLE
--------------------------
    A person reads ~4 words/sec. A model emits ~50. You pause once, for about
    a fifth of a second, at the very start. After that the buffer is
    permanently ahead of the reader's eye. Cost: one sentence of TTFB.
    Steady-state perceived latency: zero.
    *** We are not racing the model, we are racing the reader. ***

And it is the answer to TOCTOU: once a token reaches the browser it is in the
DOM and in the stream. A kill switch after the fact is theatre. The only
control that works is not releasing it in the first place.

D6 - THIS ARGUMENT ONLY HOLDS WHERE THERE IS A READER
-----------------------------------------------------
For document batch processing, agentic workflows and embeddings nothing
renders to a human, so buffering is latency with no cover story. Mode comes
from the compiled profile (`streaming.mode`), so a batch route scans in
throughput mode instead. Volunteering that is what stops the pitch line from
sounding like a slogan.

THE SPLIT-SECRET BUG, AND WHY WE FIXED IT DIFFERENTLY
-----------------------------------------------------
Section 7 names the bug: a secret split across two commits matches neither
half and escapes silently. Its proposed fix is a ~50-character overlap window
when scanning.

Scanning with an overlap detects the straddle - but by then the first half has
already been released, and released is released. So we invert it: the last
`overlap_chars` of every commit are HELD BACK rather than re-scanned later.
The boundary region is never released until it has been scanned as one
contiguous piece with the text that follows it.

Same window, one commit later, and airtight instead of merely observant. The
cost is that the tail of the stream lags by fifty characters - about eight
words, well inside the reader's own lag - and `flush()` releases it at the end.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from controlplane.policy.profile import Profile

#: Sentence boundaries: the natural, invisible commit point.
_BOUNDARY_RE = re.compile(r"[.!?]['\")\]]?\s|\n\n|\n")


@dataclass(frozen=True)
class Release:
    """Text cleared for the reader, or the moment we stopped."""

    text: str
    kind: str = "text"          # "text" | "blocked"
    reason: str | None = None
    #: Which commit rule fired: "boundary" | "tokens" | "timeout" | "flush".
    #: Observability only - nothing branches on it. It exists because "we
    #: buffer to a commit point" is a claim a reader should be able to watch
    #: happening rather than take on trust.
    trigger: str | None = None

    @property
    def blocked(self) -> bool:
        return self.kind == "blocked"


@dataclass
class BufferStats:
    commits: int = 0
    released_chars: int = 0
    held_chars: int = 0
    ttfb_ms: float | None = None
    blocked: bool = False
    boundary_catches: int = 0   # secrets caught straddling a commit


class CommitPointBuffer:
    """Accumulate, scan, release. Never the other way round.

    `scanner` is any callable taking text and returning something with
    `.findings` and `.blocked` - the substitution engine's `scan_outbound`
    fits directly. `restore` is optional and runs on released text only.
    """

    def __init__(
        self,
        profile: Profile,
        scanner,
        *,
        restore=None,
        mapping: dict[str, str] | None = None,
        clock=time.monotonic,
    ) -> None:
        self.profile = profile
        self.scanner = scanner
        self.restore = restore
        self.mapping = mapping or {}
        self._clock = clock

        self._pending = ""
        self._held = ""            # the boundary region, not yet safe to release
        self._started: float | None = None
        self._stopped = False
        self.stats = BufferStats()

    # -- public ------------------------------------------------------------

    @property
    def buffered(self) -> bool:
        """False for batch and agentic routes - see D6 in the module docstring."""
        return self.profile.streaming.buffered

    @property
    def pending_chars(self) -> int:
        """Accumulated, not yet scanned. Observability only."""
        return len(self._pending)

    @property
    def held_chars(self) -> int:
        """The overlap window: scanned, deliberately not yet released.

        This is the number that makes D5 visible. A secret straddling a
        commit point is only caught because the tail of the last window is
        re-scanned with the head of the next, and holding it back is the
        cost of that. A reader should be able to see the cost, not just be
        told it is small.
        """
        return len(self._held)

    def feed(self, chunk: str) -> list[Release]:
        if self._stopped or not chunk:
            return []
        if self._started is None:
            self._started = self._clock()

        self._pending += chunk

        if not self.buffered:
            # Throughput mode: no reader, so there is nothing to be ahead of.
            # Everything is scanned once at flush.
            return []

        releases: list[Release] = []
        while (trigger := self._should_commit()) is not None:
            release = self._commit(final=False, trigger=trigger)
            if release is not None:
                releases.append(release)
            if self._stopped:
                break
        return releases

    def flush(self) -> list[Release]:
        """End of stream. Scan and release whatever is left, held tail included."""
        if self._stopped:
            return []
        releases = []
        release = self._commit(final=True, trigger="flush")
        if release is not None:
            releases.append(release)
        return releases

    # -- internals ---------------------------------------------------------

    def _should_commit(self) -> str | None:
        """Which rule fires, or None. Returns the reason so it can be shown."""
        streaming = self.profile.streaming
        if _BOUNDARY_RE.search(self._pending):
            return "boundary"
        if _approx_tokens(self._pending) >= streaming.commit_tokens:
            return "tokens"
        if self._started is not None:
            elapsed_ms = (self._clock() - self._started) * 1000
            if elapsed_ms >= streaming.commit_ms and self._pending:
                return "timeout"
        return None

    def _commit(self, *, final: bool, trigger: str | None = None) -> Release | None:
        """Scan held+pending as one piece, release all but the new tail."""
        if not self._pending and not self._held:
            return None

        window = self._held + self._pending
        result = self.scanner(window)

        if getattr(result, "blocked", False):
            # The credential is never sent. Not deleted after, not redacted
            # downstream - never transmitted. That is demo step 2, and the
            # difference between a control and a gesture.
            self._stopped = True
            self.stats.blocked = True
            self._pending = ""
            self._held = ""
            return Release(
                text="",
                kind="blocked",
                reason=getattr(result, "block_reason", None) or "outbound scan blocked",
                trigger=trigger,
            )

        overlap = 0 if final else self.profile.streaming.overlap_chars
        safe_text = window[: len(window) - overlap] if overlap else window
        new_held = window[len(safe_text):]

        if len(new_held) > len(self._held) and self._held and safe_text.startswith(self._held):
            pass  # nothing to do; bookkeeping only

        self._held = new_held
        self._pending = ""
        self.stats.commits += 1
        self.stats.held_chars = len(self._held)

        if self._started is not None and self.stats.ttfb_ms is None and safe_text:
            self.stats.ttfb_ms = (self._clock() - self._started) * 1000
        self._started = self._clock()

        if not safe_text:
            return None

        out = safe_text
        if self.restore is not None and self.mapping:
            out = self.restore(out, self.mapping).text

        self.stats.released_chars += len(out)
        return Release(text=out, trigger=trigger)


def _approx_tokens(text: str) -> int:
    """Whitespace tokens. Close enough for a commit trigger, and free."""
    return len(text.split())


def run_stream(buffer: CommitPointBuffer, chunks) -> tuple[str, list[Release]]:
    """Drive a whole stream and return what the reader actually saw."""
    releases: list[Release] = []
    for chunk in chunks:
        releases.extend(buffer.feed(chunk))
        if buffer.stats.blocked:
            break
    else:
        releases.extend(buffer.flush())
    return "".join(r.text for r in releases), releases
