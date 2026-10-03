# Book inventory search practice brief

This is an original Python practice exercise for a Senior Software Engineer
assessment. Implement the feature as an in-memory service. Keep the exercise at
the service level: no API, UI, database, async code, or external services.

Act as an interviewer and reviewer. Let me implement the solution. Answer
clarification questions, but do not provide implementation code or a complete
solution unless I explicitly ask. Review my work against the contract and point
out concrete correctness, test coverage, and maintainability issues.

## Time budget

Allow 60 minutes, including tests:

- 5 minutes to read the brief and clarify the contract.
- 35 minutes to implement the service.
- 15 minutes to write and run focused tests.
- 5 minutes to review the result and explain tradeoffs.

Ask me to set my own timer; do not assume you can track elapsed time between
messages.

## Scenario

A library's catalog has grown large enough that users struggle to find books.
Add searching, filtering, sorting, and pagination to its inventory service.

Build an in-memory `BookInventoryService` that supports these operations:

```python
add_book(book_id, title, author, genre, publication_year, copies_available)
set_copies_available(book_id, copies_available)
get_book(book_id)
search_books(
    query="",
    genre=None,
    availability="all",
    sort_by="title",
    sort_order="asc",
    offset=0,
    limit=20,
)
```

Choose clear result types and exception types. Explain your choices before
coding and use them consistently.

## Book data

Each book contains:

- `book_id`: a nonempty, case-sensitive string that is unique for the lifetime
  of the service.
- `title`: a nonempty string.
- `author`: a nonempty string.
- `genre`: a nonempty string. There is no separate genre registry.
- `publication_year`: an integer.
- `copies_available`: a nonnegative integer. Reject booleans as integers.

`add_book` rejects duplicate IDs without changing the existing book.
`set_copies_available` replaces the current quantity; it does not increment it.
Reads and failed mutations must not change service state.

You may assume calls execute sequentially. Persistence between service instances
is not required.

## Search contract

`search_books` returns the selected page of books together with the total number
of matches before pagination.

Apply operations in this order:

1. Text search.
2. Genre and availability filters.
3. Sorting.
4. Pagination.

### Text search

- Match `query` as a substring of either the title or author.
- Matching is case-insensitive.
- An empty query matches every book.
- Do not trim or otherwise normalize stored book data.

### Filters

- `genre=None` matches every genre.
- A supplied genre uses exact, case-sensitive matching.
- `availability` accepts exactly `"all"`, `"available"`, or `"unavailable"`.
- `"available"` means `copies_available > 0`.
- `"unavailable"` means `copies_available == 0`.
- Text search and all supplied filters combine with AND.

### Sorting

- `sort_by` accepts exactly `"title"`, `"author"`, or `"publication_year"`.
- `sort_order` accepts exactly `"asc"` or `"desc"`.
- Title and author sorting is case-insensitive.
- Break every sorting tie by `book_id` in ascending order, regardless of the
  requested sort direction. Results must therefore be deterministic.

### Pagination

- `offset` and `limit` must be nonnegative integers; reject booleans.
- Calculate `total` after searching and filtering but before pagination.
- `limit=0` returns an empty page while preserving the correct total.
- An offset beyond the final match returns an empty page.
- Search results must not let callers mutate the service's internal state.

Reject unsupported filter or sort values rather than silently substituting
defaults.

## Examples

Given these books:

| ID | Title | Author | Genre | Year | Copies |
| --- | --- | --- | --- | ---: | ---: |
| `b1` | The Left Hand of Darkness | Ursula K. Le Guin | Science Fiction | 1969 | 2 |
| `b2` | Left Behind | Tim LaHaye | Fiction | 1995 | 0 |
| `b3` | A Wizard of Earthsea | Ursula K. Le Guin | Fantasy | 1968 | 1 |
| `b4` | Earthsea | Ursula K. Le Guin | Fantasy | 1990 | 0 |

- Searching for `"left"` returns `b1` and `b2`.
- Searching for `"ursula"` with genre `"Fantasy"` returns `b3` and `b4`.
- Filtering for genre `"Fantasy"` and availability `"available"` returns only
  `b3`.
- Searching with genre `"fantasy"` returns no books because genre matching is
  case-sensitive.
- Sorting the two Fantasy books by publication year descending returns `b4`,
  then `b3`.
- If three books match but `offset=1` and `limit=1`, return one book and
  `total=3`.

## Expected tests

Write focused tests covering at least:

- Adding, retrieving, and updating a book.
- Duplicate IDs and unknown IDs.
- Case-insensitive title and author search.
- Each filter individually and all filters combined.
- Available versus unavailable boundary behavior at zero copies.
- Every sort field, descending order, and deterministic ties.
- Filtering and sorting before pagination.
- Zero limit and an offset beyond the result set.
- Invalid pagination, availability, and sorting arguments.
- Failed operations preserving existing state.
- Mutation of returned results not affecting later reads.

## Review criteria

- Correct filtering, total count, sorting, and pagination semantics.
- Deterministic results, especially when sort values are equal.
- Explicit and consistent validation and error behavior.
- Internal state is protected from accidental mutation.
- Straightforward code with clear responsibilities.
- Tests emphasize boundaries and combinations rather than mirroring the
  implementation line by line.
- Ability to explain the time and space complexity of search and possible
  changes required for a database-backed implementation.

Start by asking me to describe my result types and error contract. Do not
implement the service for me.
