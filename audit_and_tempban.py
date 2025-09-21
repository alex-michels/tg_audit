import asyncio, json, os, csv
from random import uniform
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, types, errors
from telethon.tl.functions.channels import EditBannedRequest

API_ID   = 123456
API_HASH = "hash"
SESSION  = "group_audit"
CHANNEL  = "group username or invite link"   # или @username

# --- ВРЕМЕННОЕ ОКНО ДЛЯ БАНА ---
START_AT = datetime(2025, 9, 19, 21, 42, tzinfo=timezone(timedelta(hours=2))).astimezone(timezone.utc)  # 21:42 CEST
END_AT   = datetime(2025, 9, 21, 10, 44, tzinfo=timezone(timedelta(hours=2))).astimezone(timezone.utc)  # 10:44 CEST

# До какого времени держим бан
UNBAN_AT = datetime(2025, 9, 22, 16, 30, tzinfo=timezone(timedelta(hours=2))).astimezone(timezone.utc)

DRY_RUN = True

# Батчи/паузы
BATCH_SIZE = 50
JITTER_PER_REQUEST = (0.2, 0.6)
SLEEP_BETWEEN_BATCHES = (1.0, 2.0)

OUT_DIR = "out"
BANNED_IDS_PATH  = os.path.join(OUT_DIR, "banned_ids.json")   # сюда пишем ТОЛЬКО незабаненных
BANNED_DONE_PATH = os.path.join(OUT_DIR, "banned_done.json")  # фактически забаненные
CSV_PATH         = os.path.join(OUT_DIR, "new_users.csv")     # все из окна (для аудита)

def _atomic_dump(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)

def _iso_utc(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).isoformat() if dt else ""

async def collect_users_in_window(client, ch):
    """
    Собираем всех из окна (START_AT, END_AT] и сразу тащим:
      joined_at, source, first_name, last_name, username
    """
    meta: dict[int, dict] = {}

    async for ev in client.iter_admin_log(ch, limit=None, join=True, invite=True):
        if ev.date <= START_AT:
            break
        if ev.date > END_AT:
            continue

        act = ev.action
        uid, source = None, None

        if isinstance(act, types.ChannelAdminLogEventActionParticipantJoin):
            uid, source = ev.user_id, "join"
        elif isinstance(act, types.ChannelAdminLogEventActionParticipantInvite):
            uid = getattr(getattr(act, "participant", None), "user_id", None) or ev.user_id
            source = "invite"
        elif isinstance(act, types.ChannelAdminLogEventActionParticipantJoinByRequest):
            uid = getattr(getattr(act, "participant", None), "user_id", None) or ev.user_id
            source = "join_by_request"

        if not uid:
            continue

        # достаём User из карты сущностей события, если доступно
        u = None
        try:
            ents = getattr(ev, "entities", None)  # AdminLogEvent.entities: dict[user_id -> User]
            if ents:
                u = ents.get(uid)
        except Exception:
            u = None

        # инициализируем/обновляем запись
        old = meta.get(uid)
        if (not old) or (ev.date < old['joined_at']):
            meta[uid] = {
                'joined_at': ev.date,
                'source': source,
                'first_name': getattr(u, "first_name", None) if u else (old['first_name'] if old else None),
                'last_name':  getattr(u, "last_name",  None) if u else (old['last_name']  if old else None),
                'username':   getattr(u, "username",   None) if u else (old['username']   if old else None),
            }
        else:
            # дата старая, но может не хватать ФИО/username — дольём
            if u:
                if not old.get('first_name'): old['first_name'] = getattr(u, "first_name", None)
                if not old.get('last_name'):  old['last_name']  = getattr(u, "last_name",  None)
                if not old.get('username'):   old['username']   = getattr(u, "username",   None)

    ids = sorted(meta.keys())
    return ids, meta

RESOLVE_MISSING = True
RESOLVE_BATCH = 100  # безопасный размер батча

