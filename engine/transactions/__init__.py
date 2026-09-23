"""Stage 8 transaction, locking, undo, and coordinated SQL primitives."""

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
from .completion import CompletionService
from .runtime import TableRuntime
from .undo import FileImage, TableImage, UndoLimits, UndoStore

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
    "CompletionService",
    "TableRuntime",
    "FileImage",
    "TableImage",
    "UndoLimits",
    "UndoStore",
]
