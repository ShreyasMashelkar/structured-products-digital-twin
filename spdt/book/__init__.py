"""L8 Virtual Trading Book: positions, daily marks, netted Greeks across the book."""

from spdt.book.book import BookMark, PositionMark, Trade, mark_book
from spdt.book.generator import generate_autocallable_book, generate_mixed_book

__all__ = [
    "BookMark",
    "PositionMark",
    "Trade",
    "generate_autocallable_book",
    "generate_mixed_book",
    "mark_book",
]
