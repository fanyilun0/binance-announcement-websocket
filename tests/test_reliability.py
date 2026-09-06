import tempfile
import unittest
from pathlib import Path

from announcement_store import AnnouncementStore
from main import BinanceAnnouncementMonitor


class AnnouncementIdentityTests(unittest.TestCase):
    def test_same_catalog_different_articles_have_different_ids(self):
        first = {"catalogId": 48, "publishDate": 1000, "title": "First listing"}
        second = {"catalogId": 48, "publishDate": 2000, "title": "Second listing"}

        first_id = BinanceAnnouncementMonitor.announcement_id(first, first)
        second_id = BinanceAnnouncementMonitor.announcement_id(second, second)

        self.assertNotEqual(first_id, second_id)

    def test_native_article_id_is_preferred(self):
        raw = {"id": 12345, "catalogId": 48, "publishDate": 1000, "title": "Listing"}
        self.assertEqual("binance:12345", BinanceAnnouncementMonitor.announcement_id(raw, raw))


class DurableOutboxTests(unittest.TestCase):
    def test_item_is_deduplicated_across_process_restarts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = str(Path(temporary_directory) / "announcements.sqlite3")
            announcement = {"title": "Listing", "catalogId": 48}

            first_store = AnnouncementStore(database)
            self.assertTrue(first_store.add("article-1", announcement))
            first_store.close()

            second_store = AnnouncementStore(database)
            self.assertFalse(second_store.add("article-1", announcement))
            self.assertEqual("article-1", second_store.due()[0]["announcement_id"])
            second_store.close()

    def test_failed_delivery_stays_pending_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = AnnouncementStore(str(Path(temporary_directory) / "announcements.sqlite3"))
            store.add("article-1", {"title": "Listing"})
            delay = store.mark_failed("article-1", 1, "temporary webhook outage")

            self.assertEqual(2, delay)
            self.assertEqual([], store.due())
            store.close()


if __name__ == "__main__":
    unittest.main()
