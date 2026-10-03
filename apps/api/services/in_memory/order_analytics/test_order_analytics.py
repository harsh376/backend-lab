from decimal import Decimal

import pytest

from apps.api.services.order_analytics.order_analytics import (
    AnalyticsReport,
    Order,
    OrderAnalyticsService,
)


@pytest.fixture
def service():
    return OrderAnalyticsService()


@pytest.fixture
def orders(service):
    service.add_order(
        Order(
            order_id="order1",
            customer_id="customer1",
            created_at=200,
            status="pending",
            gross_cents=1000,
            refunded_cents=0,
        )
    )
    service.add_order(
        Order(
            order_id="order2",
            customer_id="customer1",
            created_at=200,
            status="cancelled",
            gross_cents=1000,
            refunded_cents=0,
        )
    )
    service.add_order(
        Order(
            order_id="order3",
            customer_id="customer1",
            created_at=200,
            status="completed",
            gross_cents=1000,
            refunded_cents=0,
        )
    )


class TestReport:
    def test_no_duplicate_orders_in_adjacent_periods(self, service, orders):

        report1 = service.report(start=100, end=200)
        report2 = service.report(start=200, end=300)

        assert report1 == AnalyticsReport(
            order_count=0,
            revenue_cents=0,
            average_order_value_cents=Decimal("0"),
            orders=(),
        )

        assert report2 == AnalyticsReport(
            order_count=1,
            revenue_cents=1000,
            average_order_value_cents=Decimal("1000.00"),
            orders=(
                Order(
                    order_id="order3",
                    customer_id="customer1",
                    created_at=200,
                    status="completed",
                    gross_cents=1000,
                    refunded_cents=0,
                ),
            ),
        )

    def test_pagination(self, service, orders):
        service.add_order(
            Order(
                order_id="order4",
                customer_id="customer1",
                created_at=200,
                status="completed",
                gross_cents=2000,
                refunded_cents=0,
            )
        )

        assert service.report(start=200, end=300, offset=0, limit=1) == AnalyticsReport(
            order_count=2,
            revenue_cents=3000,
            average_order_value_cents=Decimal("1500.00"),
            orders=(
                Order(
                    order_id="order3",
                    customer_id="customer1",
                    created_at=200,
                    status="completed",
                    gross_cents=1000,
                    refunded_cents=0,
                ),
            ),
        )
