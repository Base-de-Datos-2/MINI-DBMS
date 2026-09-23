"""Bounded physical before-images for ordinary in-process transaction undo."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Semaphore

from .errors import TransactionCapacityError, TransactionUnavailableError
from .model import TransactionId
from .resources import TableFiles


UNDO_DIRECTORY = ".minidb_undo"
UNCLEAN_MARKER = ".minidb_unclean"


@dataclass(frozen=True, slots=True)
class UndoLimits:
    per_transaction_bytes: int = 1 << 30
    total_bytes: int = 2 << 30
    chunk_bytes: int = 1 << 20
    concurrent_captures: int = 2
    free_reserve_bytes: int = 64 << 20

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in (
            self.per_transaction_bytes, self.total_bytes, self.chunk_bytes,
            self.concurrent_captures,
        )) or type(self.free_reserve_bytes) is not int or self.free_reserve_bytes < 0:
            raise ValueError("Undo limits must be positive integers (reserve may be zero)")
        if self.chunk_bytes > 1 << 20 or self.concurrent_captures > 2:
            raise ValueError("Undo capture exceeds the bounded chunk/handle policy")


@dataclass(frozen=True, slots=True)
class FileImage:
    path: Path
    image: Path
    length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TableImage:
    transaction_id: TransactionId
    table_name: str
    table_identity: str
    files: tuple[FileImage, ...]
    descriptor: Path
    prior_replacements: tuple[Path, ...] = ()


def _replacement_candidates(path: Path) -> tuple[Path, ...]:
    pattern = re.compile(rf"^\.{re.escape(path.name)}\.[0-9a-f]{{32}}\.replacement$")
    candidates = []
    for candidate in path.parent.iterdir():
        if not pattern.fullmatch(candidate.name):
            continue
        if candidate.is_symlink():
            raise TransactionUnavailableError(
                f"Unexpected symbolic replacement path: {candidate}"
            )
        if candidate.is_file():
            candidates.append(candidate)
    return tuple(sorted(candidates))


class UndoStore:
    """Owns images, quotas and the persistent unresolved-artifact marker.

    A fresh owner refuses to open if a marker or orphan data exists. This is
    intentionally detection, not crash recovery.
    """

    def __init__(self, root: Path, *, limits: UndoLimits = UndoLimits()) -> None:
        self.root = Path(root).resolve()
        self.directory = self.root / UNDO_DIRECTORY
        self.marker = self.root / UNCLEAN_MARKER
        self.limits = limits
        self.require_clean(self.root)
        self._mutex = Lock()
        self._capture_slots = Semaphore(limits.concurrent_captures)
        self._images: dict[TransactionId, dict[str, TableImage]] = {}
        self._reserved: dict[TransactionId, int] = {}
        self._pending: dict[TransactionId, int] = {}
        self._debt: set[TransactionId] = set()
        self._cleaning: set[TransactionId] = set()

    @staticmethod
    def require_clean(root: Path) -> None:
        root = Path(root).resolve()
        directory = root / UNDO_DIRECTORY
        if (root / UNCLEAN_MARKER).exists() or (
            directory.exists() and any(directory.iterdir())
        ):
            raise TransactionUnavailableError(
                "Unresolved transaction undo artifacts require external inspection"
            )

    def images(self, transaction_id: TransactionId) -> tuple[TableImage, ...]:
        with self._mutex:
            return tuple(self._images.get(transaction_id, {}).values())

    def _mark_unclean(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.marker.open("xb") as handle:
            handle.write(b"Unresolved transaction images; inspect before opening.\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _clean_empty(self) -> None:
        if (self._images or self._reserved or self._pending
                or self._debt or self._cleaning):
            return
        if self.directory.exists() and any(self.directory.iterdir()):
            raise OSError("Unexpected orphan undo artifacts remain")
        if self.directory.exists():
            self.directory.rmdir()
        self.marker.unlink(missing_ok=True)

    def capture(self, transaction_id: TransactionId, files: TableFiles) -> TableImage:
        if not isinstance(transaction_id, TransactionId) or not isinstance(files, TableFiles):
            raise TypeError("Capture requires a transaction ID and table file set")
        # A table X grant is the caller's precondition. The quota mutex only
        # protects accounting; it never encloses file copying or lock waits.
        with self._capture_slots:
            lengths = tuple(path.stat().st_size for path in files.physical_files)
            prior_replacements = tuple(
                candidate for path in files.physical_files
                for candidate in _replacement_candidates(path)
            )
            bytes_needed = sum(lengths)
            with self._mutex:
                existing = self._images.get(transaction_id, {}).get(files.name)
                if existing is not None:
                    return existing
                if (self._reserved.get(transaction_id, 0) + bytes_needed
                        > self.limits.per_transaction_bytes
                        or sum(self._reserved.values()) + bytes_needed
                        > self.limits.total_bytes):
                    raise TransactionCapacityError("Undo image quota exceeded")
                pending_after_reservation = sum(self._pending.values()) + bytes_needed
                if shutil.disk_usage(self.root).free < (
                    pending_after_reservation + self.limits.free_reserve_bytes
                ):
                    raise TransactionCapacityError("Insufficient free space for undo image")
                self._reserved[transaction_id] = self._reserved.get(transaction_id, 0) + bytes_needed
                self._pending[transaction_id] = self._pending.get(transaction_id, 0) + bytes_needed
                try:
                    if not self.marker.exists():
                        self._mark_unclean()
                except BaseException:
                    self._reserved[transaction_id] -= bytes_needed
                    if self._reserved[transaction_id] == 0:
                        del self._reserved[transaction_id]
                    self._pending[transaction_id] -= bytes_needed
                    if self._pending[transaction_id] == 0:
                        del self._pending[transaction_id]
                    raise
            # Physical identities are opaque metadata, never path components.
            safe_identity = hashlib.sha256(files.identity.encode("utf-8")).hexdigest()
            image_dir = self.directory / f"tx_{transaction_id.value}" / safe_identity
            try:
                image_dir.mkdir(parents=True, exist_ok=False)
                images = []
                for number, (path, length) in enumerate(zip(files.physical_files, lengths)):
                    image_path = image_dir / f"{number}.bin"
                    digest = hashlib.sha256()
                    copied = 0
                    with path.open("rb") as source, image_path.open("xb") as target:
                        while True:
                            block = source.read(self.limits.chunk_bytes)
                            if not block:
                                break
                            target.write(block)
                            digest.update(block)
                            copied += len(block)
                        target.flush()
                        os.fsync(target.fileno())
                    if copied != length:
                        raise OSError(f"File size changed during undo capture: {path}")
                    images.append(FileImage(path, image_path, length, digest.hexdigest()))
                descriptor = image_dir / "descriptor.json"
                payload = {
                    "version": 1, "transaction": transaction_id.value,
                    "table": files.name, "identity": files.identity,
                    "prior_replacements": [str(path) for path in prior_replacements],
                    "files": [
                        {"path": str(item.path), "image": item.image.name,
                         "length": item.length, "sha256": item.sha256}
                        for item in images
                    ],
                }
                with descriptor.open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                result = TableImage(
                    transaction_id, files.name, files.identity,
                    tuple(images), descriptor, prior_replacements,
                )
                with self._mutex:
                    self._images.setdefault(transaction_id, {})[files.name] = result
                    self._pending[transaction_id] -= bytes_needed
                    if self._pending[transaction_id] == 0:
                        del self._pending[transaction_id]
                return result
            except BaseException as capture_error:
                # Partial images are never published. Retain a marker if even
                # their cleanup fails, because a fresh open must inspect them.
                try:
                    if image_dir.exists():
                        shutil.rmtree(image_dir)
                    parent = image_dir.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                except BaseException as cleanup_error:
                    with self._mutex:
                        self._debt.add(transaction_id)
                    capture_error.add_note(
                        f"Partial undo cleanup also failed: {cleanup_error}"
                    )
                finally:
                    with self._mutex:
                        self._reserved[transaction_id] -= bytes_needed
                        if self._reserved[transaction_id] == 0:
                            del self._reserved[transaction_id]
                        self._pending[transaction_id] -= bytes_needed
                        if self._pending[transaction_id] == 0:
                            del self._pending[transaction_id]
                        try:
                            self._clean_empty()
                        except BaseException as cleanup_error:
                            self._debt.add(transaction_id)
                            capture_error.add_note(
                                f"Undo marker cleanup also failed: {cleanup_error}"
                            )
                raise capture_error

    def restore(self, image: TableImage, files: TableFiles) -> None:
        if (image.table_name != files.name or image.table_identity != files.identity
                or tuple(item.path for item in image.files) != files.physical_files):
            raise TransactionUnavailableError("Undo descriptor does not match table file set")
        prior = set(image.prior_replacements)
        for path in files.physical_files:
            for candidate in _replacement_candidates(path):
                if candidate not in prior:
                    candidate.unlink()
        for number, item in enumerate(image.files):
            if item.image.stat().st_size != item.length:
                raise OSError(f"Undo image length mismatch for {item.path}")
            digest = hashlib.sha256()
            temporary = item.path.with_name(
                item.path.name + f".undo_restore_{image.transaction_id.value}_{number}"
            )
            try:
                with item.image.open("rb") as source, temporary.open("xb") as target:
                    copied = 0
                    while True:
                        block = source.read(self.limits.chunk_bytes)
                        if not block:
                            break
                        target.write(block)
                        digest.update(block)
                        copied += len(block)
                    target.flush()
                    os.fsync(target.fileno())
                if copied != item.length or digest.hexdigest() != item.sha256:
                    raise OSError(f"Undo image checksum mismatch for {item.path}")
                os.replace(temporary, item.path)
            finally:
                temporary.unlink(missing_ok=True)

    def discard(self, transaction_id: TransactionId) -> tuple[str, ...]:
        """Idempotent post-terminal cleanup; errors become retained artifact debt."""
        parent = self.directory / f"tx_{transaction_id.value}"
        with self._mutex:
            if transaction_id in self._cleaning:
                return (f"Undo cleanup in progress for transaction {transaction_id.value}",)
            self._cleaning.add(transaction_id)
        try:
            if parent.exists():
                shutil.rmtree(parent)
        except BaseException as error:
            with self._mutex:
                self._debt.add(transaction_id)
                self._cleaning.discard(transaction_id)
            return (f"Undo cleanup pending for transaction {transaction_id.value}: {error}",)
        with self._mutex:
            self._images.pop(transaction_id, None)
            self._reserved.pop(transaction_id, None)
            self._pending.pop(transaction_id, None)
            self._debt.discard(transaction_id)
            self._cleaning.discard(transaction_id)
            try:
                self._clean_empty()
                return ()
            except BaseException as error:
                self._debt.add(transaction_id)
                return (f"Undo cleanup pending for transaction {transaction_id.value}: {error}",)
