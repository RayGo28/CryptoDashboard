from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from core.models import Coin, CoinCurrentData, PriceHistory
from watcher.tasks import cleanup_old_data, update_global_data, update_market_data


class WatcherTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.coin = Coin.objects.create(
            gecko_id="bitcoin",
            name="Bitcoin",
            symbol="btc",
            is_active=True,
        )
        CoinCurrentData.objects.create(coin=self.coin, price=Decimal("100"))

    def tearDown(self):
        cache.clear()

    def test_cleanup_old_data_deletes_records_older_than_30_days(self):
        old = PriceHistory.objects.create(
            coin=self.coin,
            price=Decimal("90"),
            timestamp=timezone.now() - timedelta(days=31),
        )
        recent = PriceHistory.objects.create(
            coin=self.coin,
            price=Decimal("110"),
            timestamp=timezone.now() - timedelta(days=1),
        )

        result = cleanup_old_data.apply().result
        self.assertIn("1", result)
        self.assertFalse(PriceHistory.objects.filter(pk=old.pk).exists())
        self.assertTrue(PriceHistory.objects.filter(pk=recent.pk).exists())

    @patch("watcher.tasks.sync_market_data")
    def test_update_market_data_calls_sync(self, sync_market_data):
        update_market_data.apply()
        sync_market_data.assert_called_once()

    @patch("watcher.tasks.sync_global_data")
    def test_update_global_data_calls_sync(self, sync_global_data):
        update_global_data.apply()
        sync_global_data.assert_called_once()

    @patch("core.services.data_sync.fetch_global_data")
    def test_update_global_data_stores_cache(self, fetch_global_data):
        fetch_global_data.return_value = {
            "total_market_cap": {"usd": 1000},
            "total_volume": {"usd": 200},
            "market_cap_percentage": {"btc": 51.2},
            "market_cap_change_percentage_24h_usd": 1.1,
            "volume_change_percentage_24h_usd": 2.2,
        }
        update_global_data.apply()
        cached = cache.get("global_data")
        self.assertEqual(cached["total_market_cap"], 1000)
        self.assertEqual(cached["active_coins_count"], 1)
