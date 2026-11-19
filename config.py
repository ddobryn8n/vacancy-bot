"""Настройки парсера. Токены здесь не храним, они берутся из .env или переменных окружения."""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Публичные каналы (юзернейм без @). Читаются через t.me/s/<юзернейм>.
# Разбор каналов и почему выбраны именно эти: каналы.md
CHANNELS = [
    "rueventjob",            # Удаленка - вся творческая работа
    "textodromo",            # Текстодром
    "work_editor",           # Работа с текстами — вакансии
    "work_copywriters",      # Работа для копирайтеров и редакторов
    "freelancechoice",       # Freelance Choice
    "uvetrovoi",             # ФРИЛАНС
    "copywriter_vacancies",  # Вакансии для копирайтеров
    "seohr",                 # SEO HR
    "zdemcv",                # Ждём резюме | Лайфхакер
    "normrabota",            # Норм работа
    "freegolup",             # Голубь на Фрилансе
    "self_ma",               # Копирайтер, редактор — удаленная работа
    "Work4writers",          # Work for writers
]

# Каналы целиком про тексты: в них не требуем слова «удалёнка», отсекаем только явный офис или гибрид.
TEXT_CHANNELS = {"textodromo", "work_editor", "work_copywriters", "copywriter_vacancies", "Work4writers"}

MAX_EXPERIENCE_YEARS = 3  # вакансии, где требуют опыт от стольких лет и больше, отсекаем
# Каналы, где контакт может быть только за кнопкой под постом (вакансию берём и без контакта в тексте)
BUTTON_CONTACT_CHANNELS = {"textodromo"}

DAYS_BACK = 3             # за сколько дней собирать посты
MAX_VACANCIES = 5          # сколько вакансий отправлять за раз (не больше)
MAX_PER_CHANNEL = 2        # не больше стольких вакансий из одного канала в сообщении
PAID_PRIORITY_DAYS = 2     # вакансии с оплатой за эти дни идут первыми, потом остальные по свежести
SENT_KEEP_DAYS = 30        # сколько дней помнить отправленные вакансии
DUPLICATE_THRESHOLD = 0.6  # похожесть текстов (0..1), выше которой две вакансии считаются одной
TIMEZONE_OFFSET_HOURS = 3  # Москва, для сравнения «свежести» по дням

# Чем отбирать вакансии: "keywords" (списки слов из keywords.txt).
# Позже сюда добавится вариант с нейросетью, см. selector.py
SELECTOR = "keywords"

KEYWORDS_FILE = BASE_DIR / "keywords.txt"
SENT_FILE = BASE_DIR / "sent.json"
ENV_FILE = BASE_DIR / ".env"


def load_env(path=ENV_FILE):
    """Читает KEY=VALUE из .env в переменные окружения (уже заданные не трогает)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --- Настройки сервера-ленты (server.py, feed.py). Задаются переменными окружения, в Dokploy — вкладка Environment ---
load_env()


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "да")


def _list(name):
    return [x.strip().lstrip("@") for x in os.environ.get(name, "").split(",") if x.strip()]


# Где хранить память об отправленном. На сервере это том /data, чтобы переживал пересборку контейнера.
SENT_FILE = Path(os.environ.get("SENT_FILE") or SENT_FILE)
# Дополнительные каналы без правки кода: EXTRA_CHANNELS=chan1,chan2 (юзернеймы без @)
CHANNELS = CHANNELS + [c for c in _list("EXTRA_CHANNELS") if c not in CHANNELS]
TEXT_CHANNELS = TEXT_CHANNELS | set(_list("EXTRA_TEXT_CHANNELS"))
# Лента: сколько вакансий слать за один запуск, пауза между сообщениями (сек), только ли с оплатой
FEED_MAX_PER_RUN = int(os.environ.get("FEED_MAX_PER_RUN") or 3)
FEED_PAUSE_SECONDS = float(os.environ.get("FEED_PAUSE_SECONDS") or 3)
REQUIRE_PAY = _flag("REQUIRE_PAY", "0")
# Кому писать о поломке (необязательно): id вашего личного чата с ботом
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
RUN_TOKEN = os.environ.get("RUN_TOKEN", "").strip()

CHAT_ID_RE = re.compile(r"^(-?\d+|@\w{4,})$")


def parse_chat_ids(raw):
    """CHAT_ID: один или несколько id через запятую (пробелы вокруг и пустые элементы не мешают).
    Возвращает (список уникальных id по порядку, список отброшенных значений)."""
    ids, bad = [], []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not CHAT_ID_RE.match(part):
            bad.append(part)
        elif part not in ids:
            ids.append(part)
    return ids, bad


def telegram_settings():
    """Токен и сырое значение CHAT_ID (разбирает parse_chat_ids)."""
    load_env()
    token = os.environ.get("BOT_TOKEN", "").strip()
    chat_id = os.environ.get("CHAT_ID", "").strip()
    return token, chat_id
