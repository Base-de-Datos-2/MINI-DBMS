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
    resource_label,
)
from .model import (
    QueryIoMetrics,
    Transaction,
    TransactionId,
    TransactionMetrics,
    TransactionReport,
    TransactionState,
    UndoIoMetrics,
)
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
from .gate import MetadataGate
from .observability import (
    TraceSnapshot, TransactionEvent, TransactionObservability,
)

__all__ = [
    "AccessPlan",
    "DeadlockVictimError",
    "LockMode",
    "LockManager",
    "LockSnapshot",
    "LockTimeoutError",
    "MetadataGate",
    "QueryIoMetrics",
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
    "TransactionMetrics",
    "TransactionObservability",
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
    "UndoIoMetrics",
    "TraceSnapshot",
    "TransactionEvent",
    "resource_label",
]
