from dataclasses import FrozenInstanceError

import pytest

from apps.api.services.inventory.inventory import InventoryService


@pytest.fixture
def service() -> InventoryService:
    service = InventoryService()
    service.receive_stock("apple", 5)
    service.receive_stock("pear", 2)
    return service


def stock_tuple(service: InventoryService, product_id: str) -> tuple[int, int, int]:
    stock = service.get_stock(product_id)
    assert stock is not None
    return stock.on_hand, stock.reserved, stock.available


def assert_reserved_matches_active_reservations(service: InventoryService) -> None:
    expected: dict[str, int] = {product_id: 0 for product_id in service.stock}
    for reservation in service.reservations.values():
        if reservation.status == "ACTIVE":
            for product_id, quantity in reservation.items.items():
                expected[product_id] += quantity
    actual = {product_id: s.reserved for product_id, s in service.stock.items()}
    assert actual == expected


class TestReceiveStock:
    def test_creates_unknown_product(self):
        service = InventoryService()

        stock = service.receive_stock("apple", 5)

        assert (stock.id_, stock.on_hand, stock.reserved, stock.available) == (
            "apple",
            5,
            0,
            5,
        )

    def test_adds_to_existing_product_and_is_not_idempotent(self, service):
        service.receive_stock("apple", 3)
        service.receive_stock("apple", 3)

        assert stock_tuple(service, "apple") == (11, 0, 11)

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_rejects_non_positive_quantity(self, service, quantity):
        with pytest.raises(Exception, match="Quantity must be positive"):
            service.receive_stock("apple", quantity)

        assert stock_tuple(service, "apple") == (5, 0, 5)

    def test_rejected_receive_does_not_create_product(self):
        service = InventoryService()

        with pytest.raises(Exception, match="Quantity must be positive"):
            service.receive_stock("apple", 0)

        assert service.get_stock("apple") is None

    def test_returns_immutable_stock(self, service):
        snapshot = service.receive_stock("apple", 1)
        with pytest.raises(FrozenInstanceError):
            snapshot.on_hand = 999

        assert stock_tuple(service, "apple") == (6, 0, 6)


class TestGetStock:
    def test_unknown_product_returns_none_without_creating_it(self, service):
        assert service.get_stock("banana") is None
        assert "banana" not in service.stock

    def test_returns_immutable_stock(self, service):
        snapshot = service.get_stock("apple")
        with pytest.raises(FrozenInstanceError):
            snapshot.on_hand = 999
        with pytest.raises(FrozenInstanceError):
            snapshot.reserved = 999

        assert stock_tuple(service, "apple") == (5, 0, 5)


class TestReserve:
    def test_reserves_stock_without_changing_on_hand(self, service):
        reservation = service.reserve({"apple": 3, "pear": 2}, "cart-1")

        assert reservation.status == "ACTIVE"
        assert reservation.request_id == "cart-1"
        assert reservation.items == {"apple": 3, "pear": 2}
        assert stock_tuple(service, "apple") == (5, 3, 2)
        assert stock_tuple(service, "pear") == (2, 2, 0)

    def test_exact_capacity(self, service):
        service.reserve({"apple": 5}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 5, 0)

    def test_one_over_capacity_fails(self, service):
        with pytest.raises(Exception, match="Quantity not available: apple:6"):
            service.reserve({"apple": 6}, "cart-1")

    def test_reservation_ids_are_unique(self, service):
        first = service.reserve({"apple": 1}, "cart-1")
        second = service.reserve({"apple": 1}, "cart-2")

        assert first.id_ != second.id_

    def test_reservations_compete_for_availability(self, service):
        service.reserve({"apple": 3}, "cart-1")

        with pytest.raises(Exception, match="Quantity not available"):
            service.reserve({"apple": 3}, "cart-2")

        service.reserve({"apple": 2}, "cart-3")
        assert stock_tuple(service, "apple") == (5, 5, 0)

    def test_empty_cart_fails(self, service):
        with pytest.raises(Exception, match="Empty items"):
            service.reserve({}, "cart-1")

    def test_unknown_product_fails(self, service):
        with pytest.raises(Exception, match="Invalid product_id: banana"):
            service.reserve({"banana": 1}, "cart-1")

    @pytest.mark.parametrize("quantity", [0, -2])
    def test_non_positive_quantity_fails(self, service, quantity):
        with pytest.raises(Exception, match="Quantity must be positive"):
            service.reserve({"apple": quantity}, "cart-1")

    def test_reserve_does_not_create_unknown_product(self, service):
        with pytest.raises(Exception, match="Invalid product_id"):
            service.reserve({"banana": 1}, "cart-1")

        assert "banana" not in service.stock


