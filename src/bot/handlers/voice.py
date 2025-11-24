import hashlib

from aiogram import Router, F
from aiogram.types import Message
import sentry_sdk

from bot.services.file_processor import handle_file
from config import settings


router = Router()


@router.message((F.chat.type == "private") & (F.voice))
async def handle_voice(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "voice",
        message.voice.duration,
        message.voice.file_id,
        message.voice.mime_type,
    )


@router.message((F.chat.type == "private") & (F.audio))
async def handle_audio(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "audio",
        message.audio.duration,
        message.audio.file_id,
        message.audio.mime_type,
    )


@router.message((F.chat.type == "private") & (F.video_note))
async def handle_video(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})

    await handle_file(
        message,
        hashed_user_id,
        "video_note",
        message.video_note.duration,
        message.video_note.file_id,
        "video/mp4",
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.reply_to_message[F.voice])
    & (F.text.contains(settings.BOT_USERNAME))
)
async def handle_voice_reply(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "voice",
        message.reply_to_message.voice.duration,
        message.reply_to_message.voice.file_id,
        message.reply_to_message.voice.mime_type,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.reply_to_message[F.audio])
    & (F.text.contains(settings.BOT_USERNAME))
)
async def handle_audio_reply(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "audio",
        message.reply_to_message.audio.duration,
        message.reply_to_message.audio.file_id,
        message.reply_to_message.audio.mime_type,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.chat.id.in_(settings.ALLOWED_CHAT_IDS))
    & (F.voice)
)
async def handle_group_message(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "voice",
        message.voice.duration,
        message.voice.file_id,
        message.voice.mime_type,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.chat.id.in_(settings.ALLOWED_CHAT_IDS))
    & (F.video_note)
)
async def handle_group_video_note(message: Message):
    hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    await handle_file(
        message,
        hashed_user_id,
        "video_note",
        message.video_note.duration,
        message.video_note.file_id,
        "video/mp4",
    )
