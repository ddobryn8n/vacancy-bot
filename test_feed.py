"""Тесты ленты без сети и без Telegram.

    python -m unittest test_feed -v
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import config
import feed
from collector import Post
from dedup import SentStore
from tg import TelegramError

NOW = datetime.now(timezone.utc)


def post(n, text=None, hours_ago=1):
    text = text or (f"Ищем копирайтера в онлайн-школу №{n}\nЗадачи: писать статьи и посты для блога\n"
                    f"Оплата: {50 + n} 000 ₽ в месяц, удалённо\nОткликнуться: @hr_school{n}")
    return Post("textodromo", 1000 + n, NOW - timedelta(hours=hours_ago), text)


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent_file = Path(self.tmp.name) / "sent.json"
        self.store = SentStore(self.sent_file, 30)
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def finder(self, items, stats=None):
        stats = stats if stats is not None else {"textodromo": (len(items), len(items))}
        return lambda log=print: (list(items), self.store, stats)

    def send(self, token, chat, html):
        self.sent.append((chat, html))

    def run_feed(self, items, **kw):
        return feed.run_feed("T", ["-100123"], send=self.send, find=self.finder(items), pause=0,
                             log=lambda *a: None, **kw)

    def test_each_vacancy_is_a_separate_message_without_number(self):
        r = self.run_feed([post(1), post(2), post(3)], max_items=10)
        self.assertEqual(r["sent"], 3)
        self.assertEqual(len(self.sent), 3)
        for _, html in self.sent:
            self.assertTrue(html.startswith('<b><a href="https://t.me/textodromo/'), html[:60])
            self.assertNotIn("Вакансии на", html)

    def test_limit_per_run(self):
        r = self.run_feed([post(i) for i in range(1, 8)], max_items=3)
        self.assertEqual(r["sent"], 3)
        self.assertEqual(len(self.sent), 3)

    def test_sent_file_saved_and_not_repeated(self):
        self.run_feed([post(1), post(2)], max_items=10)
        again = SentStore(self.sent_file, 30)
        self.assertTrue(again.was_sent(post(1), config.DUPLICATE_THRESHOLD))
        self.assertTrue(again.was_sent(post(2), config.DUPLICATE_THRESHOLD))

    def test_dry_run_sends_and_saves_nothing(self):
        r = self.run_feed([post(1)], max_items=10, dry_run=True)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.sent_file.exists())
        self.assertEqual(r["sent"], 0)

    def test_failed_send_is_not_marked_as_sent(self):
        def boom(token, chat, html):
            raise TelegramError("sendMessage: Forbidden")
        r = feed.run_feed("T", ["-100123"], send=boom, find=self.finder([post(1), post(2), post(3)]),
                          pause=0, log=lambda *a: None, max_items=10)
        self.assertEqual(r["sent"], 0)
        self.assertEqual(r["failed"], feed.MAX_FAILED_IN_ROW)   # остановились, а не долбили дальше
        self.assertFalse(self.sent_file.exists())

    def test_one_failure_then_ok_continues(self):
        calls = {"n": 0}

        def flaky(token, chat, html):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TelegramError("sendMessage: Too Many Requests")
            self.sent.append((chat, html))
        r = feed.run_feed("T", ["-100123"], send=flaky, find=self.finder([post(1), post(2), post(3)]),
                          pause=0, log=lambda *a: None, max_items=10)
        self.assertEqual((r["sent"], r["failed"]), (2, 1))

    def test_all_channels_down_raises(self):
        with self.assertRaises(RuntimeError):
            feed.run_feed("T", ["-100123"], send=self.send, pause=0, log=lambda *a: None,
                          find=self.finder([], {"a": "ошибка: ConnectionError", "b": "ошибка: Timeout"}))

    def test_empty_run_is_ok(self):
        r = self.run_feed([])
        self.assertEqual((r["sent"], r["failed"], r["candidates"]), (0, 0, 0))

    def test_oldest_first_order(self):
        self.run_feed([post(1, hours_ago=1), post(2, hours_ago=5)], max_items=10)
        self.assertIn("№2", self.sent[0][1])   # позже опубликованная идёт второй


if __name__ == "__main__":
    unittest.main()
