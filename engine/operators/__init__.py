"""Physical relational operators, execution resources, and the row contract."""

from engine.operators.base import (
    ExecutionOperator,
    Operator,
    OperatorDescriptor,
    OperatorState,
    OperatorStatistics,
    collect,
    execute,
)
from engine.operators.context import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_MAX_OPEN_HANDLES,
    MINIMUM_BUDGET_BYTES,
    ROW_OVERHEAD_BYTES,
    ExecutionContext,
    HandleLease,
    MemoryReservation,
    ResourceStatistics,
    row_footprint_bytes,
    value_footprint_bytes,
)
from engine.operators.expressions import (
    And,
    BoundExpression,
    ColumnValue,
    Compare,
    ComparisonOperator,
    Expression,
    Literal,
    Not,
    Or,
    column,
    compare_values,
    data_type_of,
    validate_comparable,
)
from engine.operators.filter import Filter
from engine.operators.projection import Projection
from engine.operators.rows import (
    ColumnReference,
    LayoutField,
    RowLayout,
    RowProvenance,
    as_reference,
    validate_identifier,
)
from engine.operators.scan import (
    EqualitySearch,
    IndexScan,
    RangeSearch,
    TableScan,
)

# Only classes and functions belong in __all__: the architecture suite resolves
# every exported symbol back to its defining module, which plain int constants
# cannot answer for. They stay importable from engine.operators.context.
__all__ = [
    "And",
    "BoundExpression",
    "ColumnReference",
    "ColumnValue",
    "Compare",
    "ComparisonOperator",
    "EqualitySearch",
    "ExecutionContext",
    "ExecutionOperator",
    "Expression",
    "Filter",
    "HandleLease",
    "IndexScan",
    "LayoutField",
    "Literal",
    "MemoryReservation",
    "Not",
    "Operator",
    "OperatorDescriptor",
    "OperatorState",
    "OperatorStatistics",
    "Or",
    "Projection",
    "RangeSearch",
    "ResourceStatistics",
    "RowLayout",
    "RowProvenance",
    "TableScan",
    "as_reference",
    "collect",
    "column",
    "compare_values",
    "data_type_of",
    "execute",
    "row_footprint_bytes",
    "validate_comparable",
    "validate_identifier",
    "value_footprint_bytes",
]
