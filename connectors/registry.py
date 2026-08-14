"""One place to obtain connector instances.

Agents ask the registry rather than constructing adapters, so swapping a mock for
a real implementation is a single edit here (architecture principle 5).
"""

from __future__ import annotations

from functools import lru_cache

from connectors.crm import CrmConnector
from connectors.dms import DmsConnector
from connectors.payments import PaymentsConnector
from connectors.project_mgmt import ProjectMgmtConnector
from connectors.ticketing import TicketingConnector


@lru_cache
def crm() -> CrmConnector:
    return CrmConnector()


@lru_cache
def project_mgmt() -> ProjectMgmtConnector:
    return ProjectMgmtConnector()


@lru_cache
def payments() -> PaymentsConnector:
    return PaymentsConnector()


@lru_cache
def dms() -> DmsConnector:
    return DmsConnector()


@lru_cache
def ticketing() -> TicketingConnector:
    return TicketingConnector()


def all_connectors() -> list:
    return [crm(), project_mgmt(), payments(), dms(), ticketing()]


async def health_all() -> list[dict]:
    out = []
    for connector in all_connectors():
        out.append(await connector.health())
    return out
