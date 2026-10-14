from dataclasses import FrozenInstanceError

import pytest

from backend.services.in_memory.idempotent_checkout.idempotent_checkout import (
    Book,
    IdempotentCheckoutService,
    Loan,
)


@pytest.fixture
def service():
    return IdempotentCheckoutService()


def test_flow(service):

    service.register_book("B", 2)

    assert service.checkout("B", "Alice", "K1") == (
        Loan(id_=0, book_id="B", patron_id="Alice"),
        Book(id_="B", stock=1),
    )

    assert service.get_state() == {
        "books": {"B": Book(id_="B", stock=1)},
        "checkouts": {
            "K1": (Loan(id_=0, book_id="B", patron_id="Alice"), Book(id_="B", stock=1))
        },
        "loans": {0: Loan(id_=0, book_id="B", patron_id="Alice")},
    }

    service.checkout("B", "Bob", "K2")

    assert service.get_state() == {
        "books": {"B": Book(id_="B", stock=0)},
        "checkouts": {
            "K1": (Loan(id_=0, book_id="B", patron_id="Alice"), Book(id_="B", stock=1)),
            "K2": (Loan(id_=1, book_id="B", patron_id="Bob"), Book(id_="B", stock=0)),
        },
        "loans": {
            0: Loan(id_=0, book_id="B", patron_id="Alice"),
            1: Loan(id_=1, book_id="B", patron_id="Bob"),
        },
    }

    assert service.checkout("B", "Alice", "K1") == (
        Loan(id_=0, book_id="B", patron_id="Alice"),
        Book(id_="B", stock=1),
    )

    service.register_book("C", 2)
    assert service.get_state() == {
        "books": {"B": Book(id_="B", stock=0), "C": Book(id_="C", stock=2)},
        "checkouts": {
            "K1": (Loan(id_=0, book_id="B", patron_id="Alice"), Book(id_="B", stock=1)),
            "K2": (Loan(id_=1, book_id="B", patron_id="Bob"), Book(id_="B", stock=0)),
        },
        "loans": {
            0: Loan(id_=0, book_id="B", patron_id="Alice"),
            1: Loan(id_=1, book_id="B", patron_id="Bob"),
        },
    }

    with pytest.raises(
        Exception,
        match="Response for id_key is not consistent with supplied book and patron",
    ):
        service.checkout("C", "Alice", "K1")


def test_lost_response_and_replay(service):

    service.register_book("B", 2)
    service.checkout("B", "Alice", "K1")
    service.checkout("B", "Bob", "K2")
    assert service.get_state() == {
        "books": {"B": Book(id_="B", stock=0)},
        "checkouts": {
            "K1": (Loan(id_=0, book_id="B", patron_id="Alice"), Book(id_="B", stock=1)),
            "K2": (Loan(id_=1, book_id="B", patron_id="Bob"), Book(id_="B", stock=0)),
        },
        "loans": {
            0: Loan(id_=0, book_id="B", patron_id="Alice"),
            1: Loan(id_=1, book_id="B", patron_id="Bob"),
        },
    }


def test_retry_after_failure(service):
    service.register_book("C", 0)

    with pytest.raises(Exception, match="No stock available"):
        service.checkout("C", "Alice", "K3")

    service.add_copies("C", 1)
    service.checkout("C", "Alice", "K3")
    assert service.get_state() == {
        "books": {"C": Book(id_="C", stock=0)},
        "checkouts": {
            "K3": (Loan(id_=0, book_id="C", patron_id="Alice"), Book(id_="C", stock=0))
        },
        "loans": {0: Loan(id_=0, book_id="C", patron_id="Alice")},
    }


def test_returned_books_are_immutable(service):
    service.register_book("B", 2)
    original = service.checkout("B", "Alice", "K1")

    for book in (original[1], service.inspect_stock("B")):
        with pytest.raises(FrozenInstanceError):
            book.stock = 99

    service.checkout("B", "Bob", "K2")

    assert service.inspect_stock("B").stock == 0
    assert service.checkout("B", "Alice", "K1") == original
    assert original[1].stock == 1