class TestReserveAtomicity:
    def test_partial_shortage_reserves_nothing(self, service):
        with pytest.raises(Exception, match="Quantity not available: pear:3"):
            service.reserve({"apple": 3, "pear": 3}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 0, 5)
        assert stock_tuple(service, "pear") == (2, 0, 2)
        assert service.reservations == {}

    def test_unknown_product_after_valid_one_reserves_nothing(self, service):
        with pytest.raises(Exception, match="Invalid product_id: banana"):
            service.reserve({"apple": 1, "banana": 1}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 0, 5)
        assert service.reservations == {}

    def test_invalid_quantity_after_valid_one_reserves_nothing(self, service):
        with pytest.raises(Exception, match="Quantity must be positive"):
            service.reserve({"apple": 1, "pear": 0}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 0, 5)
        assert service.reservations == {}

    def test_failed_reserve_does_not_consume_request_id(self, service):
        with pytest.raises(Exception, match="Quantity not available"):
            service.reserve({"apple": 1, "pear": 3}, "cart-1")

        assert "cart-1" not in service.requests

    def test_failed_reserve_does_not_consume_a_reservation_id(self, service):
        with pytest.raises(Exception, match="Quantity not available"):
            service.reserve({"apple": 6}, "cart-1")

        reservation = service.reserve({"apple": 1}, "cart-2")

        assert reservation.id_ == 0


