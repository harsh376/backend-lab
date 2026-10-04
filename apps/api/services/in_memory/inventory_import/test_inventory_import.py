import copy
from dataclasses import FrozenInstanceError

import pytest

from apps.api.services.in_memory.inventory_import.inventory_import import (
    InventoryImportService,
    Product,
)

ROWS = [
    {"product_id": " apple ", "name": "Green Apple", "stock": 8},
    {"product_id": "pear", "name": "Pear", "stock": 3},
    {"product_id": "plum", "name": "Plum", "stock": -1},
]


@pytest.fixture
def service():
    svc = InventoryImportService()
    svc.seed([Product("apple", "Apple", 5)])
    return svc


def counts(r):
    return (
        r.planned_created_count,
        r.planned_updated_count,
        r.applied_created_count,
        r.applied_updated_count,
        r.rejected_count,
    )


class TestStage1:
    def test_partial_applies_valid_rows(self, service):
        r = service.import_rows(ROWS)
        assert counts(r) == (1, 1, 1, 1, 1)
        assert [e.row_number for e in r.errors] == [3]
        assert service.get_product("apple") == Product("apple", "Green Apple", 8)
        assert service.get_product("pear") == Product("pear", "Pear", 3)
        assert service.get_product("plum") is None

    def test_atomic_with_errors_applies_nothing(self, service):
        r = service.import_rows(ROWS, atomic=True)
        assert counts(r) == (1, 1, 0, 0, 1)
        assert service.get_product("apple") == Product("apple", "Apple", 5)
        assert service.get_product("pear") is None

    def test_atomic_without_errors_applies_all(self, service):
        r = service.import_rows(ROWS[:2], atomic=True)
        assert counts(r) == (1, 1, 1, 1, 0)
        assert service.get_product("pear") is not None

    @pytest.mark.parametrize("atomic", [False, True])
    def test_dry_run_changes_nothing(self, service, atomic):
        r = service.import_rows(ROWS, atomic=atomic, dry_run=True)
        assert counts(r) == (1, 1, 0, 0, 1)
        assert service.list_products() == [Product("apple", "Apple", 5)]

    def test_empty_batch(self, service):
        assert counts(service.import_rows([])) == (0, 0, 0, 0, 0)

    def test_stock_replaces_and_unchanged_update_counts(self, service):
        r = service.import_rows([{"product_id": "apple", "name": "Apple", "stock": 5}])
        assert counts(r) == (0, 1, 0, 1, 0)

    @pytest.mark.parametrize("stock", [True, False, 1.0, "3", None, -1])
    def test_invalid_stock(self, service, stock):
        r = service.import_rows([{"product_id": "x", "name": "X", "stock": stock}])
        assert r.rejected_count == 1
        assert service.get_product("x") is None

    @pytest.mark.parametrize("field", ["product_id", "name", "stock"])
    def test_missing_field(self, service, field):
        row = {"product_id": "x", "name": "X", "stock": 1}
        del row[field]
        r = service.import_rows([row])
        assert r.rejected_count == 1
        assert field in r.errors[0].message

    @pytest.mark.parametrize("value", ["", "   ", None, 5])
    @pytest.mark.parametrize("field", ["product_id", "name"])
    def test_invalid_strings(self, service, field, value):
        row = {"product_id": "x", "name": "X", "stock": 1, field: value}
        assert service.import_rows([row]).rejected_count == 1

    def test_multiple_errors_one_rejected_row(self, service):
        r = service.import_rows([{"product_id": "", "name": " ", "stock": True}])
        assert r.rejected_count == 1
        assert len(r.errors) == 3
        assert {e.row_number for e in r.errors} == {1}

    def test_ids_are_trimmed_and_case_sensitive(self, service):
        r = service.import_rows(
            [
                {"product_id": " Apple ", "name": " Big ", "stock": 1},
                {"product_id": "apple", "name": "Small", "stock": 2},
            ]
        )
        assert counts(r) == (1, 1, 1, 1, 0)
        assert service.get_product("Apple") == Product("Apple", "Big", 1)
        assert service.get_product("apple").stock == 2

    def test_duplicates_reject_every_occurrence(self, service):
        r = service.import_rows(
            [
                {"product_id": "a", "name": "A", "stock": 1},
                {"product_id": " a ", "name": "A2", "stock": 2},
                {"product_id": "a", "name": "", "stock": 3},
                {"product_id": "b", "name": "B", "stock": 1},
            ]
        )
        assert counts(r) == (1, 0, 1, 0, 3)
        assert {e.row_number for e in r.errors} == {1, 2, 3}
        assert service.get_product("a") is None
        assert service.get_product("b") is not None

    def test_duplicate_of_existing_product_rejected(self, service):
        rows = [{"product_id": "apple", "name": "A", "stock": 1}] * 2
        r = service.import_rows(rows)
        assert counts(r) == (0, 0, 0, 0, 2)
        assert service.get_product("apple").stock == 5

    def test_errors_ordered_by_row_number(self, service):
        rows = [
            {"product_id": "a", "name": "A", "stock": -1},
            {"product_id": "b", "name": "B", "stock": 1},
            {"product_id": "b", "name": "B", "stock": 1},
            {"product_id": "", "name": "C", "stock": 1},
        ]
        r = service.import_rows(rows)
        numbers = [e.row_number for e in r.errors]
        assert numbers == sorted(numbers) == [1, 2, 3, 4]

    def test_extra_fields_ignored_and_input_not_mutated(self, service):
        rows = [
            {"product_id": " pear ", "name": " Pear ", "stock": 3, "color": "green"}
        ]
        before = copy.deepcopy(rows)
        r = service.import_rows(rows)
        assert r.rejected_count == 0
        assert rows == before
        assert service.get_product("pear") == Product("pear", "Pear", 3)

    def test_products_are_immutable(self, service):
        with pytest.raises(FrozenInstanceError):
            service.get_product("apple").stock = 999
        with pytest.raises(FrozenInstanceError):
            service.list_products()[0].name = "hacked"
        assert service.get_product("apple") == Product("apple", "Apple", 5)

    def test_list_products_returns_new_list(self, service):
        service.list_products().clear()
        assert service.get_product("apple") is not None

    def test_result_is_immutable(self, service):
        r = service.import_rows(ROWS)
        with pytest.raises(FrozenInstanceError):
            r.rejected_count = 0
        assert isinstance(r.errors, tuple)

    def test_non_mapping_row_rejected(self, service):
        r = service.import_rows(["nope", None])
        assert r.rejected_count == 2


