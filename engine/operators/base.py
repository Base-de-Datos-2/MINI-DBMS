"""Pull-based relational execution contract, without concrete operators."""

from abc import ABC, abstractmethod

from engine.storage.record import Record


class Operator(ABC):
    """A reusable open/next/close execution boundary yielding Record objects.

    Instances start closed. A successful open starts a new run; next consumes
    it; close releases resources. Results in one run share an output schema
    determined by the implementation. An empty Record is still a result;
    only None denotes exhaustion. Operators need not be Python iterators.

    Consumers must close on normal completion, early exit, and exceptions,
    including a failed open, e.g.::

        try:
            operator.open()
            while (record := operator.next()) is not None:
                consume(record)
        finally:
            operator.close()

    ABC enforces the methods only. State checks, execution and cleanup belong
    to future concrete operators and their tests; no TableScan is supplied.
    """

    @abstractmethod
    def open(self) -> None:
        """Initialize a run from its beginning and acquire owned resources.

        Opening an already open (even exhausted) operator raises RuntimeError
        without resetting that run. Opening after close is allowed. A failed
        open must release partially acquired resources and leave it closed.
        Reopening does not promise a snapshot if underlying data has changed.
        """
        raise NotImplementedError

    @abstractmethod
    def next(self) -> Record | None:
        """Return the next row, or None repeatedly after exhaustion.

        Calling before open or after close raises RuntimeError. Do not use
        StopIteration for normal exhaustion. Other execution errors propagate;
        after one, the consumer must close before opening another run.
        Exhaustion does not replace the obligation to call close().
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release resources and leave the operator closed; return None.

        Idempotent, including before open, after a failed open, or after an
        execution failure. Close owned child operators, search/scan generators,
        and temporary resources, even if not fully consumed. Do not close
        borrowed storage/index managers. Cleanup must attempt to release all
        owned resources even if releasing one fails.
        """
        raise NotImplementedError
