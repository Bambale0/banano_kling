"""Never duplicate verified durable feed objects while normalizing media URLs."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.services.feed_persist import (
    is_existing_durable_feed_upload,
    persist_feed_result_urls,
)

CANONICAL = "https://neuromixbot.com/uploads/feed/original.jpg"
LEGACY = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/feed/original.jpg"
LEGACY_ALT = "https://tanyapp.chillcreative.ru/uploads/feed/original.jpg"


def public_url(relative: str) -> str:
    return "https://neuromixbot.com/uploads/" + relative


class DurableMediaPreservationTests(unittest.TestCase):
    @patch("bot.services.media_storage.public_upload_url", side_effect=public_url)
    @patch("bot.services.media_storage.upload_exists", return_value=True)
    def test_known_current_and_legacy_host_urls_are_preserved(self, exists, _public):
        for url in (CANONICAL, LEGACY, LEGACY_ALT):
            with self.subTest(url=url):
                self.assertTrue(is_existing_durable_feed_upload(url))
        self.assertEqual(exists.call_count, 3)
        exists.assert_called_with("feed/original.jpg")

    @patch("bot.services.media_storage.public_upload_url", side_effect=public_url)
    @patch("bot.services.media_storage.upload_exists", return_value=True)
    def test_untrusted_or_unsafe_urls_never_probe_s3(self, exists, _public):
        invalid = [
            "https://evil.invalid/uploads/feed/original.jpg",
            "https://neuromixbot.com.evil.invalid/uploads/feed/original.jpg",
            "https://neuromixbot.com:8443/uploads/feed/original.jpg",
            "https://neuromixbot.com/uploads/feed/original.jpg?token=x",
            "https://neuromixbot.com/uploads/feed/../original.jpg",
            "https://neuromixbot.com/uploads/feed/%2e%2e/original.jpg",
            "https://user@neuromixbot.com/uploads/feed/original.jpg",
            "file:///uploads/feed/original.jpg",
        ]
        for url in invalid:
            with self.subTest(url=url):
                self.assertFalse(is_existing_durable_feed_upload(url))
        exists.assert_not_called()

    @patch("bot.services.media_storage.public_upload_url", side_effect=public_url)
    @patch("bot.services.media_storage.upload_exists", return_value=False)
    def test_missing_remote_object_must_not_be_marked_durable(self, exists, _public):
        self.assertFalse(is_existing_durable_feed_upload(LEGACY))
        exists.assert_called_once_with("feed/original.jpg")

    @patch("bot.services.media_storage.public_upload_url", side_effect=public_url)
    @patch("bot.services.media_storage.upload_exists", side_effect=OSError("provider offline"))
    def test_failed_storage_check_cannot_claim_missing_object_as_present(self, *_):
        self.assertFalse(is_existing_durable_feed_upload(CANONICAL))


class AsyncDurableFeedPersistenceTests(unittest.IsolatedAsyncioTestCase):
    @patch("bot.services.feed_persist.is_existing_durable_feed_upload", return_value=True)
    @patch("bot.services.feed_persist._copy_local_upload_to_feed")
    @patch("bot.services.feed_persist.download_to_local")
    async def test_persistence_reuses_verified_url_without_any_new_download(
        self, download, local_copy, already_durable
    ):
        result = await persist_feed_result_urls([LEGACY], require_local=True)
        self.assertEqual(result, [LEGACY])
        download.assert_not_called()
        local_copy.assert_not_called()
        already_durable.assert_called_once_with(LEGACY)


if __name__ == "__main__":
    unittest.main()
