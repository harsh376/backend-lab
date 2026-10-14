from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import count

type BookID = str
type PatronID = str
type LoanID = int
type IdempotencyKey = str


@dataclass(frozen=True)
class Loan:
    id_: LoanID
    book_id: BookID
    patron_id: PatronID


@dataclass(frozen=True)
class Book:
    id_: BookID
    stock: int


class IdempotentCheckoutService:
    def __init__(self):
        self._books: dict[BookID, Book] = {}
        self.loan_sequence = count()
        self._loans: dict[LoanID, Loan] = {}
        self._checkouts: dict[IdempotencyKey, tuple[Loan, Book]] = {}

    def _validate_non_empty_string(self, value: str):
        if not isinstance(value, str) or value.isspace() or value == "":
            raise Exception("Not a non-empty string")

    def _validate_positive_int(self, value: int):
        if type(value) is not int or value <= 0:
            raise Exception("Not a positive number")

    def _validate_non_negative_int(self, value: int):
        if type(value) is not int or value < 0:
            raise Exception("Not a non-negative number")

    def register_book(self, book_id: BookID, stock: int) -> BookID:
        self._validate_non_empty_string(book_id)
        self._validate_non_negative_int(stock)

        if book_id in self._books:
            raise Exception("Book already exists")

        self._books[book_id] = Book(id_=book_id, stock=stock)
        return book_id

    def add_copies(self, book_id: BookID, copies: int):
        self._validate_non_empty_string(book_id)
        self._validate_positive_int(copies)

        book = self._books.get(book_id)
        if book is None:
            raise Exception("Book does not exist")

        self._books[book_id] = replace(book, stock=book.stock + copies)

    def checkout(
        self, book_id: BookID, patron_id: PatronID, idempotency_key: IdempotencyKey
    ) -> tuple[Loan, Book]:
        self._validate_non_empty_string(book_id)
        self._validate_non_empty_string(patron_id)
        if not isinstance(idempotency_key, str):
            raise Exception("Idempotency key must be a string")

        book = self._books.get(book_id)
        if book is None:
            raise Exception("Book does not exist")

        cached_response = self._checkouts.get(idempotency_key)
        if cached_response is not None:
            cached_loan, cached_book = cached_response
            if (
                cached_loan.book_id == book_id
                and cached_loan.patron_id == patron_id
                and cached_book.id_ == book_id
            ):
                return cached_response
            raise Exception(
                "Response for id_key is not consistent with supplied book and patron"
            )

        if book.stock == 0:
            raise Exception("No stock available")

        loan_id = next(self.loan_sequence)
        self._loans[loan_id] = Loan(
            id_=loan_id,
            book_id=book_id,
            patron_id=patron_id,
        )
        self._books[book_id] = replace(book, stock=book.stock - 1)
        response = self._loans[loan_id], self._books[book_id]
        self._checkouts[idempotency_key] = response
        return response

    def inspect_stock(self, book_id: BookID) -> Book:
        self._validate_non_empty_string(book_id)

        book = self._books.get(book_id)
        if book is None:
            raise Exception("Book does not exist")

        return book

    def inspect_loan(self, loan_id: LoanID):
        if type(loan_id) is not int:
            raise Exception("Invalid loan_id")

        loan = self._loans.get(loan_id)
        if loan is None:
            raise Exception("Loan does not exist")

        return loan

    def get_state(self):
        return deepcopy(
            {
                "books": self._books,
                "loans": self._loans,
                "checkouts": self._checkouts,
            }
        )
