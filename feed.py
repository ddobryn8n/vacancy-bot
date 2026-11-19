"""Режим ленты: каждая новая вакансия уходит в чат отдельным сообщением, по мере появления.

Один запуск (его дёргает n8n раз в 15 минут через server.py):
  1. собирает посты каналов, отбирает вакансии теми же правилами, что и дайджест;
  2. убирает дубли и то, что уже отправляли (sent.json);
  3. берёт до FEED_MAX_PER_RUN лучших и шлёт по одной с паузой;
  4. после каждой отправки сразу сохраняет sent.json, чтобы при сбое ничего не ушло дважды.

Из консоли:
    python feed.py --dry-run          показать, что ушло бы, ничего не отправлять
    python feed.py                    отправить (нужны BOT_TOKEN и CHAT_ID)
"""
import argparse
import sys
import time

import config
import selector
from collector import collect
from dedup import SentStore, remove_duplicates
from formatter import format_vacancy
from main import deliver, has_pay, rank_key
from tg import send_message
from textutils import title_of

MAX_FAILED_IN_ROW = 2  # столько неудач подряд — и запуск прекращается (нет прав, бота удалили, лимит Telegram)


def find_candidates(log=print):
    """Свежие вакансии, прошедшие отбор, без дублей и без уже отправленных.

    Возвращает (кандидаты, store, статистика каналов).
    """
    tails = selector.keywords().get("хвосты", [])
    items, stats = collect(config.CHANNELS, config.DAYS_BACK, tails, log=log)
    passed = [i for i in items if selector.check(i).ok]
    unique, dupes = remove_duplicates(passed, config.DUPLICATE_THRESHOLD, better=lambda i: (has_pay(i), i.date))
    store = SentStore(config.SENT_FILE, config.SENT_KEEP_DAYS)
    # Вакансия считается отправленной, если отправлялась любая её копия из других каналов.
    copies = {i.key: [i] for i in unique}
    for d, k, _ in dupes:
        copies[k.key].append(d)
    fresh = [i for i in unique
             if not any(store.was_sent(c, config.DUPLICATE_THRESHOLD) for c in copies[i.key])]
    if config.REQUIRE_PAY:
        fresh = [i for i in fresh if has_pay(i)]
    log(f"Вакансий после нарезки: {len(items)}, прошло отбор: {len(passed)}, дублей убрано: {len(dupes)}, "
        f"новых кандидатов: {len(fresh)}")
    return fresh, store, stats


def run_feed(token, chat_ids, dry_run=False, max_items=None, pause=None, send=send_message,
             find=find_candidates, log=print):
    """Один запуск ленты. Возвращает словарь с итогом (его отдаёт server.py в n8n)."""
    max_items = config.FEED_MAX_PER_RUN if max_items is None else max_items
    pause = config.FEED_PAUSE_SECONDS if pause is None else pause
    fresh, store, stats = find(log=log)
    bad_channels = [ch for ch, s in stats.items() if not isinstance(s, tuple)]
    result = {"candidates": len(fresh), "sent": 0, "failed": 0, "channels_failed": bad_channels,
              "channels_total": len(stats), "dry_run": dry_run, "titles": []}
    if stats and len(bad_channels) == len(stats):
        raise RuntimeError("не скачался ни один канал (сеть или блокировка t.me)")

    # Берём лучших, а в чат отправляем от старых к новым: лента читается по порядку.
    chosen = sorted(fresh, key=rank_key, reverse=True)[:max_items]
    chosen.sort(key=lambda i: i.date)
    remote_words = selector.keywords().get("удалёнка", [])
    in_row = 0
    for n, item in enumerate(chosen):
        message = format_vacancy(None, item, remote_words)
        title = title_of(item)[:60]
        if dry_run:
            log(f"\n--- {item.url} ---\n{message}")
            result["titles"].append(title)
            continue
        if n:
            time.sleep(pause)
        sent_to, failed_to = deliver(token, chat_ids, message, send)
        if sent_to:
            in_row = 0
            store.add(item)
            store.save()      # сразу: если следующая отправка упадёт, эта не повторится
            result["sent"] += 1
            result["titles"].append(title)
        else:
            in_row += 1
            result["failed"] += 1
            if in_row >= MAX_FAILED_IN_ROW:
                log("Подряд не ушло несколько сообщений, остановка до следующего запуска.")
                break
    log(f"Итог: отправлено {result['sent']}, не отправлено {result['failed']}, "
        f"кандидатов было {result['candidates']}")
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=None, help="сколько вакансий максимум за запуск")
    args = ap.parse_args()
    token, raw = config.telegram_settings()
    chat_ids, bad = config.parse_chat_ids(raw)
    if not args.dry_run and not (token and chat_ids):
        sys.exit("Нет BOT_TOKEN или корректного CHAT_ID.")
    run_feed(token, chat_ids, dry_run=args.dry_run, max_items=args.max)


if __name__ == "__main__":
    main()