async def resolve_missing_users(client, meta: dict[int, dict]):
    missing = [uid for uid, info in meta.items()
               if not (info.get('first_name') or info.get('last_name') or info.get('username'))]
    if not missing:
        return

    for i in range(0, len(missing), RESOLVE_BATCH):
        chunk = missing[i:i+RESOLVE_BATCH]
        try:
            # get_entity умеет принимать список и вернёт список User/Channel/Chat
            entities = await client.get_entity(chunk)
            # если в chunk один id, Telethon вернёт не список, нормализуем
            if not isinstance(entities, list):
                entities = [entities]
            for ent in entities:
                if isinstance(ent, types.User):
                    info = meta.get(ent.id)
                    if info:
                        info['first_name'] = info.get('first_name') or ent.first_name
                        info['last_name']  = info.get('last_name')  or ent.last_name
                        info['username']   = info.get('username')   or ent.username
        except Exception:
            # если часть не удалось резолвить (нет access_hash в кэше и т.п.), просто идём дальше
            pass
        # лёгкий джиттер между батчами, чтобы не ловить FLOOD
        await asyncio.sleep(uniform(0.2, 0.5))

def _s(x):  # безопасная строковая очистка
    return (x or "").replace("\r", " ").replace("\n", " ").strip()

async def write_csv(meta: dict[int, dict], csv_path: str):
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    rows = []
    for uid, info in meta.items():
        rows.append((
            uid,
            _s(info.get('username')),
            _s(info.get('first_name')),
            _s(info.get('last_name')),
            _iso_utc(info.get('joined_at')),
            _s(info.get('source', ''))
        ))
    rows.sort(key=lambda r: (r[4] or ""))  # по дате
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "username", "first_name", "last_name", "joined_at_utc", "source"])
        w.writerows(rows)

async def main():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        ch = await client.get_entity(CHANNEL)

        # 1) Собираем окно и пишем полный CSV
        user_ids, meta = await collect_users_in_window(client, ch)
        print(f"Окно: ({START_AT.isoformat()} , {END_AT.isoformat()}] UTC")
        print(f"Найдено в окне: {len(user_ids)}")
        # 1a) По желанию — добиваем пропуски батчем
        if RESOLVE_MISSING:
            await resolve_missing_users(client, meta)

        # 1b) Пишем CSV
        await write_csv(meta, CSV_PATH)
        print(f"CSV-лог: {CSV_PATH}")

        # 2) Загружаем уже забаненных (прогресс прошлых прогонов)
        if os.path.exists(BANNED_DONE_PATH):
            with open(BANNED_DONE_PATH, "r", encoding="utf-8") as f:
                banned_done = set(json.load(f))
        else:
            banned_done = set()

        # 3) Фильтруем: сохраняем ТОЛЬКО ещё не забаненных
        pending_ids = sorted(set(user_ids) - banned_done)
        _atomic_dump(BANNED_IDS_PATH, pending_ids)
        print(f"Из них уже забанено ранее: {len(banned_done & set(user_ids))}")
        print(f"Кандидатов к бану (pending): {len(pending_ids)} → сохранены в {BANNED_IDS_PATH}")

        if DRY_RUN:
            print("DRY_RUN=ON — никого не баню. CSV полный, JSON только незабаненные.")
            return

        # 4) Боевое: баним только pending_ids
        ban_rights = types.ChatBannedRights(view_messages=True, until_date=int(UNBAN_AT.timestamp()))
        total_banned_now = 0

        for i in range(0, len(pending_ids), BATCH_SIZE):
            batch = pending_ids[i:i + BATCH_SIZE]
            print(f"Батч {i//BATCH_SIZE + 1}: {len(batch)} юзеров")
            for uid in batch:
                try:
                    await client(EditBannedRequest(ch, uid, ban_rights))
                    banned_done.add(uid)
                    total_banned_now += 1
                except errors.FloodWaitError as e:
                    _atomic_dump(BANNED_DONE_PATH, sorted(banned_done))
                    print(f"FLOOD_WAIT {e.seconds}s → сплю…")
                    await asyncio.sleep(e.seconds + 1)
                except Exception:
                    await asyncio.sleep(0.5)
                finally:
                    await asyncio.sleep(uniform(*JITTER_PER_REQUEST))
            _atomic_dump(BANNED_DONE_PATH, sorted(banned_done))
            await asyncio.sleep(uniform(*SLEEP_BETWEEN_BATCHES))

        print(f"Забанено сейчас: {total_banned_now}. Всего помечено как забанённые: {len(banned_done)}")
        print(f"Файлы: {BANNED_IDS_PATH} (pending), {BANNED_DONE_PATH} (done), {CSV_PATH} (все из окна)")
        print(f"Бан действует до {UNBAN_AT.isoformat()} (UTC)")

if __name__ == "__main__":
    asyncio.run(main())