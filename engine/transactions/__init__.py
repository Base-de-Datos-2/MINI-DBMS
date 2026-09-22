"""Stage 8 transaction foundation; data execution integration is pending."""

from .errors import (
    DeadlockVictimError,
    LockTimeoutError,
    SessionBusyError,
    TransactionAbortError,
    TransactionCapacityError,
    TransactionError,
    TransactionProtocolError,
    TransactionUnavailableError,
)
from .manager import TransactionManager
from .locks import (
    LockManager, LockSnapshot, ResourceSnapshot, SchemaResource, WaitSnapshot,
)
from .model import Transaction, TransactionId, TransactionReport, TransactionState
from .resources import (
    AccessPlan,
    LockMode,
    ResourceCatalog,
    SchemaMode,
    StaleAccessPlanError,
    TableFiles,
    TableIntent,
    TableResource,
)
from .session import SessionCoordinator, SqlSession

__all__ = [
    "AccessPlan",
    "DeadlockVictimError",
    "LockMode",
    "LockManager",
    "LockSnapshot",
    "LockTimeoutError",
    "ResourceCatalog",
    "ResourceSnapshot",
    "SchemaMode",
    "SchemaResource",
    "SessionBusyError",
    "SessionCoordinator",
    "SqlSession",
    "StaleAccessPlanError",
    "TableFiles",
    "TableIntent",
    "TableResource",
    "Transaction",
    "TransactionAbortError",
    "TransactionCapacityError",
    "TransactionError",
    "TransactionId",
    "TransactionManager",
    "TransactionProtocolError",
    "TransactionReport",
    "TransactionState",
    "TransactionUnavailableError",
    "WaitSnapshot",
]
