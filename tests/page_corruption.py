"""Shared malformed metadata for the (page 7, alpha/beta) test fixture.

Used by page-memory tests and disk-loading tests, not packaged with the engine.
"""

INVALID_SLOT_FIELDS = (
    (4091, 5, 2), (4091, 5, 0), (0, 1, 1), (4096, 1, 1),
    (4000, 65535, 1), (4000, 5, 1), (17, 1, 1), (4000, 0, 1),
    (0, 0, 0),
)

INVALID_PAGE_HEADER_FIELDS = (
    (7, 2, 21, 4087, 2), (7, 2, 22, 21, 2), (7, 2, 22, 4097, 2),
    (7, 2, 22, 4087, 1), (7, 0, 12, 4087, 0),
)
