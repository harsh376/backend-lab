import pytest

from apps.api.services.lru_cache.lru_cache import LRUCache


@pytest.mark.parametrize("capacity", [0, -1])
def test_init_rejects_non_positive_capacity(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity=capacity)


def test_set_returns_key():
    service = LRUCache(capacity=2)

    assert service.set(key="joe", value="1") == "joe"


def test_get():
    service = LRUCache(capacity=2)
    service.set(key="joe", value="1")
    service.set(key="jack", value="2")

    assert service.get(key="joe") == "1"
    assert service.get(key="jack") == "2"


def test_get_raises_key_error():
    service = LRUCache(capacity=2)

    with pytest.raises(KeyError):
        service.get(key="joe")


def test_set_evicts_least_recently_used():
    service = LRUCache(capacity=2)
    service.set(key="joe", value="1")
    service.set(key="jack", value="2")
    service.set(key="jill", value="3")

    with pytest.raises(KeyError):
        service.get(key="joe")
    assert service.get(key="jack") == "2"
    assert service.get(key="jill") == "3"


def test_get_refreshes_recency():
    service = LRUCache(capacity=2)
    service.set(key="joe", value="1")
    service.set(key="jack", value="2")

    # joe becomes most recently used, so jack is evicted next
    service.get(key="joe")
    service.set(key="jill", value="3")

    assert service.get(key="joe") == "1"
    with pytest.raises(KeyError):
        service.get(key="jack")


def test_set_existing_key_updates_value_and_recency():
    service = LRUCache(capacity=2)
    service.set(key="joe", value="1")
    service.set(key="jack", value="2")

    # Updating joe makes it most recently used without evicting anything
    service.set(key="joe", value="10")
    service.set(key="jill", value="3")

    assert service.get(key="joe") == "10"
    assert service.get(key="jill") == "3"
    with pytest.raises(KeyError):
        service.get(key="jack")


def test_capacity_one():
    service = LRUCache(capacity=1)
    service.set(key="joe", value="1")
    service.set(key="jack", value="2")

    with pytest.raises(KeyError):
        service.get(key="joe")
    assert service.get(key="jack") == "2"
