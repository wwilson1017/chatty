"""Chatty — meeting transcription service.

Entry point is transcribe_file(), an async generator that yields progress
events (for SSE forwarding to the chat UI) followed by one final result:

    {"stage": str, "message": str, "percent": int | None}
    {"done": True, "transcript": str, "duration_seconds": float,
     "provider": str, "model": str, "input_tokens": int, "output_tokens": int}

Backend selection (pick_backend) reads the global credential store directly
rather than get_ai_provider(): the ACTIVE chat provider may be Anthropic,
which has no audio API — transcription uses whichever capable key exists.

- Google Gemini (api_key profile): whole file via the Gemini File API. No
  request-size chunking, handles multi-hour recordings, labels speakers.
- OpenAI (api_key profile): Whisper. Recordings beyond the API's 25 MB
  request cap are split into 10-minute MP3 segments with ffmpeg.

Raises TranscriptionError with a user-facing message when no capable
provider is configured or conversion/transcription fails.
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from core.agents.transcription.audio import (
    GEMINI_NATIVE_EXTENSIONS,
    SEGMENT_SECONDS,
    WHISPER_NATIVE_EXTENSIONS,
    ffmpeg_available,
    format_hms,
    probe_duration_seconds,
    segment_to_mp3,
    transcode_to_mp3,
)
from core.providers.credentials import CredentialStore

logger = logging.getLogger(__name__)

GEMINI_TRANSCRIBE_MODEL = "gemini-2.5-flash"
OPENAI_TRANSCRIBE_MODEL = "gpt-4o-transcribe"

# The OpenAI audio API's documented per-request cap is 25 MB; leave headroom
# for multipart overhead.
_WHISPER_MAX_BYTES = 24 * 1024 * 1024

# 6 h — generous for meetings; caps runaway transcription cost from a
# highly-compressed multi-hour recording (the 2 GB byte cap isn't a duration
# cap) and keeps the single process from being tied up for hours.
_MAX_DURATION_SECONDS = 6 * 3600
# Reject very large files whose duration we can't verify (no ffprobe) —
# fail closed rather than let an unbounded-length file through.
_FAILCLOSED_UNKNOWN_DURATION_BYTES = 500 * 1024 * 1024

_GEMINI_PROMPT = (
    "Transcribe this meeting recording verbatim.\n"
    "- Label distinct speakers as **Speaker 1**, **Speaker 2**, etc. "
    "(use real names only if speakers clearly introduce themselves).\n"
    "- Start each speaker turn with a [h:mm:ss] timestamp.\n"
    "- Preserve the spoken words faithfully; light cleanup of filler "
    "sounds (um, uh) is fine, but do not summarize or paraphrase.\n"
    "- Output ONLY the transcript — no preamble, no commentary."
)

NO_PROVIDER_MESSAGE = (
    "Transcription needs an OpenAI or Google Gemini API key. "
    "Add one in Settings → AI Providers, then try again."
)

# genai.configure() mutates process-global SDK state (the default gRPC
# client); this lock serializes all Gemini SDK work so two concurrent
# transcriptions can't have one request's configure()/upload reset the
# global client out from under the other's in-flight call.
#
# NOTE: this only serializes transcription-vs-transcription. google_provider.py
# (every Google chat turn) and triage.py also call genai.configure() on the
# same global state WITHOUT this lock — not extended to them deliberately,
# since that would serialize every Google chat turn behind a multi-minute
# transcription. This is currently safe only because all callers share the
# one google:default api_key; if a user rotates their Google key mid-
# transcription, an in-flight get_file poll could 403.
_GEMINI_SDK_LOCK = asyncio.Lock()


class TranscriptionError(Exception):
    """Transcription failed; str(exc) is safe to show the user."""


def pick_backend() -> tuple[str, str] | None:
    """Return (provider, api_key) for transcription, or None if no capable key.

    Gemini is preferred: the File API takes multi-hour recordings whole (no
    ffmpeg chunking required) and its transcripts include speaker labels.
    Only api_key profiles qualify — OpenAI ChatGPT-OAuth tokens go through a
    chat-only proxy, and Google OAuth tokens aren't scoped for the File API.
    """
    profiles = CredentialStore().data.get("profiles", {})
    google = profiles.get("google:default", {})
    if google.get("type") == "api_key" and google.get("key"):
        return ("google", google["key"])
    openai_p = profiles.get("openai:default", {})
    if openai_p.get("type") == "api_key" and openai_p.get("key"):
        return ("openai", openai_p["key"])
    return None


def _fmt_offset(seconds: float) -> str:
    return format_hms(seconds)


async def _tick_while_running(task: asyncio.Task, stage: str, message: str):
    """Yield elapsed-time progress events every few seconds until task finishes.

    Keeps the SSE stream alive through proxies during multi-minute API calls.
    On early close (client disconnect → CancelledError at a yield) the finally
    cancels the still-running task so it doesn't leak or log an unretrieved
    exception. (For asyncio.to_thread the OS thread can't be preempted, but the
    task state is cleared and the generator exits cleanly.)
    """
    start = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=5)
            if done:
                return
            elapsed = int(time.monotonic() - start)
            yield {
                "stage": stage,
                "message": f"{message} ({elapsed // 60}:{elapsed % 60:02d} elapsed)",
                "percent": None,
            }
    finally:
        if not task.done():
            task.cancel()


async def transcribe_file(path: Path, filename: str):
    """Async generator: progress events, then a final {"done": True, ...} event."""
    backend = pick_backend()
    if not backend:
        raise TranscriptionError(NO_PROVIDER_MESSAGE)
    provider, api_key = backend

    started = time.monotonic()
    duration = await asyncio.to_thread(probe_duration_seconds, path)

    if duration and duration > _MAX_DURATION_SECONDS:
        raise TranscriptionError(
            f"This recording is about {int(duration // 3600)}h long, over the "
            f"{_MAX_DURATION_SECONDS // 3600}-hour limit. Split it into shorter recordings.")
    elif duration is None and path.stat().st_size > _FAILCLOSED_UNKNOWN_DURATION_BYTES:
        raise TranscriptionError(
            "This recording is very large and its length couldn't be verified. "
            "Please upload a shorter recording or one in a standard format (MP3/WAV/M4A).")

    if provider == "google":
        gen = _transcribe_gemini(path, filename, api_key, duration)
    else:
        gen = _transcribe_whisper(path, filename, api_key, duration)

    async for event in gen:
        if event.get("done"):
            event["provider"] = provider
            event["processing_ms"] = int((time.monotonic() - started) * 1000)
            if not event.get("duration_seconds") and duration:
                event["duration_seconds"] = duration
        yield event


# ---------------------------------------------------------------------------
# Gemini — whole-file via the File API
# ---------------------------------------------------------------------------

async def _transcribe_gemini(path: Path, filename: str, api_key: str,
                             duration: float | None):
    try:
        import google.generativeai as genai
    except ImportError:
        raise TranscriptionError("google-generativeai package not installed")

    # ponytail: genai.configure() mutates process-global SDK state (the
    # default gRPC client), so this lock serializes Gemini transcriptions to
    # keep a concurrent request's configure()/upload from corrupting the
    # shared global client mid-flight. This means concurrent Gemini
    # transcriptions queue behind each other — fine for single-user; migrate
    # to a per-request genai.Client if the new SDK is adopted.
    async with _GEMINI_SDK_LOCK:
        genai.configure(api_key=api_key)
        ext = filename.rsplit(".", 1)[-1].lower()

        with tempfile.TemporaryDirectory(prefix="chatty-transcribe-") as tmp:
            upload_path = path
            # Normalize containers the File API doesn't take as audio (m4a, mp4,
            # webm, …). Also strips video tracks, which shrinks the upload.
            if ext not in GEMINI_NATIVE_EXTENSIONS:
                if not ffmpeg_available():
                    raise TranscriptionError(
                        f"'.{ext}' recordings need ffmpeg to convert for Gemini, "
                        "and ffmpeg isn't installed. Install ffmpeg, or upload "
                        "MP3/WAV/OGG/FLAC instead."
                    )
                yield {"stage": "converting", "message": f"Converting {filename} to MP3…", "percent": None}
                upload_path = Path(tmp) / "audio.mp3"
                transcode_task = asyncio.create_task(
                    asyncio.to_thread(transcode_to_mp3, path, upload_path)
                )
                async for tick in _tick_while_running(
                    transcode_task, "converting", f"Converting {filename} to MP3"
                ):
                    yield tick
                transcode_task.result()

            yield {"stage": "uploading", "message": f"Uploading {filename} to Gemini…", "percent": None}
            upload_task = asyncio.create_task(
                asyncio.to_thread(
                    genai.upload_file, str(upload_path), mime_type="audio/mp3"
                    if upload_path.suffix == ".mp3" else None,
                )
            )
            async for tick in _tick_while_running(
                upload_task, "uploading", f"Uploading {filename} to Gemini"
            ):
                yield tick
            audio_file = upload_task.result()

            try:
                # File API processes the upload before it's usable.
                waited = 0.0
                while audio_file.state.name == "PROCESSING":
                    if waited > 600:
                        raise TranscriptionError("Gemini took too long to process the upload")
                    yield {
                        "stage": "processing",
                        "message": f"Gemini is processing {filename}… ({int(waited)}s)",
                        "percent": None,
                    }
                    await asyncio.sleep(2)
                    waited += 2
                    audio_file = await asyncio.to_thread(genai.get_file, audio_file.name)
                if audio_file.state.name != "ACTIVE":
                    raise TranscriptionError(f"Gemini rejected the upload (state: {audio_file.state.name})")

                def _generate():
                    model = genai.GenerativeModel(GEMINI_TRANSCRIBE_MODEL)
                    return model.generate_content(
                        [audio_file, _GEMINI_PROMPT],
                        generation_config={"temperature": 0.1, "max_output_tokens": 65536},
                        request_options={"timeout": 3600},
                    )

                task = asyncio.create_task(asyncio.to_thread(_generate))
                async for tick in _tick_while_running(task, "transcribing", f"Transcribing {filename} with Gemini"):
                    yield tick
                response = task.result()

                transcript = (response.text or "").strip()
                if not transcript:
                    raise TranscriptionError("Gemini returned an empty transcript")

                cand = (getattr(response, "candidates", None) or [None])[0]
                finish = getattr(cand, "finish_reason", None)
                if finish is not None and str(getattr(finish, "name", finish)).upper() in ("MAX_TOKENS", "2"):
                    transcript += (
                        "\n\n[⚠️ Transcript truncated: the recording exceeded the "
                        "transcription model's output limit; it may be longer than "
                        "captured here.]"
                    )
                    logger.warning("Gemini transcript truncated (finish_reason=%s)", finish)

                usage = getattr(response, "usage_metadata", None)
                yield {
                    "done": True,
                    "transcript": transcript,
                    "duration_seconds": duration or 0.0,
                    "model": GEMINI_TRANSCRIBE_MODEL,
                    "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                    "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                }
            finally:
                try:
                    await asyncio.to_thread(genai.delete_file, audio_file.name)
                except Exception:
                    logger.debug("Gemini file cleanup failed", exc_info=True)


# ---------------------------------------------------------------------------
# OpenAI Whisper — segmented for the 25 MB request cap
# ---------------------------------------------------------------------------

async def _transcribe_whisper(path: Path, filename: str, api_key: str,
                              duration: float | None):
    import openai

    client = openai.AsyncOpenAI(api_key=api_key)
    ext = filename.rsplit(".", 1)[-1].lower()
    size = path.stat().st_size

    needs_split = (
        size > _WHISPER_MAX_BYTES
        or (duration or 0) > SEGMENT_SECONDS
        or ext not in WHISPER_NATIVE_EXTENSIONS  # convert anything Whisper won't accept directly
    )

    with tempfile.TemporaryDirectory(prefix="chatty-transcribe-") as tmp:
        if needs_split:
            if not ffmpeg_available():
                raise TranscriptionError(
                    "This recording is too long for a single Whisper request "
                    "and ffmpeg isn't installed to split it. Install ffmpeg, "
                    "or add a Google Gemini API key (handles long recordings "
                    "without ffmpeg)."
                )
            yield {"stage": "converting", "message": f"Splitting {filename} into segments…", "percent": 0}
            segment_task = asyncio.create_task(asyncio.to_thread(segment_to_mp3, path, Path(tmp)))
            async for tick in _tick_while_running(
                segment_task, "converting", f"Splitting {filename} into segments"
            ):
                yield tick
            chunks = segment_task.result()
        else:
            chunks = [path]

        parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        for i, chunk in enumerate(chunks):
            yield {
                "stage": "transcribing",
                "message": f"Transcribing {filename} — segment {i + 1} of {len(chunks)}…",
                "percent": int(i / len(chunks) * 100),
            }

            async def _call(p=chunk):
                with open(p, "rb") as fh:
                    return await client.audio.transcriptions.create(
                        model=OPENAI_TRANSCRIBE_MODEL,
                        file=fh,
                    )

            task = asyncio.create_task(_call())
            async for tick in _tick_while_running(
                task, "transcribing",
                f"Transcribing {filename} — segment {i + 1} of {len(chunks)}",
            ):
                yield tick
            try:
                result = task.result()
            except openai.APIError as e:
                raise TranscriptionError(f"OpenAI transcription failed: {getattr(e, 'message', e)}")

            text = (result.text or "").strip()
            if text:
                if len(chunks) > 1:
                    # Segments are fixed-length, so offsets are exact
                    parts.append(f"[{_fmt_offset(i * SEGMENT_SECONDS)}]\n{text}")
                else:
                    parts.append(text)
            usage = getattr(result, "usage", None)
            input_tokens += getattr(usage, "input_tokens", 0) or 0
            output_tokens += getattr(usage, "output_tokens", 0) or 0

        transcript = "\n\n".join(parts).strip()
        if not transcript:
            raise TranscriptionError("Transcription came back empty (is the recording silent?)")

        yield {
            "done": True,
            # Duration comes from ffprobe (the `duration` arg); when ffprobe
            # is unavailable the recording was small enough for one request
            # and duration stays 0 (usage row simply prices as 0 minutes).
            "transcript": transcript,
            "duration_seconds": duration or 0.0,
            "model": OPENAI_TRANSCRIBE_MODEL,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }


# ---------------------------------------------------------------------------
# Live-meeting chunks — small standalone files, transcribed one at a time
# ---------------------------------------------------------------------------

_CHUNK_PROMPT = (
    "Transcribe this audio segment verbatim. Output only the transcript "
    "text — no timestamps, no speaker labels, no commentary. If the "
    "segment is silent or unintelligible, output nothing."
)


def pick_chunk_backend() -> tuple[str, str] | None:
    """Return (provider, api_key) for live chunk transcription, or None.

    Preference is inverted vs pick_backend(): for a ~20 s chunk OpenAI is one
    cheap REST call (webm/mp4 native, no ffmpeg), while Gemini needs a
    transcode plus an SDK call serialized behind _GEMINI_SDK_LOCK.
    """
    profiles = CredentialStore().data.get("profiles", {})
    openai_p = profiles.get("openai:default", {})
    if openai_p.get("type") == "api_key" and openai_p.get("key"):
        return ("openai", openai_p["key"])
    google = profiles.get("google:default", {})
    if google.get("type") == "api_key" and google.get("key"):
        return ("google", google["key"])
    return None


async def transcribe_chunk(path: Path, *, ext: str,
                           client_duration_s: float | None = None,
                           prev_tail: str = "") -> dict:
    """Transcribe one short live-meeting chunk.

    Returns {"text", "model", "provider", "input_tokens", "output_tokens",
    "duration_seconds"}. Empty text is a normal result (silence), not an
    error. Raises TranscriptionError on provider/conversion failure.
    """
    backend = pick_chunk_backend()
    if backend is None:
        raise TranscriptionError(NO_PROVIDER_MESSAGE)
    provider, api_key = backend

    duration = probe_duration_seconds(path) or client_duration_s or 0.0

    if provider == "openai":
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        with tempfile.TemporaryDirectory(prefix="chatty-chunk-") as tmp:
            send_path = path
            if ext not in WHISPER_NATIVE_EXTENSIONS:
                if not ffmpeg_available():
                    raise TranscriptionError(
                        f"'.{ext}' chunks need ffmpeg to convert, and ffmpeg isn't installed."
                    )
                send_path = await asyncio.to_thread(
                    transcode_to_mp3, path, Path(tmp) / "chunk.mp3"
                )
            try:
                with open(send_path, "rb") as fh:
                    result = await client.audio.transcriptions.create(
                        model=OPENAI_TRANSCRIBE_MODEL,
                        file=fh,
                        # Boundary continuity: the tail of the prior chunk's
                        # text biases decoding at the seam.
                        **({"prompt": prev_tail[-200:]} if prev_tail else {}),
                    )
            except openai.APIError as e:
                raise TranscriptionError(f"OpenAI transcription failed: {getattr(e, 'message', e)}")
        usage = getattr(result, "usage", None)
        return {
            "text": (result.text or "").strip(),
            "model": OPENAI_TRANSCRIBE_MODEL,
            "provider": "openai",
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "duration_seconds": duration,
        }

    # Gemini: inline audio bytes in generate_content — no File API, no polling.
    try:
        import google.generativeai as genai
    except ImportError:
        raise TranscriptionError("google-generativeai package not installed")

    with tempfile.TemporaryDirectory(prefix="chatty-chunk-") as tmp:
        send_path = path
        if ext not in GEMINI_NATIVE_EXTENSIONS:
            if not ffmpeg_available():
                raise TranscriptionError(
                    f"'.{ext}' chunks need ffmpeg to convert for Gemini, and ffmpeg isn't installed."
                )
            send_path = await asyncio.to_thread(
                transcode_to_mp3, path, Path(tmp) / "chunk.mp3"
            )
        audio_bytes = send_path.read_bytes()
        mime = "audio/mp3" if send_path.suffix == ".mp3" else f"audio/{ext}"

        def _generate():
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(GEMINI_TRANSCRIBE_MODEL)
            return model.generate_content(
                [{"mime_type": mime, "data": audio_bytes}, _CHUNK_PROMPT],
                generation_config={"temperature": 0.1},
                request_options={"timeout": 120},
            )

        # Same process-global SDK state caveat as _transcribe_gemini; held
        # across the to_thread call so a concurrent whole-file transcription
        # can't reconfigure mid-request.
        async with _GEMINI_SDK_LOCK:
            try:
                response = await asyncio.to_thread(_generate)
            except Exception as e:
                raise TranscriptionError(f"Gemini transcription failed: {e}")

    usage = getattr(response, "usage_metadata", None)
    try:
        text = (response.text or "").strip()
    except Exception:
        text = ""  # blocked/empty candidates — treat as silence
    return {
        "text": text,
        "model": GEMINI_TRANSCRIBE_MODEL,
        "provider": "google",
        "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
        "duration_seconds": duration,
    }
