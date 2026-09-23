"""Physical undo and terminal transaction completion under retained locks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from .errors import TransactionUnavailableError
from .locks import LockManager
from .manager import TransactionManager
from .model import TransactionId, TransactionReport, TransactionState
from .resources import LockMode, ResourceCatalog, TableResource
from .runtime import TableRuntime
from .undo import UndoLimits, UndoStore


class CompletionService:
    def __init__(
        self, root: Path, transactions: TransactionManager,
        locks: LockManager, resources: ResourceCatalog,
        runtime: TableRuntime, *, limits: UndoLimits = UndoLimits(),
        quarantine_owner: Callable[[], None] | None = None,
    ) -> None:
        self.transactions = transactions
        self.locks = locks
        self.resources = resources
        self.runtime = runtime
        self.undo = UndoStore(root, limits=limits)
        self._quarantine_owner = quarantine_owner
        self._terminal: dict[TransactionId, TransactionReport] = {}

    def prepare_write(self, transaction_id: TransactionId, table_name: str) -> None:
        """Grant schema S/table X and publish a complete image before action."""
        transaction = self.transactions.current(transaction_id)
        if transaction.state is not TransactionState.ACTIVE:
            raise TransactionUnavailableError("Transaction is not active")
        self.locks.acquire(transaction_id, self.locks.schema_resource, LockMode.S)
        files = self.resources.table_files(table_name)
        resource = TableResource(self.resources.database_identity, files.identity)
        self.locks.acquire(transaction_id, resource, LockMode.X)
        # Recheck mapping after the wait. CREATE uses schema X in the eventual
        # SQL path, so table identity cannot change under the schema grant.
        if self.resources.table_files(table_name) != files:
            raise TransactionUnavailableError("Table resource changed during lock wait")
        if table_name not in transaction.touched_tables:
            self.runtime.flush(files)
            image = self.undo.capture(transaction_id, files)
            self.transactions.record_resources(
                transaction_id,
                held=frozenset({"schema", files.identity}),
                touched=frozenset({table_name}),
                undo=(str(image.descriptor),),
            )

    def commit(self, transaction_id: TransactionId) -> TransactionReport:
        transaction = self.transactions.current(transaction_id)
        if transaction.state is not TransactionState.ACTIVE:
            raise TransactionUnavailableError("Transaction cannot commit from its current state")
        self.transactions.transition(transaction_id, TransactionState.COMMITTING)
        try:
            for image in self.undo.images(transaction_id):
                files = self.resources.table_files(image.table_name)
                self.runtime.validate(files)
                self.runtime.flush(files)
        except BaseException as error:
            report = self.abort(transaction_id)
            error.add_note(
                f"Transaction {transaction_id.value} ended {report.state.value} after commit failure"
            )
            raise
        # This is the success point. Undo and X locks still exist here.
        completed = self.transactions.transition(transaction_id, TransactionState.COMMITTED)
        report = TransactionReport.from_transaction(completed)
        self._terminal[transaction_id] = report
        try:
            self.locks.release_all(report)
        except BaseException as error:
            self._quarantine()
            report = replace(report, warnings=(
                f"Post-commit lock cleanup failed: {type(error).__name__}: {error}",
            ))
            self._terminal[transaction_id] = report
            return report
        warnings = self.undo.discard(transaction_id)
        if warnings:
            report = replace(report, warnings=warnings)
            self._terminal[transaction_id] = report
        return report

    def abort(self, transaction_id: TransactionId) -> TransactionReport:
        cached = self._terminal.get(transaction_id)
        if cached is not None:
            return cached
        transaction = self.transactions.current(transaction_id)
        if transaction.state not in (TransactionState.ACTIVE, TransactionState.COMMITTING):
            raise TransactionUnavailableError("Transaction is already being aborted")
        self.transactions.transition(transaction_id, TransactionState.ABORTING)
        try:
            # Reverse first-write order. Each restore owns only its table's
            # files, so independent committed tables remain untouched.
            for image in reversed(self.undo.images(transaction_id)):
                files = self.resources.table_files(image.table_name)
                self.runtime.close_table(files)
                self.undo.restore(image, files)
                self.runtime.reopen(files)
                self.resources.bump_generation(files.name)
        except BaseException as error:
            # Quarantine before releasing any locks or waking their waiters.
            self._quarantine()
            completed = self.transactions.transition(transaction_id, TransactionState.ABORT_FAILED)
            report = TransactionReport.from_transaction(completed)
            self._terminal[transaction_id] = replace(
                report, warnings=(f"Restore failed: {type(error).__name__}: {error}",)
            )
            return self._terminal[transaction_id]
        completed = self.transactions.transition(transaction_id, TransactionState.ABORTED)
        report = TransactionReport.from_transaction(completed)
        self._terminal[transaction_id] = report
        try:
            self.locks.release_all(report)
        except BaseException as error:
            self._quarantine()
            report = replace(report, warnings=(
                f"Post-abort lock cleanup failed: {type(error).__name__}: {error}",
            ))
            self._terminal[transaction_id] = report
            return report
        warnings = self.undo.discard(transaction_id)
        if warnings:
            report = replace(report, warnings=warnings)
            self._terminal[transaction_id] = report
        return report

    def report(self, transaction_id: TransactionId) -> TransactionReport | None:
        return self._terminal.get(transaction_id)

    def _quarantine(self) -> None:
        if self._quarantine_owner is not None:
            self._quarantine_owner()
        self.locks.quarantine()

    def retry_cleanup(self, transaction_id: TransactionId) -> tuple[str, ...]:
        report = self._terminal.get(transaction_id)
        if report is None:
            raise TransactionUnavailableError("Transaction has not completed")
        if report.state not in (TransactionState.COMMITTED, TransactionState.ABORTED):
            raise TransactionUnavailableError(
                "Failed restoration artifacts require external inspection"
            )
        return self.undo.discard(transaction_id)
