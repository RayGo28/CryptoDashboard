from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Coin, CoinCurrentData, PriceHistory
from core.services.data_sync import prepare_records_data, save_market_data, sync_market_data
from core.services.selectors import get_coins_market_overview, get_coin_detail_overview


class CoinFixturesMixin:
    def create_coin(self, gecko_id="bitcoin", name="Bitcoin", symbol="btc", is_active=True, **current):
        coin = Coin.objects.create(
            gecko_id=gecko_id,
            name=name,
            symbol=symbol,
            is_active=is_active,
            image_url="https://example.com/btc.png",
        )
        CoinCurrentData.objects.create(
            coin=coin,
            price=current.get("price", Decimal("100.50")),
            market_cap=current.get("market_cap", Decimal("1000000")),
            total_volume=current.get("total_volume", Decimal("50000")),
            price_change_percentage_24h=current.get("price_change_percentage_24h", Decimal("1.25")),
            circulating_supply=current.get("circulating_supply", Decimal("19000000")),
            ath=current.get("ath", Decimal("200")),
            atl=current.get("atl", Decimal("10")),
        )
        return coin


class PageTests(TestCase):
    def test_index_page(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)

    def test_coin_detail_page(self):
        response = self.client.get(reverse("coin-detail", kwargs={"pk": "bitcoin"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bitcoin")


class CoinApiTests(CoinFixturesMixin, TestCase):
    def setUp(self):
        self.api = APIClient()
        cache.clear()
        self.btc = self.create_coin()
        self.eth = self.create_coin(gecko_id="ethereum", name="Ethereum", symbol="eth")
        self.create_coin(gecko_id="inactive-coin", name="Inactive", symbol="zzz", is_active=False)

    def tearDown(self):
        cache.clear()

    def test_list_returns_only_active_coins(self):
        response = self.api.get("/api/coins/")
        self.assertEqual(response.status_code, 200)
        gecko_ids = [coin["gecko_id"] for coin in response.data]
        self.assertEqual(set(gecko_ids), {"bitcoin", "ethereum"})

    def test_list_search_filters_by_name_or_symbol(self):
        response = self.api.get("/api/coins/", {"search": "bit"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([coin["gecko_id"] for coin in response.data], ["bitcoin"])

        response = self.api.get("/api/coins/", {"search": "ETH"})
        self.assertEqual([coin["gecko_id"] for coin in response.data], ["ethereum"])

    def test_list_uses_cache(self):
        cache.set(
            "coin_list_cache",
            [{"gecko_id": "cached-coin", "name": "Cached", "symbol": "cc"}],
            timeout=125,
        )
        response = self.api.get("/api/coins/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["gecko_id"], "cached-coin")

    def test_retrieve_returns_detail_and_stats(self):
        PriceHistory.objects.create(coin=self.btc, price=Decimal("90"))
        PriceHistory.objects.create(coin=self.btc, price=Decimal("110"))

        response = self.api.get("/api/coins/bitcoin/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["gecko_id"], "bitcoin")
        self.assertEqual(response.data["history_records_count"], 2)
        self.assertEqual(Decimal(response.data["highest_price"]), Decimal("110"))
        self.assertEqual(len(response.data["history_data"]), 2)

    def test_retrieve_unknown_coin_returns_404(self):
        response = self.api.get("/api/coins/unknown/")
        self.assertEqual(response.status_code, 404)

    def test_global_data_fallback_when_cache_empty(self):
        response = self.api.get("/api/global/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "total_market_cap": None,
                "total_volume": None,
                "market_cap_percentage_btc": None,
                "active_coins_count": None,
            },
        )

    def test_global_data_from_cache(self):
        payload = {
            "total_market_cap": 1,
            "total_volume": 2,
            "market_cap_percentage_btc": 50,
            "active_coins_count": 2,
        }
        cache.set("global_data", payload, timeout=620)
        response = self.api.get("/api/global/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)

    def test_openapi_schema_and_docs(self):
        schema = self.api.get("/api/schema/")
        self.assertEqual(schema.status_code, 200)
        docs = self.client.get("/api/docs/")
        self.assertEqual(docs.status_code, 200)


class SelectorAndSyncTests(CoinFixturesMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.btc = self.create_coin()

    def tearDown(self):
        cache.clear()

    def test_market_overview_excludes_inactive(self):
        self.create_coin(gecko_id="dead", name="Dead", symbol="ddd", is_active=False)
        self.assertEqual(list(get_coins_market_overview().values_list("gecko_id", flat=True)), ["bitcoin"])

    def test_coin_detail_overview_attaches_history_and_stats(self):
        PriceHistory.objects.create(coin=self.btc, price=Decimal("80"))
        PriceHistory.objects.create(coin=self.btc, price=Decimal("120"))
        coin = get_coin_detail_overview("bitcoin")
        self.assertEqual(coin.stats["history_records_count"], 2)
        self.assertEqual(coin.stats["highest_price"], Decimal("120"))
        self.assertEqual(len(list(coin.history_records)), 2)

    def test_prepare_records_data_skips_unknown_and_invalid_ath(self):
        raw = [
            {
                "id": "bitcoin",
                "current_price": "101",
                "market_cap": "2000",
                "total_volume": "300",
                "price_change_percentage_24h": "1.5",
                "circulating_supply": "19000000",
                "ath": "not-a-number",
                "atl": "1",
            },
            {"id": "not-in-db", "current_price": "1"},
        ]
        records = prepare_records_data(raw, {"bitcoin": self.btc})
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["ath"])
        self.assertEqual(records[0]["atl"], Decimal("1"))

    def test_save_market_data_writes_history_and_current(self):
        records = prepare_records_data(
            [
                {
                    "id": "bitcoin",
                    "current_price": "150",
                    "market_cap": "3000",
                    "total_volume": "400",
                    "price_change_percentage_24h": "2.5",
                    "circulating_supply": "19100000",
                    "ath": "250",
                    "atl": "8",
                }
            ],
            {"bitcoin": self.btc},
        )
        save_market_data(records)
        self.assertEqual(PriceHistory.objects.filter(coin=self.btc).count(), 1)
        self.btc.current_data.refresh_from_db()
        self.assertEqual(self.btc.current_data.price, Decimal("150"))

    @patch("core.services.data_sync.fetch_market_data")
    def test_sync_market_data_with_mocked_api(self, fetch_market_data):
        fetch_market_data.return_value = [
            {
                "id": "bitcoin",
                "current_price": "111",
                "market_cap": "222",
                "total_volume": "333",
                "price_change_percentage_24h": "0.5",
                "circulating_supply": "19000000",
                "ath": "500",
                "atl": "1",
            }
        ]
        result = sync_market_data()
        self.assertIn("1 coins", result)
        self.assertEqual(PriceHistory.objects.count(), 1)
        self.assertIsNotNone(cache.get("coin_list_cache"))

    @patch("core.services.data_sync.fetch_market_data")
    def test_sync_market_data_without_active_coins(self, fetch_market_data):
        Coin.objects.all().delete()
        result = sync_market_data()
        self.assertEqual(result, "No active coins found.")
        fetch_market_data.assert_not_called()

    @patch("core.management.commands.fetch_coins.update_global_data.delay")
    @patch("core.management.commands.fetch_coins.update_market_data.delay")
    @patch("core.management.commands.fetch_coins.requests.get")
    def test_fetch_coins_command(self, requests_get, delay_market, delay_global):
        response = MagicMock()
        response.json.return_value = [
            {
                "id": "solana",
                "name": "Solana",
                "symbol": "SOL",
                "image": "https://example.com/sol.png",
                "max_supply": 1000000000,
            }
        ]
        requests_get.return_value = response

        call_command("fetch_coins", stdout=StringIO())

        coin = Coin.objects.get(gecko_id="solana")
        self.assertEqual(coin.symbol, "sol")
        delay_market.assert_called_once()
        delay_global.assert_called_once()
