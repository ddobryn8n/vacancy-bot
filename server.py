"""HTTP-обёртка над лентой для n8n и Dokploy.

    POST /run          один запуск ленты (заголовок Authorization: Bearer <RUN_TOKEN>)
    POST /run?dry=1    то же, но ничего не отправляется (проверка из n8n или curl)
    GET  /health       жив ли сервис, когда был последний запуск (без секретов)

Запускать одним процессом (uvicorn без --workers): так блокировка от двойного запуска работает.
"""
import hmac
import shutil
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Query

import config
import feed
from tg import TelegramError, send_message

LOCK = threading.Lock()
STATE = {"last_run": None, "last_ok": None, "last_result": None, "last_error": None, "last_alert": 0.0}
ALERT_EVERY_SECONDS = 3 * 3600  # о поломке пишем не чаще раза в 3 часа


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_sent_file():
    """На новом сервере том /data пустой: кладём туда sent.json из образа, чтобы не слать старые вакансии заново."""
    target = config.SENT_FILE
    bundled = config.BASE_DIR / "sent.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() and bundled.exists() and bundled.resolve() != target.resolve():
        shutil.copyfile(bundled, target)
        print(f"sent.json скопирован из образа в {target}")


@asynccontextmanager
async def lifespan(app):
    seed_sent_file()
    token, raw = config.telegram_settings()
    chat_ids, bad = config.parse_chat_ids(raw)
    print(f"Старт. Чатов: {len(chat_ids)}, каналов-источников: {len(config.CHANNELS)}, "
          f"токен бота {'есть' if token else 'НЕ ЗАДАН'}, RUN_TOKEN {'есть' if config.RUN_TOKEN else 'НЕ ЗАДАН'}, "
          f"память: {config.SENT_FILE}")
    yield


app = FastAPI(title="vacancy-feed", lifespan=lifespan)


def alert(text):
    """Сообщение администратору о поломке (если задан ADMIN_CHAT_ID), не чаще раза в 3 часа."""
    token, _ = config.telegram_settings()
    if not (config.ADMIN_CHAT_ID and token):
        return
    if time.time() - STATE["last_alert"] < ALERT_EVERY_SECONDS:
        return
    STATE["last_alert"] = time.time()
    try:
        send_message(token, config.ADMIN_CHAT_ID, f"⚠️ Лента вакансий: {text}")
    except TelegramError as e:
        print(f"Не удалось отправить предупреждение: {e}")


@app.get("/health")
def health():
    return {"ok": True, "now": now(), **{k: STATE[k] for k in ("last_run", "last_ok", "last_result", "last_error")}}


@app.post("/run")
def run(dry: int = Query(0), authorization: str = Header(default="")):
    if not config.RUN_TOKEN:
        raise HTTPException(500, "RUN_TOKEN не задан в окружении")
    expected = f"Bearer {config.RUN_TOKEN}"
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, "неверный токен")
    token, raw = config.telegram_settings()
    chat_ids, bad = config.parse_chat_ids(raw)
    if not dry and not (token and chat_ids):
        raise HTTPException(500, "BOT_TOKEN или CHAT_ID не заданы в окружении")
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "предыдущий запуск ещё идёт")
    try:
        STATE["last_run"] = now()
        try:
            result = feed.run_feed(token, chat_ids, dry_run=bool(dry))
        except Exception as e:  # noqa: BLE001 — любая поломка должна дойти до n8n и администратора
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            alert(STATE["last_error"])
            raise HTTPException(500, STATE["last_error"]) from None
        STATE["last_error"] = None
        STATE["last_result"] = result
        if result["failed"] and not result["sent"]:
            alert(f"сообщения не уходят в чат ({result['failed']} неудач). Проверьте, что бот админ группы и CHAT_ID верный.")
            raise HTTPException(502, "ни одно сообщение не ушло в чат")
        STATE["last_ok"] = now()
        return result
    finally:
        LOCK.release()
