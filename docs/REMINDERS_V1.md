# Reminders v1

## Форматы фраз
Поддерживаются локально:
- `в 16:00 напомни ...`
- `завтра в 10:30 ...`
- `сегодня в 09:15 ...`
- `через 2 часа ...`
- `через 15 минут ...`

Если время не распознано — вернётся 1 уточняющий вопрос (например "Когда напомнить?").

## Где хранится
- Таблица `reminders` в SQLite (`memory/migrations/007_reminders.sql`).

## Доставка
- Telegram (если заданы `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`).
- Иначе: локальный лог + событие, статус `failed` с `last_error=telegram_not_configured`.

## Ретраи
- Telegram отправка: до 3 попыток с backoff 1s / 2s / 4s.

## API
- `GET /api/v1/reminders` — список.
- `POST /api/v1/reminders/create` — создание (техническое, требует due_at/text).
- `DELETE /api/v1/reminders/{id}` — отмена.

## События
- `reminder_created`
- `reminder_due`
- `reminder_sent`
- `reminder_failed`
- `reminder_cancelled`

## TELEGRAM_CHAT_ID
Можно получить через Bot API:
1. Напишите боту сообщение.
2. Вызовите `getUpdates`:

```bash
curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

Найдите `chat.id` в ответе — это и есть `TELEGRAM_CHAT_ID`.
