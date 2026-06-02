"""Per-turn write budget enforcement.

A BudgetState is created fresh at the start of each AI turn. It tracks
how many write tools have executed and rejects/terminates on excess.

Budget applies to ALL tools with writes=True in tool_definitions,
excluding context_memory tools.
"""

from dataclasses import dataclass
from enum import Enum


class BudgetAction(Enum):
    ALLOW = "allow"
    REJECT = "reject"
    TERMINATE = "terminate"


@dataclass
class BudgetState:
    limit: int
    enabled: bool = True
    writes_used: int = 0
    rejected_once: bool = False

    def check_write(self, tool_name: str) -> BudgetAction:
        if not self.enabled or self.limit <= 0:
            return BudgetAction.ALLOW
        if self.writes_used < self.limit:
            self.writes_used += 1
            return BudgetAction.ALLOW
        if not self.rejected_once:
            self.rejected_once = True
            return BudgetAction.REJECT
        return BudgetAction.TERMINATE

    @property
    def remaining(self) -> int:
        if not self.enabled:
            return 999
        return max(0, self.limit - self.writes_used)
