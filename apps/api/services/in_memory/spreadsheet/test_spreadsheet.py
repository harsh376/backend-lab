import pytest

from apps.api.services.in_memory.spreadsheet.spreadsheet import (
    CellNotFoundException,
    CycleFoundException,
    SpreadsheetService,
)


@pytest.fixture
def service():
    return SpreadsheetService()


def test_set_cell(service):
    assert service.set_cell("A1", "2") == "A1"
    assert service.set_cell("B1", "2 + 4") == "B1"
    assert service.set_cell("C1", "A1 + B1") == "C1"


def test_set_cell_raises_error(service):
    with pytest.raises(CellNotFoundException):
        service.set_cell("C1", "A1 + B1")


def test_set_cell_raises_cycle_found_exception(service):
    assert service.set_cell("A1", "2") == "A1"
    assert service.set_cell("B1", "2 + A1") == "B1"
    assert service.set_cell("C1", "A1 + B1") == "C1"

    with pytest.raises(CycleFoundException):
        service.set_cell("B1", "C1")


def test_get_cell(service):
    service.set_cell("A1", "2")
    service.set_cell("B1", "2 + 4")
    service.set_cell("C1", "A1 + B1")

    assert service.get_cell("A1") == 2
    assert service.get_cell("B1") == 6
    assert service.get_cell("C1") == 8


def test_get_cell_negated_reference(service):
    service.set_cell("A1", "5")
    service.set_cell("B1", "10 - A1")
    service.set_cell("C1", "-A1")

    assert service.get_cell("B1") == 5
    assert service.get_cell("C1") == -5


def test_get_cell_shared_dependency(service):
    service.set_cell("A1", "1")
    service.set_cell("B1", "A1 + 1")
    service.set_cell("C1", "A1 + 2")
    service.set_cell("D1", "B1 + C1")

    assert service.get_cell("D1") == 5


def test_get_cell_long_chain(service):
    service.set_cell("Z0", "1")
    for i in range(1, 5000):
        service.set_cell(f"Z{i}", f"Z{i - 1} + 1")

    assert service.get_cell("Z4999") == 5000
