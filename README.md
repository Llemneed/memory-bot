# Memory Bot

Минимальный Telegram-бот с диалоговой памятью на SQLite FTS5 и генерацией ответов через `g4f`.

## Что внутри

- `app.py` — точка входа
- `telegram/handlers.py` — обработка сообщений и пайплайн диалога
- `memory/` — retrieval, сборка контекста и ограничения по размеру
- `dialogs/` — short-term история последних сообщений
- `llm/` — клиент `g4f` с fallback по провайдерам
- `database/sqlite.py` — инициализация SQLite и FTS5

## Пайплайн

1. Пользователь отправляет сообщение.
2. Сообщение сохраняется в SQLite.
3. По FTS5 ищутся релевантные фрагменты прошлых сообщений.
4. Из retrieval и последних сообщений собирается контекст.
5. Бот вызывает LLM через `g4f`.
6. Ответ отправляется пользователю и сохраняется в историю.

## Быстрый старт локально

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env
# укажи BOT_TOKEN в .env

python app.py
```

## Запуск в Docker

```bash
cp .env.example .env
# укажи BOT_TOKEN в .env

docker compose up -d --build
```

## Деплой одной командой

Если на машине уже установлен Docker Compose, можно запускать так:

```bash
git clone https://github.com/Llemneed/memory-bot.git && cd memory-bot && BOT_TOKEN=your_telegram_bot_token_here docker compose up -d --build
```

Если нужен не дефолтный путь к базе:

```bash
git clone https://github.com/Llemneed/memory-bot.git && cd memory-bot && BOT_TOKEN=your_telegram_bot_token_here DB_PATH=database/sqlite.db docker compose up -d --build
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `BOT_TOKEN` | — | токен Telegram-бота |
| `G4F_MODEL` | `gpt-4o-mini` | модель для `g4f` |
| `LLM_TIMEOUT` | `60` | таймаут одного провайдера, сек |
| `LLM_MAX_RETRIES` | `5` | сколько fallback-провайдеров пробовать |
| `HISTORY_LAST_N` | `10` | сколько последних сообщений брать в short-term историю |
| `RETRIEVAL_TOP_K` | `5` | сколько сообщений поднимать из FTS5 |
| `MAX_CONTEXT_CHARS` | `6000` | лимит символов у retrieval-блока |
| `DB_PATH` | `database/sqlite.db` | путь к SQLite-файлу |

## Fallback-провайдеры

Порядок fallback зашит в `llm/g4f_client.py`:

`Auto -> PollinationsAI -> Blackbox -> DeepInfra -> HuggingChat -> You`

При недоступности текущего провайдера бот автоматически пробует следующий.
