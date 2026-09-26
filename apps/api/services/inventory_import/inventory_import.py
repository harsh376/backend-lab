from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    stock: int


class Row(TypedDict):
    product_id: str
    name: str
    stock: int


@dataclass(frozen=True)
class RowError:
    row_number: int  # one-based
    message: str


@dataclass(frozen=True)
class ImportResult:
    errors: tuple[RowError, ...]
    rejected_count: int
    planned_created_count: int
    planned_updated_count: int
    applied_created_count: int
    applied_updated_count: int


class InventoryImportService:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def seed(self, products: Iterable[Product]) -> None:
        for product in products:
            self._products[product.product_id] = product

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def import_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        atomic: bool = False,
        dry_run: bool = False,
    ) -> ImportResult:
        rows = list(rows)

        # Validate: each row is normalized or gets errors. Never touches state.
        normalized: dict[int, Product] = {}
        ids: dict[
            int, str
        ] = {}  # valid IDs, including on rows invalid for other reasons
        errors: dict[int, list[str]] = {}
        for number, row in enumerate(rows, start=1):
            product_id, product, row_errors = self._validate(row, self._products)
            if product_id:
                ids[number] = product_id
            if product:
                normalized[number] = product
            if row_errors:
                errors[number] = row_errors

        # Reject every occurrence of a valid normalized ID that repeats.
        counts = Counter(ids.values())
        for number, product_id in ids.items():
            if counts[product_id] > 1:
                normalized.pop(number, None)
                errors.setdefault(number, []).append(
                    f"duplicate product_id {product_id!r} in batch"
                )

        # Plan against the state at the start of the call.
        to_create = [
            p for p in normalized.values() if p.product_id not in self._products
        ]
        to_update = [p for p in normalized.values() if p.product_id in self._products]

        applied_created = applied_updated = 0
        if not dry_run and not (atomic and errors):
            for product in to_create + to_update:
                self._products[product.product_id] = product
            applied_created, applied_updated = len(to_create), len(to_update)

        return ImportResult(
            errors=tuple(
                RowError(number, message)
                for number in sorted(errors)
                for message in errors[number]
            ),
            rejected_count=len(errors),
            planned_created_count=len(to_create),
            planned_updated_count=len(to_update),
            applied_created_count=applied_created,
            applied_updated_count=applied_updated,
        )

    @staticmethod
    def _validate(
        row: Any, existing: dict[str, Product]
    ) -> tuple[str | None, Product | None, list[str]]:
        """Return (valid normalized ID or None,
        normalized product if fully valid, errors)."""
        if not isinstance(row, Mapping):
            return None, None, ["row must be a mapping"]

        errors: list[str] = []
        values: dict[str, Any] = {}

        if "product_id" not in row:
            errors.append("product_id is required")
        elif not isinstance(row["product_id"], str) or not row["product_id"].strip():
            errors.append("product_id must be a nonempty string")
        else:
            values["product_id"] = row["product_id"].strip()

        current = existing.get(values["product_id"]) if "product_id" in values else None

        if "name" not in row:
            if current:
                values["name"] = current.name
            else:
                errors.append("name is required")
        elif not isinstance(row["name"], str) or not row["name"].strip():
            errors.append("name must be a nonempty string")
        else:
            values["name"] = row["name"].strip()

        if "stock" not in row:
            if current:
                values["stock"] = current.stock
            else:
                errors.append("stock is required")
        elif type(row["stock"]) is not int or row["stock"] < 0:
            errors.append("stock must be a nonnegative integer")
        else:
            values["stock"] = row["stock"]

        product = None if errors else Product(**values)
        return values.get("product_id"), product, errors
