"""Text preprocessing, external SPIMI construction and persistent readers."""

from .format import CollectionStatistics, DocumentEntry, TermEntry
from .index import PostingIterator, TextIndex
from .ranking import TextHit, TextRankingReport, TextSearchResult, search_text
from .spimi import SpimiBuildReport, build_spimi
from .tokenizer import tokenize, tokenizer_signature

__all__ = [
    "CollectionStatistics", "DocumentEntry", "TermEntry", "PostingIterator",
    "TextIndex", "SpimiBuildReport", "build_spimi", "tokenize", "tokenizer_signature",
    "TextHit", "TextRankingReport", "TextSearchResult", "search_text",
]
