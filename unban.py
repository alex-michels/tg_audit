# unban.py
import asyncio, json, os
from random import uniform
from telethon import TelegramClient, types, errors
from telethon.tl.functions.channels import EditBannedRequest

API_ID   = 12345
API_HASH = "hash"
SESSION  = "group_audit"
CHANNEL  = "group username or invite link"

OUT_DIR = "out"
BANNED_IDS_PATH  = os.path.join(OUT_DIR, "banned_ids.json")
BANNED_DONE_PATH = os.path.join(OUT_DIR, "banned_done.json")

BATCH_SIZE = 50
JITTER_PER_REQUEST = (0.2, 0.6)
SLEEP_BETWEEN_BATCHES = (1.0, 2.0)

async def main():
    # читаем тех, кого реально банили (если файла нет — используем всех кандидатов)
    if os.path.exists(BANNED_DONE_PATH):
        with open(BANNED_DONE_PATH, "r", encoding="utf-8") as f:
            ids = json.load(f)
    else:
        with open(BANNED_IDS_PATH, "r", encoding="utf-8") as f:
            ids = json.load(f)

    ids = sorted(set(ids))
    print(f"К разбaну: {len(ids)}")

    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        ch = await client.get_entity(CHANNEL)
        unban_rights = types.ChatBannedRights(view_messages=False, until_date=None)

        done = 0
        for i in range(0, len(ids), BATCH_SIZE):
            batch = ids[i:i + BATCH_SIZE]
            print(f"Батч {i//BATCH_SIZE + 1}: {len(batch)} юзеров")
            for uid in batch:
                try:
                    await client(EditBannedRequest(ch, uid, unban_rights))
                    done += 1
                except errors.FloodWaitError as e:
                    print(f"FLOOD_WAIT {e.seconds}s → сплю…")
                    await asyncio.sleep(e.seconds + 1)
                except Exception:
                    await asyncio.sleep(0.5)
                finally:
                    await asyncio.sleep(uniform(*JITTER_PER_REQUEST))
            await asyncio.sleep(uniform(*SLEEP_BETWEEN_BATCHES))

    print(f"Разбанено: {done}/{len(ids)}")
    print("Напоминание: разбан НЕ подписывает людей обратно — он только снимает запрет на просмотр.")

if __name__ == "__main__":
    asyncio.run(main())
