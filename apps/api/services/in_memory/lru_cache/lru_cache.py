from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int = 5):
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self.capacity = capacity
        self.cache: OrderedDict[str, str] = OrderedDict()

    def set(self, key: str, value: str) -> str:
        if key in self.cache:
            self.cache[key] = value
            self.cache.move_to_end(key)
            return key

        if len(self.cache) >= self.capacity:
            self.cache.popitem(last=False)
        self.cache[key] = value
        return key

    def get(self, key: str) -> str:
        value = self.cache.get(key)
        if value is None:
            raise KeyError

        self.cache.move_to_end(key)
        return value
