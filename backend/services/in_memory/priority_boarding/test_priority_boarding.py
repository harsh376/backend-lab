from collections import deque

import pytest

from backend.services.in_memory.priority_boarding.priority_boarding import (
    Bus,
    DuplicateBus,
    DuplicateStop,
    PriorityBoardingService,
    Stop,
)


@pytest.fixture
def service():
    return PriorityBoardingService()


def test_register_stop(service):
    assert service.register_stop("stop1") == "stop1"

    with pytest.raises(DuplicateStop):
        service.register_stop("stop1")


def test_register_bus(service):
    assert service.register_bus("bus1", 5) == "bus1"

    with pytest.raises(DuplicateBus):
        service.register_bus("bus1", capacity=6)


def test_add_passenger(service):
    service.register_stop("stop1")
    service.register_bus("bus1", capacity=2)

    service.add_passenger(
        stop_id="stop1",
        passenger_id="p1",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p2",
        priority_pass_status=False,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p3",
        priority_pass_status=False,
    )

    assert service.list_stops() == {
        "stop1": Stop(regular=deque(["p2", "p3"]), priority=deque(["p1"]))
    }
    assert service.list_buses() == {"bus1": Bus(capacity=2, passenger_ids=deque([]))}


def test_board_passenger(service):
    service.register_stop("stop1")
    service.register_bus("bus1", capacity=2)

    service.add_passenger(
        stop_id="stop1",
        passenger_id="p1",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p2",
        priority_pass_status=False,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p3",
        priority_pass_status=False,
    )

    assert service.list_stops() == {
        "stop1": Stop(regular=deque(["p2", "p3"]), priority=deque(["p1"]))
    }
    assert service.list_buses() == {"bus1": Bus(capacity=2, passenger_ids=deque([]))}

    assert service.board(
        bus_id="bus1",
        stop_id="stop1",
    ) == deque(["p1", "p2"])

    assert service.list_stops() == {
        "stop1": Stop(regular=deque(["p3"]), priority=deque([]))
    }
    assert service.list_buses() == {
        "bus1": Bus(capacity=2, passenger_ids=deque(["p1", "p2"]))
    }

    service.board(
        bus_id="bus1",
        stop_id="stop1",
    )

    assert service.list_stops() == {
        "stop1": Stop(regular=deque(["p3"]), priority=deque([]))
    }
    assert service.list_buses() == {
        "bus1": Bus(capacity=2, passenger_ids=deque(["p1", "p2"]))
    }


def test_fifo(service):
    service.register_stop("stop1")
    service.register_bus("bus1", capacity=3)

    service.add_passenger(
        stop_id="stop1",
        passenger_id="p1",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p3",
        priority_pass_status=False,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p4",
        priority_pass_status=False,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p2",
        priority_pass_status=True,
    )

    assert service.board(
        bus_id="bus1",
        stop_id="stop1",
    ) == deque(["p1", "p2", "p3"])


def test_independent_stops(service):
    service.register_stop("stop1")
    service.register_stop("stop2")
    service.register_bus("bus1", capacity=3)
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p1",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop2",
        passenger_id="p2",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop2",
        passenger_id="p3",
        priority_pass_status=True,
    )
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p4",
        priority_pass_status=False,
    )

    assert service.list_stops() == {
        "stop1": Stop(regular=deque(["p4"]), priority=deque(["p1"])),
        "stop2": Stop(regular=deque([]), priority=deque(["p2", "p3"])),
    }
    assert service.list_buses() == {"bus1": Bus(capacity=3, passenger_ids=deque([]))}

    assert service.board(
        bus_id="bus1",
        stop_id="stop1",
    ) == deque(["p1", "p4"])

    assert service.list_stops() == {
        "stop1": Stop(regular=deque([]), priority=deque([])),
        "stop2": Stop(regular=deque([]), priority=deque(["p2", "p3"])),
    }
    assert service.list_buses() == {
        "bus1": Bus(capacity=3, passenger_ids=deque(["p1", "p4"]))
    }


def test_board_full_bus(service):
    service.register_stop("stop1")
    service.register_stop("stop2")
    service.register_bus("bus1", capacity=1)
    service.add_passenger(
        stop_id="stop1",
        passenger_id="p1",
        priority_pass_status=True,
    )
    assert service.board(
        bus_id="bus1",
        stop_id="stop1",
    ) == deque(["p1"])

    assert service.board(
        bus_id="bus1",
        stop_id="stop1",
    ) == deque([])

    assert service.list_buses() == {
        "bus1": Bus(capacity=1, passenger_ids=deque(["p1"]))
    }
