import hashlib

from aiogram import Router, F
from aiogram.types import Message
import sentry_sdk

from config import settings
from bot.services.file_processor import handle_file


router = Router()


async def forward_and_transcribe(message: Message, file_type: str, duration: int, file_id: str, mime_type: str):
    """Forward message to admin and automatically transcribe it"""
    if not settings.ADMIN_ID:
        return
    
    try:
        # Forward to admin
        forwarded = await message.forward(settings.ADMIN_ID)
        
        # Add source info
        await forwarded.reply(
            f"From: {message.chat.title} (@{message.chat.username or message.chat.id or 'no username'})\n"
            f"User: {message.from_user.full_name or message.from_user.id or 'no username'}"
        )
        
        # Automatically transcribe
        hashed_user_id = hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
        sentry_sdk.set_user({"id": hashed_user_id})
        await handle_file(
            forwarded,
            hashed_user_id,
            file_type,
            duration,
            file_id,
            mime_type,
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.chat.id.in_(settings.FORWARD_CHAT_IDS))
    & (F.voice)
)
async def forward_voice_to_admin(message: Message):
    """Forward voice messages from specified chats to admin and transcribe"""
    await forward_and_transcribe(
        message,
        "voice",
        message.voice.duration,
        message.voice.file_id,
        message.voice.mime_type,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.chat.id.in_(settings.FORWARD_CHAT_IDS))
    & (F.audio)
)
async def forward_audio_to_admin(message: Message):
    """Forward audio messages from specified chats to admin and transcribe"""
    await forward_and_transcribe(
        message,
        "audio",
        message.audio.duration,
        message.audio.file_id,
        message.audio.mime_type,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"})
    & (F.chat.id.in_(settings.FORWARD_CHAT_IDS))
    & (F.video_note)
)
async def forward_video_note_to_admin(message: Message):
    """Forward video note messages from specified chats to admin and transcribe"""
    await forward_and_transcribe(
        message,
        "video_note",
        message.video_note.duration,
        message.video_note.file_id,
        "video/mp4",
    )
