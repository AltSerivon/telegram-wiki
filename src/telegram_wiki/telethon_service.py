from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User

from telegram_wiki.config import Settings, get_settings


def build_client(settings: Settings | None = None) -> TelegramClient:
    s = settings or get_settings()
    s.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(s.telegram_session_path),
        s.telegram_api_id,
        s.telegram_api_hash,
    )


@asynccontextmanager
async def telegram_client(connected: bool = True) -> AsyncIterator[TelegramClient]:
    client = build_client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "Telegram session not authorized. Run: telegram-wiki login",
        )
    try:
        yield client
    finally:
        await client.disconnect()


def classify_entity(entity) -> tuple[str, int, int | None, str | None, str | None]:
    """Return peer_type, peer_id, access_hash, username, title."""
    if isinstance(entity, Channel):
        un = getattr(entity, "username", None) or None
        title = getattr(entity, "title", None) or None
        return "channel", entity.id, entity.access_hash, un, title
    if isinstance(entity, Chat):
        return "chat", entity.id, None, None, getattr(entity, "title", None) or None
    if isinstance(entity, User):
        un = getattr(entity, "username", None) or None
        fn = getattr(entity, "first_name", "") or ""
        ln = getattr(entity, "last_name", "") or ""
        name = (fn + " " + ln).strip() or None
        return "user", entity.id, entity.access_hash, un, name
    return "unknown", 0, None, None, None


async def build_input_peer(client: TelegramClient, peer_type: str, peer_id: int, access_hash: int | None, username: str | None):
    from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

    if peer_type == "channel" and access_hash is not None:
        return InputPeerChannel(channel_id=peer_id, access_hash=access_hash)
    if peer_type == "chat":
        return InputPeerChat(chat_id=peer_id)
    if peer_type == "user" and access_hash is not None:
        return InputPeerUser(user_id=peer_id, access_hash=access_hash)
    if username:
        return await client.get_input_entity(username)
    return await client.get_input_entity(peer_id)
