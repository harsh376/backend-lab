from dataclasses import dataclass, replace
from typing import Literal

type BookID = str
type Availability = Literal["all", "available", "unavailable"]
type SortBy = Literal["title", "author", "publication_year"]
type SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class Book:
    book_id: BookID
    title: str
    author: str
    genre: str
    publication_year: int
    copies_available: int


@dataclass(frozen=True)
class SearchResult:
    total: int
    matches: list[Book]


class BookAlreadyExists(Exception):
    pass


class BookNotFoundError(Exception):
    pass


class InvalidString(Exception):
    pass


class InvalidNumberOfCopies(Exception):
    pass


class InvalidPublicationYear(Exception):
    pass


class NotNonnegativeInteger(Exception):
    pass


class InvalidValue(Exception):
    pass


class BookInventoryService:
    def __init__(self):
        self.books: dict[BookID, Book] = {}

    def _validate_string(self, value: str):
        if not isinstance(value, str) or value == "" or value.isspace():
            raise InvalidString(value)

    def _validate_year(self, value: int):
        if type(value) is int and value > 0:
            return
        raise InvalidPublicationYear

    def _validate_non_negative_integer(self, value: int):
        if type(value) is int and value > 0:
            return
        raise NotNonnegativeInteger

    def _validate_copies(self, value: int):
        if type(value) is not int or value < 0:
            raise InvalidNumberOfCopies(value)

    def add_book(
        self, book_id, title, author, genre, publication_year, copies_available
    ) -> BookID:
        """
        - pk constraint on id

        """
        for field in (book_id, title, author, genre):
            self._validate_string(field)

        self._validate_copies(copies_available)

        self._validate_year(publication_year)

        if book_id in self.books:
            raise BookAlreadyExists

        self.books[book_id] = Book(
            book_id, title, author, genre, publication_year, copies_available
        )
        return book_id

    def set_copies_available(self, book_id: BookID, copies_available: int):
        """
        - replace current quantity
        """
        book = self.books.get(book_id)
        if book is None:
            raise BookNotFoundError

        self._validate_string(book_id)
        self._validate_copies(copies_available)

        self.books[book_id] = replace(book, copies_available=copies_available)
        return book_id

    def get_book(self, book_id: BookID) -> Book:
        self._validate_string(book_id)

        book = self.books.get(book_id)
        if book is None:
            raise BookNotFoundError

        return book

    def _validate_option(self, options: list[str], value: str):
        if value not in options:
            raise InvalidValue(f"{value}")

    def _validate_offset_and_limit(self, offset, limit):
        if type(offset) is not int or offset < 0:
            raise Exception("Bad offset")

        if type(limit) is not int or limit < 0:
            raise Exception("Bad limit")

    def search_books(
        self,
        query="",
        genre=None,
        availability: Availability = "all",
        sort_by: SortBy = "title",
        sort_order: SortOrder = "asc",
        offset=0,
        limit=20,
    ) -> SearchResult:
        """
        - return total matches before pagination
        """

        self._validate_option(["all", "available", "unavailable"], availability)
        self._validate_option(["title", "author", "publication_year"], sort_by)
        self._validate_option(["asc", "desc"], sort_order)
        self._validate_offset_and_limit(offset, limit)

        matches = []
        for _, book in self.books.items():
            if (
                (genre is None or book.genre == genre)
                and (
                    availability == "all"
                    or (availability == "available" and book.copies_available > 0)
                    or (availability == "unavailable" and book.copies_available == 0)
                )
            ) and (
                query == ""
                or query.casefold() in book.title.casefold()
                or query.casefold() in book.author.casefold()
            ):
                matches.append(book)

        matches.sort(key=lambda b: b.book_id)
        reverse = sort_order == "desc"
        if sort_by in ("title", "author"):
            matches.sort(key=lambda b: getattr(b, sort_by).casefold(), reverse=reverse)
        else:
            matches.sort(key=lambda b: getattr(b, sort_by), reverse=reverse)

        total = len(matches)
        return SearchResult(
            total=total,
            matches=matches[offset : offset + limit],
        )
