"""
add_product(product_id, name, category, price_cents, stock)
update_stock(product_id, stock)
search(
    query="",
    category=None,
    in_stock_only=False,
    sort_by="name",
    offset=0,
    limit=20,
)

Product IDs are unique; prices and stock are nonnegative integers.
Search is a case-insensitive substring match on the name.
Filters combine with AND.
Supported sorting: name ascending or price ascending; ties break by product ID.
Name sorting is case-insensitive.
Filtering and sorting happen before pagination.
Return both the paginated products and the total matching count.
Negative offset or limit raises ValueError; zero limit returns no products but preserves
the total.
Returned results must not let callers accidentally mutate internal state.

product_id is a non-empty string, such as "prod_123". IDs are case-sensitive and must be
unique.
category is a non-empty string, not a fixed enum. Category filtering uses an exact,
case-sensitive match. You don’t need a separate category registry.
stock is the number of units currently available for purchase, represented by a
nonnegative integer. 0 means out of stock; in_stock_only=True includes only products
with stock > 0. update_stock replaces the quantity—it doesn’t increment it.
"""

from dataclasses import dataclass, replace
from typing import Literal

type ProductID = str
type SortType = Literal["name", "price_cents"]


@dataclass
class Product:
    id_: ProductID
    name: str
    category: str
    price_cents: int
    stock: int


@dataclass
class SearchResult:
    products: list[Product]
    total: int


class ProductAlreadyExistsException(Exception):
    pass


class ProductDNEException(Exception):
    pass


class StockValueError(ValueError):
    pass


class CatalogService:
    def __init__(self):
        self.products: dict[ProductID, Product] = {}

    def add_product(
        self,
        product_id: ProductID,
        name: str,
        category: str,
        price_cents: int,
        stock: int,
    ) -> ProductID:
        if not isinstance(product_id, str) or not product_id:
            raise ValueError("product_id must be a non-empty string")
        if not isinstance(category, str) or not category:
            raise ValueError("category must be a non-empty string")
        if type(price_cents) is not int or price_cents < 0:
            raise ValueError("price_cents must be a nonnegative integer")
        self._validate_stock(stock)
        if product_id in self.products:
            raise ProductAlreadyExistsException

        self.products[product_id] = Product(
            id_=product_id,
            name=name,
            category=category,
            price_cents=price_cents,
            stock=stock,
        )
        return product_id

    def update_stock(self, product_id: ProductID, stock: int) -> bool:
        product = self.products.get(product_id)
        if product is None:
            raise ProductDNEException

        self._validate_stock(stock)

        product.stock = stock
        return True

    @staticmethod
    def _validate_stock(stock: int) -> None:
        if type(stock) is not int or stock < 0:
            raise StockValueError("stock must be a nonnegative integer")

    def search(
        self,
        query: str = "",
        category: str | None = None,
        in_stock_only: bool = False,
        sort_by: SortType = "name",
        offset: int = 0,
        limit: int = 20,
    ) -> SearchResult:
        """Return independent product copies and the count before pagination."""
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a nonnegative integer")
        if sort_by not in ("name", "price_cents"):
            raise ValueError("sort_by must be 'name' or 'price_cents'")

        normalized_query = query.casefold()
        products = [
            product
            for product in self.products.values()
            if normalized_query in product.name.casefold()
            and (category is None or product.category == category)
            and (not in_stock_only or product.stock > 0)
        ]
        if sort_by == "name":
            products.sort(key=lambda p: (p.name.casefold(), p.id_))
        else:
            products.sort(key=lambda p: (p.price_cents, p.id_))

        return SearchResult(
            products=[replace(p) for p in products[offset : offset + limit]],
            total=len(products),
        )
