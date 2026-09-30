import unittest
from dataclasses import FrozenInstanceError

from apps.api.services.idempotent_checkout.idempotent_checkout import (
    Book,
    IdempotentCheckoutService,
    Loan,
)


class TestIdempotentCheckoutService(unittest.TestCase):
    def setUp(self):
        self.service = IdempotentCheckoutService()

    def test_flow(self):
        service = self.service

        service.register_book("B", 2)

        self.assertEqual(
            service.checkout("B", "Alice", "K1"),
            (
                Loan(id_=0, book_id="B", patron_id="Alice"),
                Book(id_="B", stock=1),
            ),
        )

        self.assertEqual(
            service.get_state(),
            {
                "books": {"B": Book(id_="B", stock=1)},
                "checkouts": {
                    "K1": (
                        Loan(id_=0, book_id="B", patron_id="Alice"),
                        Book(id_="B", stock=1),
                    )
                },
                "loans": {0: Loan(id_=0, book_id="B", patron_id="Alice")},
            },
        )

        service.checkout("B", "Bob", "K2")

        self.assertEqual(
            service.get_state(),
            {
                "books": {"B": Book(id_="B", stock=0)},
                "checkouts": {
                    "K1": (
                        Loan(id_=0, book_id="B", patron_id="Alice"),
                        Book(id_="B", stock=1),
                    ),
                    "K2": (
                        Loan(id_=1, book_id="B", patron_id="Bob"),
                        Book(id_="B", stock=0),
                    ),
                },
                "loans": {
                    0: Loan(id_=0, book_id="B", patron_id="Alice"),
                    1: Loan(id_=1, book_id="B", patron_id="Bob"),
                },
            },
        )

        self.assertEqual(
            service.checkout("B", "Alice", "K1"),
            (
                Loan(id_=0, book_id="B", patron_id="Alice"),
                Book(id_="B", stock=1),
            ),
        )

        service.register_book("C", 2)
        self.assertEqual(
            service.get_state(),
            {
                "books": {"B": Book(id_="B", stock=0), "C": Book(id_="C", stock=2)},
                "checkouts": {
                    "K1": (
                        Loan(id_=0, book_id="B", patron_id="Alice"),
                        Book(id_="B", stock=1),
                    ),
                    "K2": (
                        Loan(id_=1, book_id="B", patron_id="Bob"),
                        Book(id_="B", stock=0),
                    ),
                },
                "loans": {
                    0: Loan(id_=0, book_id="B", patron_id="Alice"),
                    1: Loan(id_=1, book_id="B", patron_id="Bob"),
                },
            },
        )

        with self.assertRaisesRegex(
            Exception,
            "Response for id_key is not consistent with supplied book and patron",
        ):
            service.checkout("C", "Alice", "K1")

    def test_lost_response_and_replay(self):
        service = self.service

        service.register_book("B", 2)
        service.checkout("B", "Alice", "K1")
        service.checkout("B", "Bob", "K2")
        self.assertEqual(
            service.get_state(),
            {
                "books": {"B": Book(id_="B", stock=0)},
                "checkouts": {
                    "K1": (
                        Loan(id_=0, book_id="B", patron_id="Alice"),
                        Book(id_="B", stock=1),
                    ),
                    "K2": (
                        Loan(id_=1, book_id="B", patron_id="Bob"),
                        Book(id_="B", stock=0),
                    ),
                },
                "loans": {
                    0: Loan(id_=0, book_id="B", patron_id="Alice"),
                    1: Loan(id_=1, book_id="B", patron_id="Bob"),
                },
            },
        )

    def test_retry_after_failure(self):
        service = self.service
        service.register_book("C", 0)

        with self.assertRaisesRegex(Exception, "No stock available"):
            service.checkout("C", "Alice", "K3")

        service.add_copies("C", 1)
        service.checkout("C", "Alice", "K3")
        self.assertEqual(
            service.get_state(),
            {
                "books": {"C": Book(id_="C", stock=0)},
                "checkouts": {
                    "K3": (
                        Loan(id_=0, book_id="C", patron_id="Alice"),
                        Book(id_="C", stock=0),
                    )
                },
                "loans": {0: Loan(id_=0, book_id="C", patron_id="Alice")},
            },
        )

    def test_returned_books_are_immutable(self):
        service = self.service
        service.register_book("B", 2)
        original = service.checkout("B", "Alice", "K1")

        for book in (original[1], service.inspect_stock("B")):
            with self.assertRaises(FrozenInstanceError):
                book.stock = 99

        service.checkout("B", "Bob", "K2")

        self.assertEqual(service.inspect_stock("B").stock, 0)
        self.assertEqual(service.checkout("B", "Alice", "K1"), original)
        self.assertEqual(original[1].stock, 1)


if __name__ == "__main__":
    unittest.main()
