import asyncio
import tempfile
import sentry_sdk
import os
import subprocess
import io

from aiogram.utils.formatting import BlockQuote, Pre
from bot.bot_init import bot
from config import settings
import bot.messages as messages
from bot.services.transcribe import transcription_client
from bot.services import db
import time


async def convert_video_to_audio(file):
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(file.read())
        file_path = temp_file.name

        command = ["ffmpeg", "-i", file_path, '-vn', "-c:a", "copy", "-f", "adts", "-"]
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        audio_bytes, stderr_bytes = process.communicate()

        if process.returncode != 0:
            raise Exception(f"{stderr_bytes.decode()}")

        return io.BytesIO(audio_bytes), "audio/aac"


async def handle_file(
    message, hashed_user_id, file_type, file_duration, file_id, mime_type
):
    file_info = None
    try:
        user, check_result = await db.prepare_user_for_transcription(
            hashed_user_id, file_duration
        )
        if check_result == "exceeded":
            await message.reply(
                messages.limit_exceeded_message(
                    user.left_free_seconds + user.left_purchased_seconds,
                    settings.AVAILABLE_SECONDS,
                )
            )
            return
        elif check_result == "show_warning":
            await message.reply(
                messages.limit_warning_message(
                    user.left_free_seconds + user.left_purchased_seconds,
                    settings.AVAILABLE_SECONDS,
                )
            )
        msg = await message.reply("Распознаю...")

        file_info = await bot.get_file(file_id)
        file = await bot.download_file(file_info.file_path)

        if file_type == "video_note":
            audio_bytes, mime_type = await convert_video_to_audio(file)
        else:
            audio_bytes = file

        retries = 0
        start_time = time.time()
        while retries < settings.MAX_RETRIES:
            try:
                transcript = await transcription_client.transcribe(audio_bytes, mime_type)
                transcription_time = time.time() - start_time
            except Exception as e:
                retries += 1
                await msg.edit_text(**BlockQuote(f"Попытка {retries}/{settings.MAX_RETRIES}...").as_kwargs())
                await asyncio.sleep(settings.RETRY_DELAY)
                if retries == settings.MAX_RETRIES:
                    raise e

        if len(transcript) > settings.MAX_MESSAGE_LENGTH:
            await msg.edit_text(
                **BlockQuote(transcript[: settings.MAX_MESSAGE_LENGTH]).as_kwargs()
            )
            for i in range(
                settings.MAX_MESSAGE_LENGTH,
                len(transcript),
                settings.MAX_MESSAGE_LENGTH,
            ):
                await message.reply(
                    **BlockQuote(
                        transcript[i : i + settings.MAX_MESSAGE_LENGTH]
                    ).as_kwargs()
                )
        else:
            await msg.edit_text(**BlockQuote(transcript).as_kwargs())

        await db.process_user_transcription(user, file_duration, transcription_time)
        await db.insert_transcription_log(user, file_duration, transcription_time)
    except Exception as e:
        await msg.edit_text(
            **Pre(f"Ошибочка: {str(e)}"[: settings.MAX_MESSAGE_LENGTH]).as_kwargs()
        )
        sentry_sdk.capture_exception(e)
        user, _ = await db.get_or_create_user(hashed_user_id)
        await db.insert_transcription_log(user, file_duration, -1)
    finally:
        if file_info and os.path.exists(file_info.file_path):
            os.remove(file_info.file_path)
