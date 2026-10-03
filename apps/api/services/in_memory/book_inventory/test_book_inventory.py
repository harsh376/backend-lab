import pytest

from apps.api.services.book_inventory.book_inventory import (
    Book,
    BookAlreadyExists,
    BookInventoryService,
    BookNotFoundError,
    InvalidNumberOfCopies,
    InvalidPublicationYear,
    InvalidString,
    SearchResult,
)


def test_add_book():
    service = BookInventoryService()

    assert (
        service.add_book("book1", "My title", "Author1", "Horror", 1996, 1) == "book1"
    )

    with pytest.raises(BookAlreadyExists):
        service.add_book("book1", "My title", "Author1", "Horror", 1996, 1)

    with pytest.raises(InvalidString):
        service.add_book("book2", "", "Author1", "Horror", 1996, 1)

    with pytest.raises(InvalidPublicationYear):
        service.add_book("book2", "Title1", "Author1", "Horror", 0, 1)

    with pytest.raises(InvalidNumberOfCopies):
        service.add_book("book2", "Title1", "Author1", "Horror", 1998, -1)


def test_set_copies():
    service = BookInventoryService()

    with pytest.raises(BookNotFoundError):
        service.set_copies_available("book1", 10)

    service.add_book("book1", "My title", "Author1", "Horror", 1996, 1)

    with pytest.raises(InvalidNumberOfCopies):
        service.set_copies_available("book1", -1)

    assert service.get_book("book1") == Book(
        book_id="book1",
        title="My title",
        author="Author1",
        genre="Horror",
        publication_year=1996,
        copies_available=1,
    )

    service.set_copies_available("book1", 10)

    assert service.get_book("book1") == Book(
        book_id="book1",
        title="My title",
        author="Author1",
        genre="Horror",
        publication_year=1996,
        copies_available=10,
    )


@pytest.mark.parametrize("copies", [-1, True, False, 1.5, "2", None])
def test_copies_must_be_nonnegative_integers(copies):
    service = BookInventoryService()

    with pytest.raises(InvalidNumberOfCopies):
        service.add_book("book1", "Title", "Author", "Genre", 2000, copies)
    assert service.books == {}

    service.add_book("book1", "Title", "Author", "Genre", 2000, 0)
    with pytest.raises(InvalidNumberOfCopies):
        service.set_copies_available("book1", copies)
    assert service.get_book("book1").copies_available == 0


def test_get_book():
    service = BookInventoryService()

    with pytest.raises(BookNotFoundError):
        service.get_book("book1")


def test_search():
    service = BookInventoryService()

    service.add_book(
        "b1",
        "The Left Hand of Darkness",
        "Ursula K. Le Guin",
        "Science Fiction",
        1969,
        2,
    )

    service.add_book(
        "b2",
        "Left Behind",
        "Tim LaHaye",
        "Fiction",
        1995,
        0,
    )

    service.add_book(
        "b3",
        "A Wizard of Earthsea",
        "Ursula K. Le Guin",
        "Fantasy",
        1968,
        1,
    )

    service.add_book(
        "b4",
        "Earthsea",
        "Ursula K. Le Guin",
        "Fantasy",
        1990,
        0,
    )

    assert service.search_books("left") == SearchResult(
        total=2,
        matches=[
            Book(
                book_id="b2",
                title="Left Behind",
                author="Tim LaHaye",
                genre="Fiction",
                publication_year=1995,
                copies_available=0,
            ),
            Book(
                book_id="b1",
                title="The Left Hand of Darkness",
                author="Ursula K. Le Guin",
                genre="Science Fiction",
                publication_year=1969,
                copies_available=2,
            ),
        ],
    )

    assert service.search_books("ursula", "Fantasy") == SearchResult(
        total=2,
        matches=[
            Book(
                book_id="b3",
                title="A Wizard of Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1968,
                copies_available=1,
            ),
            Book(
                book_id="b4",
                title="Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1990,
                copies_available=0,
            ),
        ],
    )

    assert service.search_books("", "Fantasy", "available") == SearchResult(
        total=1,
        matches=[
            Book(
                book_id="b3",
                title="A Wizard of Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1968,
                copies_available=1,
            )
        ],
    )

    assert service.search_books("", "fantasy") == SearchResult(
        total=0,
        matches=[],
    )

    assert service.search_books(
        "ursula", "Fantasy", "all", "publication_year", "desc"
    ) == SearchResult(
        total=2,
        matches=[
            Book(
                book_id="b4",
                title="Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1990,
                copies_available=0,
            ),
            Book(
                book_id="b3",
                title="A Wizard of Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1968,
                copies_available=1,
            ),
        ],
    )

    assert service.search_books(query="ursula", offset=1, limit=1) == SearchResult(
        total=3,
        matches=[
            Book(
                book_id="b4",
                title="Earthsea",
                author="Ursula K. Le Guin",
                genre="Fantasy",
                publication_year=1990,
                copies_available=0,
            )
        ],
    )
