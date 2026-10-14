import pytest

from backend.services.in_memory.catalog.catalog import (
    CatalogService,
    Product,
    ProductAlreadyExistsException,
    ProductDNEException,
    StockValueError,
)


@pytest.fixture
def service():
    return CatalogService()


@pytest.fixture
def products(service):
    service.add_product(
        "product1",
        "Shampoo",
        "Toiletries",
        1000,
        3,
    )
    service.add_product(
        "product2",
        "Soap",
        "Toiletries",
        200,
        3,
    )
    service.add_product(
        "product3",
        "Toothbrush",
        "Toiletries",
        1000,
        0,
    )
    service.add_product(
        "product4",
        "Shampoo",
        "Toiletries",
        1000,
        3,
    )
    service.add_product(
        "product5",
        "Shampoo",
        "Toiletries",
        2000,
        3,
    )
    service.add_product(
        "product6",
        "Shampoo",
        "General",
        2000,
        3,
    )


class TestAddProduct:
    def test_add_product(self, service):
        service.add_product(
            "product1",
            "Shampoo",
            "Toiletries",
            1000,
            3,
        )
        service.add_product(
            "product2",
            "Soap",
            "Toiletries",
            500,
            4,
        )
        assert service.products == {
            "product1": Product(
                id_="product1",
                name="Shampoo",
                category="Toiletries",
                price_cents=1000,
                stock=3,
            ),
            "product2": Product(
                id_="product2",
                name="Soap",
                category="Toiletries",
                price_cents=500,
                stock=4,
            ),
        }

    def test_add_product_raises_exception(self, service):
        service.add_product(
            "product1",
            "Shampoo",
            "Toiletries",
            1000,
            3,
        )
        with pytest.raises(ProductAlreadyExistsException):
            service.add_product(
                "product1",
                "Shampoo",
                "Toiletries",
                1000,
                3,
            )


class TestUpdateStock:
    def test_raises_product_dne_exception(self, service):
        with pytest.raises(ProductDNEException):
            service.update_stock("product1", 1)

    def test_raises_stock_value_error(self, service):
        service.add_product(
            "product1",
            "Shampoo",
            "Toiletries",
            1000,
            3,
        )
        with pytest.raises(StockValueError):
            service.update_stock("product1", -1)

    def test_updates_stock(self, service):
        service.add_product(
            "product1",
            "Shampoo",
            "Toiletries",
            1000,
            3,
        )
        service.update_stock("product1", 1)
        assert service.products == {
            "product1": Product(
                id_="product1",
                name="Shampoo",
                category="Toiletries",
                price_cents=1000,
                stock=1,
            )
        }


@pytest.mark.parametrize(
    "kwargs, expected_ids, total",
    [
        ({"query": "shampoo", "limit": 1}, ["product1"], 4),
        ({"query": "shampoo", "category": "General"}, ["product6"], 1),
        ({"query": "tooth", "category": "Toiletries", "in_stock_only": True}, [], 0),
        ({"query": "Toothbrush"}, ["product3"], 1),
        (
            {"query": "S"},
            ["product1", "product4", "product5", "product6", "product2", "product3"],
            6,
        ),
        (
            {"sort_by": "price_cents"},
            ["product2", "product1", "product3", "product4", "product5", "product6"],
            6,
        ),
        (
            {
                "query": "shampoo",
                "category": "Toiletries",
                "in_stock_only": True,
                "offset": 1,
                "limit": 1,
            },
            ["product4"],
            3,
        ),
        ({"limit": 0}, [], 6),
        ({"offset": 100}, [], 6),
        ({"query": "missing"}, [], 0),
        ({"category": "toiletries"}, [], 0),
    ],
)
def test_search(service, products, kwargs, expected_ids, total):
    result = service.search(**kwargs)
    assert [p.id_ for p in result.products] == expected_ids
    assert result.total == total


def test_case_insensitive_name_sort_and_id_ties(service):
    service.add_product("z", "apple", "Fruit", 0, 0)
    service.add_product("b", "APPLE", "Fruit", 1, 1)
    service.add_product("a", "Banana", "Fruit", 2, 1)
    assert [p.id_ for p in service.search().products] == ["b", "z", "a"]


def test_search_results_are_independent(service, products):
    result = service.search("shampoo")
    result.products[0].stock = -50
    result.products[0].name = "changed"
    result.products.clear()
    fresh = service.search("shampoo")
    assert fresh.total == 4
    assert fresh.products[0].stock == 3
    service.update_stock("product1", 9)
    assert fresh.products[0].stock == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1},
        {"limit": -1},
        {"offset": 1.5},
        {"limit": True},
        {"sort_by": "unknown"},
    ],
)
def test_invalid_search_arguments(service, kwargs):
    with pytest.raises(ValueError):
        service.search(**kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("product_id", ""),
        ("product_id", None),
        ("category", ""),
        ("category", None),
        ("price_cents", -1),
        ("price_cents", 1.5),
        ("price_cents", True),
        ("stock", -1),
        ("stock", 1.5),
        ("stock", True),
    ],
)
def test_invalid_product_does_not_mutate_state(service, field, value):
    args = dict(
        product_id="p", name="Product", category="General", price_cents=0, stock=0
    )
    args[field] = value
    with pytest.raises(ValueError):
        service.add_product(**args)
    assert service.products == {}


@pytest.mark.parametrize("stock", [-1, 1.5, True, "3", None])
def test_invalid_stock_update_preserves_quantity(service, products, stock):
    with pytest.raises(StockValueError):
        service.update_stock("product1", stock)
    assert service.products["product1"].stock == 3


def test_zero_values_and_case_sensitive_ids(service):
    service.add_product("p", "Product", "General", 0, 0)
    service.add_product("P", "Product", "General", 0, 1)
    service.update_stock("P", 0)
    assert service.search().total == 2
    assert service.search(in_stock_only=True).total == 0


def test_empty_catalog(service):
    result = service.search()
    assert result.products == []
    assert result.total == 0