class TestCommit:
    def test_commit_decreases_on_hand_and_reserved(self, service):
        reservation = service.reserve({"apple": 3, "pear": 2}, "cart-1")

        committed = service.commit(reservation.id_, "purchase-1")

        assert committed.status == "COMMITTED"
        assert stock_tuple(service, "apple") == (2, 0, 2)
        assert stock_tuple(service, "pear") == (0, 0, 0)

    def test_commit_with_new_request_id_is_a_noop(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.commit(reservation.id_, "purchase-1")

        again = service.commit(reservation.id_, "purchase-2")

        assert again.status == "COMMITTED"
        assert stock_tuple(service, "apple") == (2, 0, 2)

    def test_commit_released_reservation_fails(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.release(reservation.id_, "release-1")

        with pytest.raises(Exception, match="Reservation has been released"):
            service.commit(reservation.id_, "purchase-1")

        assert stock_tuple(service, "apple") == (5, 0, 5)
        assert service.get_reservation(reservation.id_).status == "RELEASED"

    def test_commit_unknown_reservation_fails(self, service):
        with pytest.raises(Exception, match="Invalid reservation_id"):
            service.commit(123, "purchase-1")

    def test_failed_commit_does_not_consume_request_id(self, service):
        with pytest.raises(Exception, match="Invalid reservation_id"):
            service.commit(123, "purchase-1")

        assert "purchase-1" not in service.requests

    def test_failed_commit_request_id_can_be_reused(self, service):
        with pytest.raises(Exception, match="Invalid reservation_id"):
            service.commit(123, "purchase-1")
        reservation = service.reserve({"apple": 2}, "cart-1")

        committed = service.commit(reservation.id_, "purchase-1")

        assert committed.status == "COMMITTED"

    def test_commit_frees_availability_of_other_stock_correctly(self, service):
        first = service.reserve({"apple": 2}, "cart-1")
        service.reserve({"apple": 3}, "cart-2")

        service.commit(first.id_, "purchase-1")

        assert stock_tuple(service, "apple") == (3, 3, 0)


class TestRelease:
    def test_release_decreases_reserved_only(self, service):
        reservation = service.reserve({"apple": 3, "pear": 2}, "cart-1")

        released = service.release(reservation.id_, "release-1")

        assert released.status == "RELEASED"
        assert stock_tuple(service, "apple") == (5, 0, 5)
        assert stock_tuple(service, "pear") == (2, 0, 2)

    def test_release_with_new_request_id_is_a_noop(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.release(reservation.id_, "release-1")

        again = service.release(reservation.id_, "release-2")

        assert again.status == "RELEASED"
        assert stock_tuple(service, "apple") == (5, 0, 5)

    def test_release_committed_reservation_fails(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.commit(reservation.id_, "purchase-1")

        with pytest.raises(Exception, match="already been committed"):
            service.release(reservation.id_, "release-1")

        assert stock_tuple(service, "apple") == (2, 0, 2)
        assert service.get_reservation(reservation.id_).status == "COMMITTED"

    def test_release_unknown_reservation_fails(self, service):
        with pytest.raises(Exception, match="Reservation doesn't exist"):
            service.release(123, "release-1")

    def test_failed_release_does_not_consume_request_id(self, service):
        with pytest.raises(Exception, match="Reservation doesn't exist"):
            service.release(123, "release-1")

        assert "release-1" not in service.requests

    def test_released_stock_can_be_reserved_again(self, service):
        reservation = service.reserve({"apple": 5}, "cart-1")
        service.release(reservation.id_, "release-1")

        service.reserve({"apple": 5}, "cart-2")

        assert stock_tuple(service, "apple") == (5, 5, 0)


class TestGetReservation:
    def test_returns_current_state(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.commit(reservation.id_, "purchase-1")

        current = service.get_reservation(reservation.id_)

        assert current.status == "COMMITTED"
        assert current.items == {"apple": 3}

    def test_terminal_reservations_remain_queryable(self, service):
        committed = service.reserve({"apple": 1}, "cart-1")
        released = service.reserve({"apple": 1}, "cart-2")
        service.commit(committed.id_, "purchase-1")
        service.release(released.id_, "release-1")

        assert service.get_reservation(committed.id_).status == "COMMITTED"
        assert service.get_reservation(released.id_).status == "RELEASED"

    def test_unknown_reservation_fails(self, service):
        with pytest.raises(Exception, match="Reservation doesn't exist"):
            service.get_reservation(123)

        assert service.reservations == {}


class TestIdempotentRetries:
    def test_reserve_retry_returns_original_response(self, service):
        first = service.reserve({"apple": 3, "pear": 2}, "cart-1")

        retry = service.reserve({"pear": 2, "apple": 3}, "cart-1")

        assert retry == first
        assert len(service.reservations) == 1
        assert stock_tuple(service, "apple") == (5, 3, 2)
        assert stock_tuple(service, "pear") == (2, 2, 0)

    def test_commit_retry_returns_original_response(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        first = service.commit(reservation.id_, "purchase-1")

        retry = service.commit(reservation.id_, "purchase-1")

        assert retry == first
        assert stock_tuple(service, "apple") == (2, 0, 2)

    def test_release_retry_returns_original_response(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        first = service.release(reservation.id_, "release-1")

        retry = service.release(reservation.id_, "release-1")

        assert retry == first
        assert stock_tuple(service, "apple") == (5, 0, 5)

    def test_reserve_replay_is_resolved_before_current_state(self, service):
        original = service.reserve({"apple": 3}, "cart-1")
        service.commit(original.id_, "purchase-1")

        replay = service.reserve({"apple": 3}, "cart-1")

        assert replay.status == "ACTIVE"
        assert service.get_reservation(original.id_).status == "COMMITTED"
        assert stock_tuple(service, "apple") == (2, 0, 2)

    def test_commit_replay_ignores_later_state_changes(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        first = service.commit(reservation.id_, "purchase-1")
        service.receive_stock("apple", 10)

        assert service.commit(reservation.id_, "purchase-1") == first

    def test_replayed_noop_commit_keeps_its_own_response(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.commit(reservation.id_, "purchase-1")
        noop = service.commit(reservation.id_, "purchase-2")

        assert service.commit(reservation.id_, "purchase-2") == noop

    def test_noop_commit_claims_its_request_id(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        service.commit(reservation.id_, "purchase-1")
        service.commit(reservation.id_, "purchase-2")

        with pytest.raises(Exception, match="not a `reserve` operation"):
            service.reserve({"apple": 1}, "purchase-2")

    @pytest.mark.parametrize(
        ("first_call", "second_call", "operation"),
        [
            ("reserve", "commit", "commit"),
            ("reserve", "release", "release"),
            ("commit", "reserve", "reserve"),
            ("commit", "release", "release"),
            ("release", "reserve", "reserve"),
            ("release", "commit", "commit"),
        ],
    )
    def test_request_id_reused_across_operations_fails(
        self, service, first_call, second_call, operation
    ):
        held = service.reserve({"apple": 1}, "setup")

        def call(name: str):
            if name == "reserve":
                return service.reserve({"apple": 1}, "shared")
            return getattr(service, name)(held.id_, "shared")

        call(first_call)
        before = stock_tuple(service, "apple")

        with pytest.raises(Exception, match=f"not a `{operation}` operation"):
            call(second_call)

        assert stock_tuple(service, "apple") == before

    def test_failed_reserve_can_succeed_after_restocking(self, service):
        with pytest.raises(Exception, match="Quantity not available: pear:3"):
            service.reserve({"apple": 1, "pear": 3}, "cart-1")

        service.receive_stock("pear", 1)
        reservation = service.reserve({"apple": 1, "pear": 3}, "cart-1")

        assert reservation.status == "ACTIVE"
        assert stock_tuple(service, "pear") == (3, 3, 0)

    def test_failed_reserve_id_can_be_reused_with_different_payload(self, service):
        with pytest.raises(Exception, match="Quantity not available"):
            service.reserve({"apple": 6}, "cart-1")

        reservation = service.reserve({"pear": 1}, "cart-1")

        assert reservation.items == {"pear": 1}

    def test_reserve_with_different_payload_conflicts(self, service):
        service.reserve({"apple": 3, "pear": 2}, "cart-1")

        with pytest.raises(Exception, match="(?i)idempotenc|conflict|different"):
            service.reserve({"apple": 1}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 3, 2)

    def test_commit_with_different_reservation_conflicts(self, service):
        first = service.reserve({"apple": 1}, "cart-1")
        second = service.reserve({"apple": 1}, "cart-2")
        service.commit(first.id_, "purchase-1")

        with pytest.raises(Exception, match="(?i)idempotenc|conflict|different"):
            service.commit(second.id_, "purchase-1")

        assert service.get_reservation(second.id_).status == "ACTIVE"


class TestSnapshotIsolation:
    def test_mutating_reserve_input_does_not_affect_reservation(self, service):
        items = {"apple": 3}
        reservation = service.reserve(items, "cart-1")

        items["apple"] = 1
        items["pear"] = 2

        assert service.get_reservation(reservation.id_).items == {"apple": 3}

    def test_earlier_responses_keep_their_status_after_transitions(self, service):
        reserved = service.reserve({"apple": 3}, "cart-1")
        service.commit(reserved.id_, "purchase-1")

        assert reserved.status == "ACTIVE"
        assert service.reserve({"apple": 3}, "cart-1").status == "ACTIVE"

    def test_reserve_response_is_immutable(self, service):
        response = service.reserve({"apple": 3}, "cart-1")

        with pytest.raises(TypeError):
            response.items["apple"] = 99
        with pytest.raises(FrozenInstanceError):
            response.status = "RELEASED"

        assert service.get_reservation(response.id_).items == {"apple": 3}
        assert service.get_reservation(response.id_).status == "ACTIVE"
        replay = service.reserve({"apple": 3}, "cart-1")
        assert replay.items == {"apple": 3}
        assert replay.status == "ACTIVE"

    def test_replayed_response_is_immutable(self, service):
        service.reserve({"apple": 3}, "cart-1")
        replay = service.reserve({"apple": 3}, "cart-1")

        with pytest.raises(TypeError):
            replay.items["apple"] = 99
        with pytest.raises(FrozenInstanceError):
            replay.status = "COMMITTED"

        again = service.reserve({"apple": 3}, "cart-1")
        assert again.items == {"apple": 3}
        assert again.status == "ACTIVE"

    def test_get_reservation_result_is_immutable(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")

        snapshot = service.get_reservation(reservation.id_)
        with pytest.raises(TypeError):
            snapshot.items["apple"] = 99
        with pytest.raises(FrozenInstanceError):
            snapshot.status = "COMMITTED"

        assert service.get_reservation(reservation.id_).items == {"apple": 3}
        assert service.get_reservation(reservation.id_).status == "ACTIVE"

    def test_commit_response_is_immutable(self, service):
        reservation = service.reserve({"apple": 3}, "cart-1")
        response = service.commit(reservation.id_, "purchase-1")

        with pytest.raises(FrozenInstanceError):
            response.status = "RELEASED"

        assert service.commit(reservation.id_, "purchase-1").status == "COMMITTED"
        assert service.get_reservation(reservation.id_).status == "COMMITTED"


class TestInputValidation:
    def test_boolean_quantity_is_rejected_on_receive(self):
        service = InventoryService()

        with pytest.raises(Exception):  # noqa: B017
            service.receive_stock("apple", True)

    def test_boolean_quantity_is_rejected_on_reserve(self, service):
        with pytest.raises(Exception):  # noqa: B017
            service.reserve({"apple": True}, "cart-1")

        assert stock_tuple(service, "apple") == (5, 0, 5)

    def test_empty_product_id_is_rejected(self):
        service = InventoryService()

        with pytest.raises(Exception):  # noqa: B017
            service.receive_stock("", 1)

    def test_empty_request_id_is_rejected(self, service):
        with pytest.raises(Exception):  # noqa: B017
            service.reserve({"apple": 1}, "")

    def test_ids_are_case_sensitive_and_not_trimmed(self):
        service = InventoryService()
        service.receive_stock("Apple", 1)
        service.receive_stock("apple ", 2)

        assert stock_tuple(service, "Apple") == (1, 0, 1)
        assert stock_tuple(service, "apple ") == (2, 0, 2)
        assert service.get_stock("apple") is None


class TestInvariants:
    def test_reserved_equals_sum_of_active_reservations(self, service):
        first = service.reserve({"apple": 2, "pear": 1}, "cart-1")
        second = service.reserve({"apple": 3, "pear": 1}, "cart-2")
        assert_reserved_matches_active_reservations(service)

        with pytest.raises(Exception, match="Quantity not available"):
            service.reserve({"apple": 1}, "cart-3")
        assert_reserved_matches_active_reservations(service)

        service.commit(first.id_, "purchase-1")
        assert_reserved_matches_active_reservations(service)

        service.release(second.id_, "release-1")
        assert_reserved_matches_active_reservations(service)

        service.commit(first.id_, "purchase-2")
        service.release(second.id_, "release-2")
        assert_reserved_matches_active_reservations(service)

    def test_quantities_never_go_negative(self, service):
        first = service.reserve({"apple": 5, "pear": 2}, "cart-1")
        service.commit(first.id_, "purchase-1")

        for stock in service.stock.values():
            assert stock.on_hand >= 0
            assert stock.reserved >= 0
            assert stock.available >= 0


def test_worked_example_from_readme():
    service = InventoryService()
    service.receive_stock("apple", 5)
    service.receive_stock("pear", 2)

    reservation = service.reserve({"apple": 3, "pear": 2}, "cart-1")
    assert stock_tuple(service, "apple") == (5, 3, 2)
    assert stock_tuple(service, "pear") == (2, 2, 0)

    assert service.reserve({"pear": 2, "apple": 3}, "cart-1") == reservation
    assert stock_tuple(service, "apple") == (5, 3, 2)

    with pytest.raises(Exception, match="Quantity not available"):
        service.reserve({"apple": 1, "pear": 1}, "cart-2")
    assert stock_tuple(service, "apple") == (5, 3, 2)
    assert stock_tuple(service, "pear") == (2, 2, 0)

    committed = service.commit(reservation.id_, "purchase-1")
    assert stock_tuple(service, "apple") == (2, 0, 2)
    assert stock_tuple(service, "pear") == (0, 0, 0)

    assert service.commit(reservation.id_, "purchase-1") == committed
    service.commit(reservation.id_, "purchase-3")
    assert stock_tuple(service, "apple") == (2, 0, 2)

    with pytest.raises(Exception, match="already been committed"):
        service.release(reservation.id_, "release-1")

    service.receive_stock("pear", 1)
    assert service.reserve({"apple": 1, "pear": 1}, "cart-2").status == "ACTIVE"
