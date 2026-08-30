"""Cost ledger and pricing.

The claim under test is demo step 9: their traffic, what it cost, what it
would have cost. IDEATION section 20 calls it the most persuasive artefact in
the pitch and says it needs no explanation - which only holds if the number
is honest, which is what D7 is about.
"""

import pytest

from controlplane.cost.ledger import BudgetExceeded, CostLedger
from controlplane.cost.pricing import (
    DEFAULT_PRICES,
    PRICES_AS_OF,
    PriceBook,
    UnknownModel,
    Usage,
    estimate_tokens,
)


@pytest.fixture()
def ledger():
    return CostLedger(baseline_model="claude-opus-5")


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------

def test_cost_arithmetic():
    book = PriceBook()
    # opus-5 is $5/1M in, $25/1M out
    cost = book.cost(Usage("claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == pytest.approx(30.0)


def test_cheaper_model_costs_less():
    book = PriceBook()
    usage = lambda m: Usage(m, input_tokens=100_000, output_tokens=10_000)
    assert book.cost(usage("claude-haiku-4-5")) < book.cost(usage("claude-sonnet-5"))
    assert book.cost(usage("claude-sonnet-5")) < book.cost(usage("claude-opus-5"))


def test_cache_reads_are_much_cheaper_than_fresh_input():
    """Why repeated invariant context is the highest-value cheap win."""
    book = PriceBook()
    fresh = book.cost(Usage("claude-opus-5", input_tokens=100_000))
    cached = book.cost(Usage("claude-opus-5", cache_read_tokens=100_000))
    assert cached == pytest.approx(fresh * 0.10)


def test_cache_writes_carry_a_premium():
    book = PriceBook()
    fresh = book.cost(Usage("claude-opus-5", input_tokens=100_000))
    written = book.cost(Usage("claude-opus-5", cache_write_tokens=100_000))
    assert written == pytest.approx(fresh * 1.25)


def test_unknown_model_raises_rather_than_costing_zero():
    """A model priced at zero silently understates the bill - the one
    failure mode that makes the whole report worthless."""
    with pytest.raises(UnknownModel, match="no price"):
        PriceBook().cost(Usage("some-model-we-never-priced", input_tokens=10))


def test_prices_carry_an_as_of_date():
    """A number without a date is a number nobody can check."""
    assert PriceBook().as_of == PRICES_AS_OF
    assert len(DEFAULT_PRICES) >= 5


def test_price_book_is_overridable():
    """A customer runs their own negotiated rates on their own provider mix."""
    book = PriceBook({"house-model": (1.0, 2.0)}, as_of="2026-08-30")
    assert book.cost(Usage("house-model", input_tokens=1_000_000)) == pytest.approx(1.0)
    with pytest.raises(UnknownModel):
        book.cost(Usage("claude-opus-5", input_tokens=1))


def test_estimate_assumes_the_worst_case_output():
    """A refusal based on an optimistic estimate arrives after the money is gone."""
    book = PriceBook()
    assert book.estimate("claude-opus-5", 1000, 4000) > book.estimate("claude-opus-5", 1000, 100)


def test_token_estimate_is_a_sizing_heuristic():
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("") == 1


# --------------------------------------------------------------------------
# Budgets - refusing before dispatch costs zero
# --------------------------------------------------------------------------

def test_request_budget_refuses_before_dispatch():
    """IDEATION 8: check first, dispatch second.

    The original design forwarded upstream and cancelled on failure - but you
    are billed the moment tokens are generated, so that blocks the request
    AND pays for it.
    """
    ledger = CostLedger()
    estimate = ledger.estimate("claude-opus-5", "x" * 40_000, 4000)
    with pytest.raises(BudgetExceeded, match="request budget"):
        ledger.check_budget(team="support", estimate=estimate, request_budget_usd=0.01)
    assert len(ledger) == 0, "a refused request must cost nothing and record nothing"


def test_team_budget_tracks_cumulative_spend():
    ledger = CostLedger(team_budgets={"support": 0.10})
    for i in range(3):
        ledger.record(
            request_id=f"r{i}", team="support", profile="customer-support",
            usage=Usage("claude-opus-5", input_tokens=5_000, output_tokens=1_000),
        )
    with pytest.raises(BudgetExceeded, match="team 'support'"):
        ledger.check_budget(team="support", estimate=0.09)


def test_a_team_without_a_budget_is_unlimited(ledger):
    """No cap configured means no refusal - proven by the absence of a raise.

    Written with an explicit `does not raise` rather than a bare call: a test
    body with no assert reads as one that cannot fail, and a reader should not
    have to work out that `check_budget` raising IS the failure mode.
    """
    ledger.check_budget(team="nobody-set-a-cap", estimate=99.0)  # must not raise
    assert ledger.spend_for_team("nobody-set-a-cap") == 0.0


# --------------------------------------------------------------------------
# D7 - gross, overhead, net. Never one without the others.
# --------------------------------------------------------------------------

def test_report_always_contains_all_three(ledger):
    """If the flattering figure is the only one you can get, it is the one
    that ends up on the slide."""
    ledger.record(
        request_id="r1", team="support", profile="customer-support",
        usage=Usage("claude-haiku-4-5", input_tokens=10_000, output_tokens=1_000),
    )
    d = ledger.savings().as_dict()
    assert {"gross_saving_usd", "our_overhead_usd", "net_saving_usd"} <= set(d)


def test_our_overhead_reduces_the_net(ledger):
    """Consistency sampling and counterfactual probing multiply token spend,
    and a judge who suspects we are hiding it will ask."""
    ledger.record(
        request_id="r1", team="support", profile="customer-support",
        usage=Usage("claude-haiku-4-5", input_tokens=100_000, output_tokens=10_000),
    )
    ledger.record(
        request_id="r1-probe", team="support", profile="customer-support",
        usage=Usage("claude-haiku-4-5", input_tokens=20_000, output_tokens=2_000),
        purpose="overhead",
    )
    report = ledger.savings()
    assert report.overhead_spend > 0
    assert report.net_saving == pytest.approx(report.gross_saving - report.overhead_spend)
    assert report.net_saving < report.gross_saving


def test_overhead_share_is_reported(ledger):
    """IDEATION 15.5: cap evaluation spend as a share of protected spend."""
    ledger.record(
        request_id="r1", team="t", profile="p",
        usage=Usage("claude-opus-5", input_tokens=100_000, output_tokens=10_000),
    )
    ledger.record(
        request_id="r1-probe", team="t", profile="p",
        usage=Usage("claude-opus-5", input_tokens=10_000, output_tokens=1_000),
        purpose="overhead",
    )
    assert 0.05 < ledger.savings().overhead_share < 0.15


def test_overhead_requests_are_not_counted_as_protected_traffic(ledger):
    ledger.record(request_id="a", team="t", profile="p",
                  usage=Usage("claude-opus-5", input_tokens=100))
    ledger.record(request_id="b", team="t", profile="p",
                  usage=Usage("claude-opus-5", input_tokens=100), purpose="overhead")
    report = ledger.savings()
    assert report.requests == 1 and report.overhead_requests == 1


def test_routing_to_a_cheaper_model_shows_as_saving(ledger):
    """The biggest lever (IDEATION 15.1): wrong model for the job."""
    for i in range(10):
        ledger.record(
            request_id=f"r{i}", team="support", profile="customer-support",
            usage=Usage("claude-haiku-4-5", input_tokens=20_000, output_tokens=2_000),
        )
    report = ledger.savings()
    assert report.gross_saving > 0
    assert report.baseline_spend > report.protected_spend
    assert report.baseline_model == "claude-opus-5"


def test_report_string_shows_the_working(ledger):
    ledger.record(request_id="r", team="t", profile="p",
                  usage=Usage("claude-haiku-4-5", input_tokens=10_000, output_tokens=1_000))
    text = str(ledger.savings())
    for fragment in ("baseline", "gross", "overhead", "NET", "prices as of"):
        assert fragment in text


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------

def test_attribution_by_team_and_profile(ledger):
    ledger.record(request_id="a", team="support", profile="customer-support",
                  usage=Usage("claude-opus-5", input_tokens=100_000))
    ledger.record(request_id="b", team="hr", profile="internal-knowledge",
                  usage=Usage("claude-opus-5", input_tokens=10_000))
    by_team = ledger.by_team()
    assert list(by_team)[0] == "support", "biggest spender first"
    assert set(ledger.by_profile()) == {"customer-support", "internal-knowledge"}


# --------------------------------------------------------------------------
# Caching opportunities - the highest-value cheap win
# --------------------------------------------------------------------------

def test_repeated_prefix_surfaces_a_caching_opportunity(ledger):
    """IDEATION 15.2: hash prompt prefixes, notice the same one recurring.

    The fix is one config change for a large discount, and nobody spots it
    because the context grows silently.
    """
    system = "You are a support assistant. " * 40
    for i in range(5):
        ledger.record(
            request_id=f"r{i}", team="support", profile="customer-support",
            usage=Usage("claude-opus-5", input_tokens=5_000, output_tokens=200),
            prompt_prefix=system,
        )
    opportunities = ledger.caching_opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].occurrences == 5
    assert opportunities[0].estimated_saving_usd > 0


def test_varied_prompts_surface_nothing(ledger):
    for i in range(5):
        ledger.record(
            request_id=f"r{i}", team="t", profile="p",
            usage=Usage("claude-opus-5", input_tokens=1_000),
            prompt_prefix=f"a completely different question number {i} " * 20,
        )
    assert ledger.caching_opportunities() == []


def test_ledger_holds_hashes_not_prompts(ledger):
    """Same line as everywhere else: counters and hashes, never content."""
    ledger.record(
        request_id="r", team="t", profile="p",
        usage=Usage("claude-opus-5", input_tokens=1_000),
        prompt_prefix="Refund Priya Sharma on account 50100234567890",
    )
    blob = repr(ledger.entries) + repr(ledger.caching_opportunities(min_occurrences=1))
    assert "Priya" not in blob and "50100234567890" not in blob
