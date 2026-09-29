from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, replace

type PassengerID = str
type StopID = str
type BusID = str


@dataclass(frozen=True)
class Passenger:
    id_: PassengerID
    priority_pass_status: bool


@dataclass(frozen=True)
class Stop:
    regular: deque[PassengerID] = field(default_factory=deque)
    priority: deque[PassengerID] = field(default_factory=deque)


@dataclass(frozen=True)
class Bus:
    capacity: int
    passenger_ids: deque[PassengerID] = field(default_factory=deque)


class InvalidString(Exception):
    pass


class BusDoesNotExist(Exception):
    pass


class StopDoesNotExist(Exception):
    pass


class DuplicateStop(Exception):
    pass


class InvalidNonNegativeNumber(Exception):
    pass


class DuplicateBus(Exception):
    pass


class NotBooleanValue(Exception):
    pass


class PassengerAlreadyInQueue(Exception):
    pass


class PassengerAlreadyBoarded(Exception):
    pass


class PriorityBoardingService:
    def __init__(self):
        self.stops: dict[StopID, Stop] = {}
        self.buses: dict[BusID, Bus] = {}

    def _validate_string(self, value):
        if not isinstance(value, str) or value.isspace() or value == "":
            raise InvalidString
        return value

    def _validate_bool(self, value):
        if not isinstance(value, bool):
            raise NotBooleanValue

    def _validate_non_negative(self, value):
        if type(value) is int and value >= 0:
            return
        raise InvalidNonNegativeNumber

    def register_stop(self, stop_id: StopID) -> StopID:
        self._validate_string(stop_id)

        if stop_id in self.stops:
            raise DuplicateStop

        self.stops[stop_id] = Stop()
        return stop_id

    def register_bus(self, bus_id: BusID, capacity: int):
        self._validate_string(bus_id)
        self._validate_non_negative(capacity)

        if bus_id in self.buses:
            raise DuplicateBus

        self.buses[bus_id] = Bus(capacity=capacity)
        return bus_id

    def add_passenger(
        self, stop_id: StopID, passenger_id: PassengerID, priority_pass_status: bool
    ):
        self._validate_string(stop_id)
        self._validate_string(passenger_id)
        self._validate_bool(priority_pass_status)

        stop = self.stops.get(stop_id)
        if stop is None:
            raise StopDoesNotExist

        for _, s in self.stops.items():
            if passenger_id in s.priority or passenger_id in s.regular:
                raise PassengerAlreadyInQueue

        for _, b in self.buses.items():
            if passenger_id in b.passenger_ids:
                raise PassengerAlreadyBoarded

        if priority_pass_status:
            priority = self.stops[stop_id].priority
            if passenger_id in priority:
                return

            priority.append(passenger_id)
            self.stops[stop_id] = replace(stop, priority=priority)
            return

        regular = self.stops[stop_id].regular
        if passenger_id in regular:
            return

        regular.append(passenger_id)
        self.stops[stop_id] = replace(stop, regular=regular)

    def board(self, bus_id: BusID, stop_id: StopID):
        self._validate_string(bus_id)
        self._validate_string(stop_id)

        bus = self.buses.get(bus_id)
        if bus is None:
            raise BusDoesNotExist

        stop = self.stops.get(stop_id)
        if stop is None:
            raise StopDoesNotExist

        capacity = bus.capacity
        onboard = len(bus.passenger_ids)

        boarded: deque[PassengerID] = deque()
        while capacity - onboard > 0 and (stop.priority or stop.regular):
            if stop.priority:
                passenger_id = stop.priority.popleft()
                boarded.append(passenger_id)
                onboard += 1
            elif stop.regular:
                passenger_id = stop.regular.popleft()
                boarded.append(passenger_id)
                onboard += 1

        consolidated = bus.passenger_ids + boarded
        self.buses[bus_id] = replace(bus, passenger_ids=consolidated)
        return boarded

    def list_stops(self) -> dict[StopID, Stop]:
        return deepcopy(self.stops)

    def list_buses(self) -> dict[BusID, Bus]:
        return deepcopy(self.buses)