class TestStage2:
    def test_omit_name_on_existing_product(self, service):
        r = service.import_rows([{"product_id": "apple", "stock": 10}])
        assert counts(r) == (0, 1, 0, 1, 0)
        assert service.get_product("apple") == Product("apple", "Apple", 10)

    def test_omit_stock_on_existing_product(self, service):
        r = service.import_rows([{"product_id": "apple", "name": "Granny Smith"}])
        assert counts(r) == (0, 1, 0, 1, 0)
        assert service.get_product("apple") == Product("apple", "Granny Smith", 5)

    def test_omit_name_and_stock_on_existing_product(self, service):
        r = service.import_rows([{"product_id": "apple"}])
        assert counts(r) == (0, 1, 0, 1, 0)
        assert service.get_product("apple") == Product("apple", "Apple", 5)

    def test_omit_name_on_new_product_rejected(self, service):
        r = service.import_rows([{"product_id": "banana", "stock": 3}])
        assert r.rejected_count == 1
        assert service.get_product("banana") is None

    def test_omit_stock_on_new_product_rejected(self, service):
        r = service.import_rows([{"product_id": "banana", "name": "Banana"}])
        assert r.rejected_count == 1
        assert service.get_product("banana") is None

    def test_omit_both_on_new_product_rejected(self, service):
        r = service.import_rows([{"product_id": "banana"}])
        assert r.rejected_count == 1
        assert service.get_product("banana") is None

    def test_explicit_none_name_invalid_on_existing(self, service):
        r = service.import_rows([{"product_id": "apple", "name": None, "stock": 10}])
        assert r.rejected_count == 1
        assert service.get_product("apple").stock == 5

    def test_explicit_none_stock_invalid_on_existing(self, service):
        r = service.import_rows([{"product_id": "apple", "name": "A", "stock": None}])
        assert r.rejected_count == 1
        assert service.get_product("apple").stock == 5

    def test_explicit_blank_name_invalid_on_existing(self, service):
        r = service.import_rows([{"product_id": "apple", "name": "  ", "stock": 10}])
        assert r.rejected_count == 1
        assert service.get_product("apple").stock == 5

    def test_patch_with_duplicate_ids_rejected(self, service):
        r = service.import_rows(
            [
                {"product_id": "apple", "stock": 10},
                {"product_id": "apple", "name": "New"},
            ]
        )
        assert r.rejected_count == 2
        assert service.get_product("apple") == Product("apple", "Apple", 5)

    def test_patch_existing_atomic_with_invalid_new(self, service):
        r = service.import_rows(
            [
                {"product_id": "apple", "stock": 99},
                {"product_id": "banana"},
            ],
            atomic=True,
        )
        assert counts(r) == (0, 1, 0, 0, 1)
        assert service.get_product("apple").stock == 5

    def test_patch_dry_run_no_state_change(self, service):
        r = service.import_rows([{"product_id": "apple", "stock": 99}], dry_run=True)
        assert counts(r) == (0, 1, 0, 0, 0)
        assert service.get_product("apple").stock == 5

    def test_patch_extra_fields_ignored(self, service):
        r = service.import_rows([{"product_id": "apple", "stock": 7, "color": "red"}])
        assert r.rejected_count == 0
        assert service.get_product("apple").stock == 7

    def test_patch_trims_product_id(self, service):
        r = service.import_rows([{"product_id": " apple ", "stock": 12}])
        assert counts(r) == (0, 1, 0, 1, 0)
        assert service.get_product("apple").stock == 12

    def test_patch_trims_name_when_provided(self, service):
        r = service.import_rows([{"product_id": "apple", "name": " Fuji "}])
        assert counts(r) == (0, 1, 0, 1, 0)
        assert service.get_product("apple").name == "Fuji"
