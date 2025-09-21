# Telegram Channel Audit & Temporary Ban Tool

> Найти и временно забанить всех, кто вступил в канал/группу **в заданном окне времени** `(START_AT, END_AT]`.  
> Источник данных — **Admin Log (Recent Actions)**; бан через `channels.editBanned` с `ChatBannedRights(view_messages=True, until_date=...)`.  
> Резюмируемо, безопасно к повторным прогонам, с CSV-логом и скриптом для разбана.

---

## Что умеет

- Фильтрация новых участников **строго после** `START_AT` и **не позже** `END_AT` (окно `(START_AT, END_AT]`).
- CSV-лог: `user_id, username, first_name, last_name, joined_at_utc, source(join|invite|join_by_request)`.
- Временный бан до `UNBAN_AT` (после истечения запрет снимается автоматически).
- Батчи + джиттер + обработка FLOOD_WAIT.
- **Резюмируемый прогресс**:  
  - `out/banned_ids.json` — кандидаты (только те, кто ещё не забанен);  
  - `out/banned_done.json` — фактически забаненные (накапливается между прогонами).
- `unban.py` — массовый разбан (снятие запрета на просмотр).  
  **Важно:** разбан **не подписывает** пользователей обратно на приватный канал.

---

## Требования

- Вы — **админ** канала/группы с правом банить.
- **Python 3.11+** установлен в системе.
- **Telethon** (ставится из `requirements.txt`).
- `api_id` и `api_hash` (получить на `my.telegram.org → API development tools`).
- `@username` канала **или** приватная инвайт-ссылка.

---

## Установка (Windows/macOS/Linux)

1) **Установите Python** (проверьте версию):
```bash
python --version
# или
python3 --version
```

2) **Создайте папку проекта и виртуальное окружение**:
```bash
mkdir tg_audit && cd tg_audit
python -m venv .venv
# macOS/Linux: python3 -m venv .venv
```

3) **Активируйте окружение**:
- Windows (PowerShell):
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
  Если ругается на политику, временно разрешите:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\.venv\Scripts\Activate.ps1
  ```
- Windows (cmd):
  ```cmd
  .\.venv\Scripts\activate.bat
  ```
- macOS/Linux:
  ```bash
  source .venv/bin/activate
  ```

4) **Создайте `requirements.txt` и установите зависимости**:
```
telethon==1.41.2
```
Установка:
```bash
pip install -r requirements.txt
```

---

## Файлы проекта

```
.
├─ audit_and_tempban.py   # основной скрипт (поиск по окну + бан)
├─ unban.py                     # массовый разбан
├─ requirements.txt
├─ .gitignore                   # игнорит out/ и файлы сессий
└─ out/
   ├─ new_users.csv             # все из окна (для аудита)
   ├─ banned_ids.json           # кандидаты к бану (ещё не забаненные)
   └─ banned_done.json          # фактически забаненные (прогресс)
