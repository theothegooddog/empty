"""Reading and writing audio files.

Backends, tried in order:

1. ``soundfile`` (libsndfile): WAV, FLAC, OGG/Vorbis, OPUS, MP3, AIFF, ...
2. ``ffmpeg`` on the PATH: anything ffmpeg can decode (M4A, AAC, video files, ...)
3. The standard-library ``wave`` module: PCM WAV only.

All functions work with float32 arrays of shape ``(frames, channels)``
scaled to the range [-1.0, 1.0].
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave

import numpy as np

try:  # pragma: no cover - depends on the environment
    import soundfile as _sf
except (ImportError, OSError):  # OSError: libsndfile missing
    _sf = None


class AudioIOError(IOError):
    """Raised when an audio file can't be read or written."""


def read(path: str | os.PathLike) -> tuple[np.ndarray, int]:
    """Read an audio file. Returns ``(samples, sample_rate)``."""
    path = os.fspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    errors = []
    if _sf is not None:
        try:
            data, sr = _sf.read(path, dtype="float32", always_2d=True)
            return data, int(sr)
        except Exception as e:  # unsupported format, fall through
            errors.append(f"soundfile: {e}")

    if shutil.which("ffmpeg"):
        try:
            return _read_ffmpeg(path)
        except Exception as e:
            errors.append(f"ffmpeg: {e}")

    try:
        return _read_wave(path)
    except Exception as e:
        errors.append(f"wave: {e}")

    raise AudioIOError(f"Could not read {path!r}:\n  " + "\n  ".join(errors))


def write(path: str | os.PathLike, samples: np.ndarray, sample_rate: int,
          subtype: str | None = None) -> None:
    """Write samples to ``path``. The format is chosen from the file extension.

    ``subtype`` is passed to soundfile (e.g. ``"PCM_16"``, ``"PCM_24"``,
    ``"FLOAT"``). Without soundfile only 16-bit PCM WAV can be written.
    """
    path = os.fspath(path)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, None]

    if _sf is not None:
        try:
            _sf.write(path, samples, sample_rate, subtype=subtype)
            return
        except Exception as e:
            if not path.lower().endswith(".wav"):
                raise AudioIOError(f"Could not write {path!r}: {e}") from e

    if not path.lower().endswith(".wav"):
        raise AudioIOError(
            "Writing formats other than WAV requires the 'soundfile' package")
    _write_wave(path, samples, sample_rate)


def _read_wave(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())

    if width == 1:  # 8-bit WAV is unsigned
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / (1 << 23)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / (1 << 31)
    else:
        raise AudioIOError(f"Unsupported WAV sample width: {width} bytes")
    return data.reshape(-1, channels), sr


def _write_wave(path: str, samples: np.ndarray, sample_rate: int) -> None:
    ints = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(ints.tobytes())


def _read_ffmpeg(path: str) -> tuple[np.ndarray, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True)
    sr, channels = (int(v) for v in probe.stdout.strip().split(",")[:2])
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True, check=True)
    data = np.frombuffer(out.stdout, dtype="<f4").copy()
    return data.reshape(-1, channels), sr
