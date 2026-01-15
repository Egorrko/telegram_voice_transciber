import asyncio
import tempfile
import logging
import sentry_sdk
import os
import subprocess
import io

from enum import StrEnum
from aiogram.utils.formatting import BlockQuote, Pre
from bot.bot_init import bot
from config import settings
import bot.messages as messages
from bot.services.transcribe import (
    transcription_client,
    fallback_transcription_client,
    generate_troll_response,
)
from bot.services import db
import time


class ProcessStatus(StrEnum):
    INIT = "Инициализация"
    DOWNLOAD = "Скачиваю файл..."
    CONVERT = "Достаю звук из видео..."
    TRANSCRIBE = "Распознаю..."
    SENDING = "Отправляю результат..."


async def convert_video_to_audio(file):
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(file.read())
        file_path = temp_file.name

        command = ["ffmpeg", "-i", file_path, "-vn", "-c:a", "copy", "-f", "adts", "-"]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        audio_bytes, stderr_bytes = await process.communicate()

        if process.returncode != 0:
            raise Exception(f"{stderr_bytes.decode()}")

        return io.BytesIO(audio_bytes), "audio/aac"


async def handle_file(
    message, hashed_user_id, file_type, file_duration, file_id, mime_type
):
    file_info = None
    current_step = ProcessStatus.INIT.name

    async def set_step(msg, step: ProcessStatus, notify_user=True):
        nonlocal current_step
        current_step = step.name
        try:
            if msg.text != step.value and notify_user:
                await msg.edit_text(step.value)
        except Exception:
            pass

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

        await set_step(msg, ProcessStatus.DOWNLOAD)
        file_info = await bot.get_file(file_id)
        file = await bot.download_file(file_info.file_path, timeout=60)

        if file_type == "video_note":
            await set_step(msg, ProcessStatus.CONVERT)
            audio_bytes, mime_type = await convert_video_to_audio(file)
        else:
            audio_bytes = file

        retries = 0
        start_time = time.time()
        transcript = None
        errors = []

        await set_step(msg, ProcessStatus.TRANSCRIBE)
        while retries < settings.MAX_RETRIES:
            try:
                transcript = await transcription_client.transcribe(
                    audio_bytes, mime_type
                )
                transcription_time = time.time() - start_time
                break
            except Exception as e:
                logging.error(f"Error during transcription attempt {retries}: {e}")
                audio_bytes.seek(0)
                retries += 1
                await msg.edit_text(
                    **BlockQuote(
                        f"Попытка {retries}/{settings.MAX_RETRIES}...\nЖдите {(settings.RETRY_DELAY * retries)} секунд..."
                    ).as_kwargs()
                )
                await asyncio.sleep((settings.RETRY_DELAY * retries))
                if retries == settings.MAX_RETRIES:
                    errors.append(e)

        if transcript is None and fallback_transcription_client:
            try:
                await msg.edit_text(**BlockQuote("Последняя попытка...").as_kwargs())
                audio_bytes.seek(0)
                transcript = await fallback_transcription_client.transcribe(
                    audio_bytes, mime_type
                )
                transcription_time = time.time() - start_time
            except Exception as e:
                logging.error(f"Error during fallback transcription: {e}")
                errors.append(e)

        if transcript is None:
            raise Exception(errors)

        if message.from_user and message.from_user.id in settings.TROLLING_USERS:
            try:
                troll_resp = await generate_troll_response(transcript, message.from_user.username)
                if troll_resp:
                    await message.reply(troll_resp)
            except Exception:
                pass

        await set_step(msg, ProcessStatus.SENDING, notify_user=False)
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
        logging.error(f"Error processing file: {e}")
        error_text = str(e) if str(e) else f"{type(e).__name__}"
        await msg.edit_text(
            **Pre(
                f"Ошибочка ({current_step}):\n{error_text}"[
                    : settings.MAX_MESSAGE_LENGTH
                ]
            ).as_kwargs()
        )

        sentry_sdk.set_context("pipeline", {"step": current_step})
        sentry_sdk.capture_exception(e)
        user, _ = await db.get_or_create_user(hashed_user_id)
        await db.insert_transcription_log(user, file_duration, -1)
    finally:
        if file_info and os.path.exists(file_info.file_path):
            os.remove(file_info.file_path)
