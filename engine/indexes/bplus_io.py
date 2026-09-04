"""B+ metadata/node page I/O delegated entirely to PageManager."""

from __future__ import annotations

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.page import Page
from engine.storage.page_manager import PageManager

from .bplus_header import BPlusFileHeader
from .bplus_node import BPlusFreeNode, BPlusInternalNode, BPlusLeafNode
from .bplus_node_codec import BPlusNode, BPlusNodeCodec


_HEADER_PAGE_ID = 0
_ONLY_SLOT_ID = 0


def _require_manager(manager: object) -> PageManager:
    if not isinstance(manager, PageManager):
        raise InvalidTypeError("manager must be a PageManager")
    return manager


def _single_payload_page(page_id: int, payload: bytes) -> Page:
    page = Page(page_id)
    slot_id = page.insert(payload)
    if slot_id != _ONLY_SLOT_ID:
        raise ValidationError("B+ page payload must occupy slot 0")
    return page


def _read_only_payload(page: Page, label: str) -> bytes:
    if page.slot_count != 1 or page.active_record_count != 1:
        raise ValidationError(f"Invalid {label} page layout")
    if not page.slots[_ONLY_SLOT_ID].is_active:
        raise ValidationError(f"Invalid {label} page slot state")
    return page.read(_ONLY_SLOT_ID)


class BPlusHeaderPageIO:
    """Read/write the canonical B+ descriptor in physical page 0."""

    @staticmethod
    def initialize(manager: PageManager, header: BPlusFileHeader) -> None:
        checked_manager = _require_manager(manager)
        if not isinstance(header, BPlusFileHeader):
            raise InvalidTypeError("header must be a BPlusFileHeader")
        if checked_manager.allocated_page_count != 0:
            raise ValidationError("B+ header initialization requires an empty file")
        if header.node_page_count != 0:
            raise ValidationError("Initial B+ header cannot reference node pages")
        payload = header.serialize()
        page_id = checked_manager.allocate_page()
        if page_id != _HEADER_PAGE_ID:
            raise ValidationError("B+ metadata page must be physical page 0")
        checked_manager.write_page(_single_payload_page(page_id, payload))

    @staticmethod
    def read(manager: PageManager) -> BPlusFileHeader:
        checked_manager = _require_manager(manager)
        if checked_manager.allocated_page_count < 1:
            raise ValidationError("B+ file has no metadata page")
        page = checked_manager.read_page(_HEADER_PAGE_ID)
        header = BPlusFileHeader.deserialize(
            _read_only_payload(page, "B+ metadata")
        )
        if checked_manager.allocated_page_count != header.node_page_count + 1:
            raise ValidationError(
                "B+ node-page count does not match the physical file"
            )
        return header

    @staticmethod
    def write(manager: PageManager, header: BPlusFileHeader) -> None:
        checked_manager = _require_manager(manager)
        if not isinstance(header, BPlusFileHeader):
            raise InvalidTypeError("header must be a BPlusFileHeader")
        if checked_manager.allocated_page_count != header.node_page_count + 1:
            raise ValidationError(
                "B+ header node-page count does not match the physical file"
            )
        checked_manager.write_page(
            _single_payload_page(_HEADER_PAGE_ID, header.serialize())
        )


class BPlusNodePageIO:
    """Allocate/read/write B+ node frames through one borrowed PageManager."""

    def __init__(self, manager: PageManager, key_type: DataType) -> None:
        self._manager = _require_manager(manager)
        if not isinstance(key_type, DataType):
            raise InvalidTypeError("key_type must be a DataType")
        self._key_type = key_type

    @property
    def key_type(self) -> DataType:
        return self._key_type

    def allocate_page(self) -> int:
        page_id = self._manager.allocate_page()
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("Allocate the B+ metadata page before node pages")
        return page_id

    def frame_node(self, node: BPlusNode) -> Page:
        self._validate_node(node)
        return _single_payload_page(node.page_id, BPlusNodeCodec.serialize(node))

    def write_node(self, node: BPlusNode) -> None:
        self._manager.write_page(self.frame_node(node))

    def read_node(self, page_id: int) -> BPlusNode:
        if type(page_id) is not int:
            raise InvalidTypeError("B+ node page_id must be a built-in int")
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("B+ node cannot use reserved metadata page 0")
        page = self._manager.read_page(page_id)
        node = BPlusNodeCodec.deserialize(
            self._key_type,
            _read_only_payload(page, "B+ node"),
        )
        if node.page_id != page_id:
            raise ValidationError(
                f"Stored B+ node page_id {node.page_id} does not match "
                f"physical page_id {page_id}"
            )
        return node

    def _validate_node(self, node: object) -> None:
        if not isinstance(node, (BPlusLeafNode, BPlusInternalNode, BPlusFreeNode)):
            raise InvalidTypeError("node must be a B+ leaf, internal, or free node")
        if (
            isinstance(node, (BPlusLeafNode, BPlusInternalNode))
            and node.key_type is not self._key_type
        ):
            raise ValidationError("B+ node key type differs from its index file")
