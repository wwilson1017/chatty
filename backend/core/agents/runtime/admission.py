"""
Chatty — turn admission.

Two independent guards, kept separate on purpose:

* a per-agent **admission lock + lease set**: every streaming turn (any
  runtime) holds a lease for its lifetime, and an agent-level operation that
  must see no turns in flight (cutover finish/abort, PR 3) closes admission and
  drains the leases;
* a per-conversation **mutex** used by the Hermes runtime for the whole turn,
  including approvals and recovery polling, because Hermes warns against
  concurrent turns on one session.

Both are process-local. The durable guard (an unresolved `external_turns`
row) lives in chat.db and is checked by `runtime.guard_unresolved`.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException


@dataclass
class Lease:
    lease_id: str
    agent_id: str
    conversation_id: str | None
    runtime: str
    started_at: float = field(default_factory=time.time)
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        adm = _agents.get(self.agent_id)
        if adm:
            adm.leases.pop(self.lease_id, None)


@dataclass
class _AgentAdmission:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    leases: dict[str, Lease] = field(default_factory=dict)
    closed: bool = False


_agents: dict[str, _AgentAdmission] = {}
_conversation_locks: dict[str, asyncio.Lock] = {}


def _adm(agent_id: str) -> _AgentAdmission:
    adm = _agents.get(agent_id)
    if adm is None:
        adm = _agents[agent_id] = _AgentAdmission()
    return adm


async def acquire_lease(agent_id: str, conversation_id: str | None, runtime: str) -> Lease:
    adm = _adm(agent_id)
    async with adm.lock:
        if adm.closed:
            raise HTTPException(status_code=409,
                                detail="This agent is switching runtimes; try again in a moment")
        lease = Lease(uuid.uuid4().hex, agent_id, conversation_id, runtime)
        adm.leases[lease.lease_id] = lease
        return lease


def active_leases(agent_id: str) -> list[Lease]:
    return list(_adm(agent_id).leases.values())


async def close_admission(agent_id: str, drain_seconds: float = 30.0) -> bool:
    """Refuse new turns and wait for active leases to drain. Returns False
    (and reopens) when leases remain after the deadline."""
    adm = _adm(agent_id)
    async with adm.lock:
        adm.closed = True
    deadline = time.time() + drain_seconds
    while adm.leases and time.time() < deadline:
        await asyncio.sleep(0.2)
    if adm.leases:
        adm.closed = False
        return False
    return True


def reopen_admission(agent_id: str) -> None:
    _adm(agent_id).closed = False


def conversation_lock(conversation_id: str) -> asyncio.Lock:
    lock = _conversation_locks.get(conversation_id)
    if lock is None:
        lock = _conversation_locks[conversation_id] = asyncio.Lock()
    return lock


async def try_lock_conversation(conversation_id: str) -> asyncio.Lock:
    """Acquire the conversation mutex without waiting; 409 if it is held.

    Safe on a single event-loop thread: `acquire()` on an unlocked Lock
    completes without suspending, so nothing can slip in between the check
    and the acquire.
    """
    lock = conversation_lock(conversation_id)
    if lock.locked():
        raise HTTPException(status_code=409,
                            detail="A turn is already in progress in this conversation")
    await lock.acquire()
    return lock


def _reset_for_tests() -> None:
    _agents.clear()
    _conversation_locks.clear()
