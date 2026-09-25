from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from apps.api.services.reservation.reservation import ReservationService, SlotFullError


def test_thread_safe():
    workers = 5
    barrier = Barrier(workers)
    service = ReservationService()
    service.create_slot(id_="slot1", start=0, end=10, capacity=1)

    def attempt():
        barrier.wait(timeout=5)
        try:
            return service.create_reservation("slot1", 5)
        except SlotFullError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(attempt) for _ in range(workers)]
        results = [future.result() for future in futures]

    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert set(service.reservations) == set(successful)
    assert service.slots["slot1"].reservations == set(successful)
