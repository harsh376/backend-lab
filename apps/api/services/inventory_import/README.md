# Inventory import service

An original Python service-level practice exercise. Suggested time: **40 minutes**.
Implement the service and your own tests in this directory. No API, UI, database,
threads, or external services are required. Assume sequential calls.

## Scenario

An inventory administrator imports product records in batches. Some imports
should accept valid rows despite errors; others must succeed completely or make
no changes. Administrators can also preview an import without applying it.

Build an in-memory `InventoryImportService` with this operation:

```python
import_rows(rows, *, atomic=False, dry_run=False) -> ImportResult
```

Choose your own models and supporting methods for seeding and inspecting stock.
Rows are dictionaries, and each product has `product_id`, `name`, and `stock`.

## Stage 1: validation and import modes

- Product ID and name must be nonempty strings after trimming. Store the trimmed
  values. Product IDs are case-sensitive.
- Stock must be a nonnegative integer. Reject booleans, floats, and numeric strings.
- All three fields are required in every row for this stage.
- Existing products are updated; unknown products are created. Imported stock
  replaces the previous quantity rather than adding to it.
- If a valid normalized product ID appears more than once in the batch, reject
  **every occurrence**, even if one of those rows also has another validation error.
- Report errors with **one-based row numbers**. Each rejected row must have at
  least one useful error; you may report multiple errors per row.
- Partial mode (`atomic=False`) applies valid rows and reports rejected rows.
- Atomic mode (`atomic=True`) applies nothing if any row is invalid.
- Dry run (`dry_run=True`) performs the same validation and planning without
  changing state, in either mode.
- Do not mutate the input rows or expose mutable internal state through results
  or product snapshots.
- An empty batch succeeds with all counts zero. Ignore extra row fields.

## Result contract

Return:

- Row errors, ordered by row number.
- `rejected_count`: number of invalid rows, not number of error messages.
- `planned_created_count` and `planned_updated_count`: counts of valid rows that
  would create or update products, based on state at the start of the call.
- `applied_created_count` and `applied_updated_count`: counts actually applied.

Planned counts still describe valid rows when an atomic import is rejected.
Applied counts are zero for every dry run and for an atomic import with errors.
Updating an existing product counts as an update even if its values are unchanged.

## Worked example

Initially, `apple` exists with name `Apple` and stock `5`.

```python
rows = [
    {"product_id": " apple ", "name": "Green Apple", "stock": 8},
    {"product_id": "pear", "name": "Pear", "stock": 3},
    {"product_id": "plum", "name": "Plum", "stock": -1},
]
```

Starting from that initial state independently for each mode:

| Mode | Planned creates / updates | Applied creates / updates | Rejected rows |
| --- | --- | --- | --- |
| Partial | 1 / 1 | 1 / 1 | Row 3 |
| Atomic | 1 / 1 | 0 / 0 | Row 3 |
| Dry run, either mode | 1 / 1 | 0 / 0 | Row 3 |

In partial mode, apple's stock becomes 8 and pear is created with stock 3.
In the other modes, inventory remains unchanged.

## Stage 2: introduce at minute 25

Extend the service to support patch-style updates:

- For existing products, `name` and `stock` may be omitted. Omitted fields remain
  unchanged; a row with only a valid existing product ID is a valid no-op update.
- New products still require both name and stock.
- Explicitly blank names remain invalid. Explicit `None` values are invalid,
  rather than being treated as omitted fields.
- All duplicate detection, mode, reporting, and input/output isolation rules
  continue to apply.

## Self-review

Check normalization collisions, booleans as stock, mixed valid/invalid batches,
atomic rejection, dry-run preservation, and omitted versus explicit invalid
fields. Confirm that rejected rows cannot partially modify existing products.

Be ready to explain how validation, planning, and application stay consistent
across modes, and the time and space complexity of an import. No particular
implementation architecture is required.