```

---

## Настройка

Откройте `audit_and_tempban.py` и задайте:

- `API_ID`, `API_HASH` — ваши ключи.
- `SESSION` — имя файла сессии (создастся `SESSION.session` рядом со скриптом).
- `CHANNEL` — `@username` канала или приватная инвайт-ссылка.
- `START_AT`, `END_AT` — окно по времени. Пример:
  ```python
  # локальное время с TZ (CEST = UTC+2, CET = UTC+1), в коде переводится в UTC
  START_AT = datetime(2025, 9, 19, 21, 42, tzinfo=timezone(timedelta(hours=2)))
  END_AT   = datetime(2025, 9, 21, 10, 44, tzinfo=timezone(timedelta(hours=2)))
  ```
  Окно интерпретируется как **(START_AT, END_AT]** — строго после нижней границы и **включая** верхнюю.
- `UNBAN_AT` — до какого момента держать временный бан (в местной TZ; код переведёт в UTC).
- `DRY_RUN` — сначала `True` (никаких банов), затем `False` для боевого запуска.
- По желанию:
  - `BATCH_SIZE`, `JITTER_PER_REQUEST`, `SLEEP_BETWEEN_BATCHES` — настройки темпа.
  - `RESOLVE_MISSING = True` — дозаполнять `username/имя/фамилию` батчами через `get_entity`.

> **Логин:** при первом запуске Telethon запросит **номер телефона** и **код**; при включённом 2FA — **пароль**. Создастся файл сессии `SESSION.session`; храните его, чтобы не логиниться заново.

---

## Запуск

### 1) Пробный прогон (рекомендуется первым)
В `audit_and_tempban.py`:
```python
DRY_RUN = True
```
Запустите:
```bash
python audit_and_tempban.py
```
Что произойдёт:
- Соберутся события вступления из Admin Log, отфильтруются по окну `(START_AT, END_AT]`.
- Сформируется **CSV** `out/new_users.csv` со столбцами:
  ```
  user_id, username, first_name, last_name, joined_at_utc, source
  ```
- Сформируется `out/banned_ids.json` — **только ещё не забаненные ранее** (учитывается `out/banned_done.json`).
- Никого банить **не будут** (это dry run).

### 2) Боевой прогон (бан)
Поменяйте:
```python
DRY_RUN = False
```
Запустите:
```bash
python audit_and_tempban.py
```
Скрипт будет:
- Банить **только** тех, кто в `out/banned_ids.json`.
- Работать **батчами**, с **джиттером** и паузами при FLOOD_WAIT.
- Постоянно сохранять прогресс в `out/banned_done.json`.
- Безопасен к повторным прогонам (не затрагивает уже забаненных).

### 3) Повторный прогон (догоняем хвосты)
Просто запускайте снова: `banned_ids.json` каждый раз формируется **из окна минус уже забаненные**.

---

## Разбан

В любое время:
```bash
python unban.py
```
- Возьмёт `out/banned_done.json` (если его нет — `out/banned_ids.json`).
- Снимет запрет `view_messages`.  
**Важно:** разбан **не подписывает** участников обратно на приватный канал.

---

## Советы и ограничения

- **Admin Log — “недавние действия”**, а не вся история. Запускайте скрипт ближе ко времени всплеска, чтобы окно покрывалось логами.
- **FLOOD_WAIT** — нормален при массовых изменениях. Скрипт сам ждёт нужное число секунд. Можно уменьшить `BATCH_SIZE`.
- **Права**: нужен админ с `ban users`.
- **Сессии**: не коммитьте `*.session` в git; не удаляйте, иначе придётся логиниться заново.
- **Приватный канал**: после снятия бана человек **сам** должен вернуться (например, по инвайту); автоматически он не “переподпишется”.

---

## Быстрый чек-лист

- [ ] Python установлен, `pip` работает, venv активирован.  
- [ ] Установили зависимости: `pip install -r requirements.txt`.  
- [ ] В `tempban_after_threshold.py` заданы `API_ID`, `API_HASH`, `SESSION`, `CHANNEL`, `START_AT`, `END_AT`, `UNBAN_AT`.  
- [ ] Первый запуск — `DRY_RUN=True`, проверили CSV/количество.  
- [ ] Боевой запуск — `DRY_RUN=False`, наблюдаете батчи/прогресс.  
- [ ] По окончании — `python unban.py` (при необходимости).

---

## Структура CSV

`out/new_users.csv`:

| column           | meaning                                           |
|------------------|---------------------------------------------------|
| `user_id`        | Telegram numeric ID                               |
| `username`       | @username (если есть)                             |
| `first_name`     | имя (если есть)                                   |
| `last_name`      | фамилия (если есть)                                |
| `joined_at_utc`  | дата/время события вступления в UTC (ISO 8601)    |
| `source`         | `join` / `invite` / `join_by_request`             |

---

## Безопасность и приватность

- Не публикуйте `API_ID`, `API_HASH`, файлы сессий `*.session` и содержимое `out/`.
- Добавьте `.gitignore`, который исключает `out/` и файлы сессий (пример в репозитории).