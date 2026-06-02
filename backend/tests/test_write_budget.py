"""Tests for per-turn write budget state machine."""

from core.agents.security.write_budget import BudgetAction, BudgetState


class TestBudgetState:
    def test_allows_writes_up_to_limit(self):
        b = BudgetState(limit=3)
        assert b.check_write("tool_a") == BudgetAction.ALLOW
        assert b.check_write("tool_b") == BudgetAction.ALLOW
        assert b.check_write("tool_c") == BudgetAction.ALLOW

    def test_first_excess_rejects(self):
        b = BudgetState(limit=2)
        b.check_write("a")
        b.check_write("b")
        assert b.check_write("c") == BudgetAction.REJECT

    def test_second_excess_terminates(self):
        b = BudgetState(limit=1)
        b.check_write("a")
        b.check_write("b")  # REJECT
        assert b.check_write("c") == BudgetAction.TERMINATE

    def test_disabled_budget_always_allows(self):
        b = BudgetState(limit=1, enabled=False)
        for _ in range(100):
            assert b.check_write("tool") == BudgetAction.ALLOW

    def test_zero_limit_always_allows(self):
        b = BudgetState(limit=0, enabled=True)
        for _ in range(100):
            assert b.check_write("tool") == BudgetAction.ALLOW

    def test_remaining_property(self):
        b = BudgetState(limit=5)
        assert b.remaining == 5
        b.check_write("a")
        assert b.remaining == 4
        b.check_write("b")
        b.check_write("c")
        assert b.remaining == 2

    def test_remaining_when_disabled(self):
        b = BudgetState(limit=5, enabled=False)
        assert b.remaining == 999

    def test_remaining_never_negative(self):
        b = BudgetState(limit=1)
        b.check_write("a")
        b.check_write("b")  # REJECT
        b.check_write("c")  # TERMINATE
        assert b.remaining == 0

    def test_escalation_sequence(self):
        b = BudgetState(limit=2)
        results = [b.check_write(f"t{i}") for i in range(5)]
        assert results == [
            BudgetAction.ALLOW,
            BudgetAction.ALLOW,
            BudgetAction.REJECT,
            BudgetAction.TERMINATE,
            BudgetAction.TERMINATE,
        ]
