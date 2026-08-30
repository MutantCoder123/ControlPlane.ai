"""Model prices, and the arithmetic that turns tokens into rupees.

Prices are the one thing in this repo that goes stale on someone else's
schedule, so two rules:

1. Every table is DATED. A number without a date is a number nobody can
   check, and "what it would have cost" is the most persuasive artefact in
   the pitch (IDEATION section 20, demo step 9) - it has to survive being
   questioned.
2. The table is OVERRIDABLE. A customer runs their own negotiated rates, on
   their own provider mix. We ship a default so the demo works from a clean
   checkout; we do not pretend our defaults are their bill.

The shipped defaults are Anthropic's published first-party rates. Rates for
other providers are deliberately absent rather than guessed - an invented
price is worse than a missing one, because it looks authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

#: When the shipped table was last checked against published rates.
PRICES_AS_OF = "2026-06-24"

#: USD per 1M tokens. Source: Anthropic published API pricing.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    # model id            (input, output)
    "claude-fable-5":     (10.00, 50.00),
    "claude-opus-5":      (5.00, 25.00),
    "claude-opus-4-8":    (5.00, 25.00),
    "claude-opus-4-7":    (5.00, 25.00),
    "claude-opus-4-6":    (5.00, 25.00),
    "claude-sonnet-5":    (2.00, 10.00),
    "claude-sonnet-4-6":  (3.00, 15.00),
    "claude-haiku-4-5":   (1.00, 5.00),
}

#: Cache writes cost a premium, cache reads a fraction, both relative to the
#: model's input rate. This is why repeated invariant context is the highest
#: value cheap win in the product (IDEATION section 15.2).
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


class UnknownModel(KeyError):
    """A model with no price. We refuse to guess rather than under-report."""


@dataclass(frozen=True)
class Usage:
    """What one request actually consumed."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


class PriceBook:
    """Model prices, with the as-of date attached to every number it produces."""

    def __init__(
        self,
        prices: dict[str, tuple[float, float]] | None = None,
        *,
        as_of: str = PRICES_AS_OF,
    ) -> None:
        self.prices = dict(prices or DEFAULT_PRICES)
        self.as_of = as_of

    def rates(self, model: str) -> tuple[float, float]:
        try:
            return self.prices[model]
        except KeyError:
            raise UnknownModel(
                f"no price for {model!r} as of {self.as_of}. Add it to the price "
                "book rather than letting it cost zero - a model priced at zero "
                "silently understates the bill."
            ) from None

    def cost(self, usage: Usage) -> float:
        """Cost in USD for one request's usage."""
        rate_in, rate_out = self.rates(usage.model)
        per_token_in = rate_in / 1_000_000
        per_token_out = rate_out / 1_000_000
        return (
            usage.input_tokens * per_token_in
            + usage.output_tokens * per_token_out
            + usage.cache_write_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
            + usage.cache_read_tokens * per_token_in * CACHE_READ_MULTIPLIER
        )

    def estimate(self, model: str, input_tokens: int, max_output_tokens: int) -> float:
        """Worst-case cost BEFORE dispatch.

        Deliberately assumes the output runs to `max_output_tokens`. The
        pre-flight gate refuses over-budget requests before spending anything
        (IDEATION section 8), and a refusal based on an optimistic estimate is
        a refusal that arrives after the money is gone.
        """
        return self.cost(
            Usage(model=model, input_tokens=input_tokens, output_tokens=max_output_tokens)
        )

    def cheapest(self, candidates=None) -> str:
        pool = [m for m in (candidates or self.prices) if m in self.prices]
        if not pool:
            raise UnknownModel("no priced models to choose from")
        return min(pool, key=lambda m: sum(self.prices[m]))

    def known_models(self) -> list[str]:
        return sorted(self.prices)


def estimate_tokens(text: str) -> int:
    """Rough token count for budgeting only.

    ~4 characters per token. This is a SIZING heuristic for the pre-flight
    budget check, not an accounting figure - real usage comes back from the
    provider and is what the ledger records. Never bill anyone from this.
    """
    return max(1, len(text) // 4)
