"""Chatty — ffmpeg helpers for meeting audio transcription.

Pure-subprocess helpers (no Python audio dependencies): probe duration,
normalize arbitrary audio/video containers to mono MP3, and split long
recordings into Whisper-sized segments. ffmpeg ships in the Docker image;
local dev installs may lack it, so callers must check ffmpeg_available()
and degrade with a clear message instead of crashing.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions accepted as meeting recordings. Video containers are included
# because Zoom/Meet recordings are usually .mp4/.webm — only the audio track
# is used.
AUDIO_EXTENSIONS = {
    "mp3", "m4a", "wav", "ogg", "oga", "opus", "flac", "aac", "aiff",
    "mp4", "mov", "webm", "mpga", "mpeg",
}

# Containers Gemini's File API accepts as audio without conversion.
GEMINI_NATIVE_EXTENSIONS = {"mp3", "wav", "aac", "ogg", "flac", "aiff"}

# Formats OpenAI's audio API accepts natively: flac, mp3, mp4, mpeg, mpga,
# m4a, ogg, wav, webm (https://platform.openai.com/docs/guides/speech-to-text).
# Anything else in AUDIO_EXTENSIONS (oga, opus, aac, aiff, mov) must be
# converted with ffmpeg before it's sent to Whisper.
WHISPER_NATIVE_EXTENSIONS = {
    "flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm",
}

# 10-minute segments at 48 kbps mono ≈ 3.6 MB — comfortably under the
# Whisper API's 25 MB per-request cap even with container overhead.
SEGMENT_SECONDS = 600

_TRANSCODE_ARGS = ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k"]


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def format_hms(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS (e.g. 3723 -> "1:02:03")."""
    s = int(seconds or 0)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"{cmd[0]} failed: {' / '.join(tail) or 'unknown error'}")
    return proc


def probe_duration_seconds(path: Path) -> float | None:
    """Return the recording's duration via ffprobe, or None if unavailable."""
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = _run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ], timeout=60)
        duration = json.loads(proc.stdout).get("format", {}).get("duration")
        return float(duration) if duration else None
    except Exception as e:
        logger.warning("ffprobe failed for %s: %s", path.name, e)
        return None


def transcode_to_mp3(src: Path, dst: Path) -> Path:
    """Convert any audio/video file to 16 kHz mono MP3 (drops video track)."""
    _run(["ffmpeg", "-y", "-i", str(src), *_TRANSCODE_ARGS, str(dst)])
    return dst


def concat_audio(chunks: list[Path], dst: Path) -> Path:
    """Stitch ordered recording chunks into one 16 kHz mono MP3.

    Normalize-first: the concat demuxer requires matching codecs/timebases
    across *inputs*, so each chunk is transcoded to MP3 before concatenation
    (re-encoding only the output would not make mixed webm/mp4 chunks safe).
    Chunks already in .mp3 are used as-is.
    """
    if not chunks:
        raise RuntimeError("no chunks to concatenate")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="chatty-concat-") as tmp:
        tmp_dir = Path(tmp)
        normalized: list[Path] = []
        for i, chunk in enumerate(chunks):
            if chunk.suffix.lower() == ".mp3":
                normalized.append(chunk)
            else:
                normalized.append(transcode_to_mp3(chunk, tmp_dir / f"norm-{i:05d}.mp3"))
        list_file = tmp_dir / "concat.txt"
        # concat-demuxer list format; paths are program-generated (no quotes)
        list_file.write_text(
            "".join(f"file '{p}'\n" for p in normalized), encoding="utf-8",
        )
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(dst)])
    return dst


def segment_to_mp3(src: Path, dst_dir: Path, segment_seconds: int = SEGMENT_SECONDS) -> list[Path]:
    """Split a recording into sequential mono MP3 segments for Whisper."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    pattern = dst_dir / "chunk-%04d.mp3"
    _run([
        "ffmpeg", "-y", "-i", str(src), *_TRANSCODE_ARGS,
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1", str(pattern),
    ])
    chunks = sorted(dst_dir.glob("chunk-*.mp3"))
    if not chunks:
        raise RuntimeError("ffmpeg produced no segments")
    return chunks
