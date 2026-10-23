"""Real-time playback with transport controls (play / pause / seek / volume / loop)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

import numpy as np

if TYPE_CHECKING:
    from .audio import Audio


class PlaybackError(RuntimeError):
    """Raised when audio can't be played (no backend or no output device)."""


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as e:
        raise PlaybackError(
            "Playback needs the 'sounddevice' package: pip install sounddevice") from e
    except OSError as e:  # the PortAudio shared library is missing
        raise PlaybackError(
            "Playback needs the PortAudio library "
            "(Debian/Ubuntu: apt install libportaudio2, macOS: brew install portaudio)") from e
    return sd


class Player:
    """Plays an :class:`Audio` on an output device.

    Usually created with :meth:`Audio.play`::

        player = song.play()
        player.volume = 0.5
        player.seek(30)       # jump to 0:30
        player.pause()
        player.resume()
        player.loop = True
        player.wait()         # block until playback finishes

    All controls are thread-safe and take effect immediately.
    """

    def __init__(self, audio: "Audio", *, volume: float = 1.0, loop: bool = False,
                 start: float = 0.0, end: float | None = None,
                 device: int | str | None = None, blocksize: int = 0,
                 on_finished: Callable[["Player"], None] | None = None):
        self._audio = audio
        self._data = audio.samples  # (frames, channels) float32, read-only view
        self._sr = audio.sample_rate
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._done.set()
        self._stream = None
        self._pos = 0
        self._paused = False
        self.volume = volume
        self.loop = loop
        self.muted = False
        self.device = device
        self.blocksize = blocksize
        self.on_finished = on_finished
        self.set_region(start, end)
        self._pos = self._start

    # ---- transport --------------------------------------------------------

    def play(self) -> "Player":
        """Start (or restart, if it finished) playback. Returns ``self``."""
        with self._lock:
            if self._stream is not None and self._stream.active:
                self._paused = False
                return self
            if self._pos >= self._end:
                self._pos = self._start
            self._paused = False
        sd = _sounddevice()
        if self._stream is not None:  # a previous run that already finished
            self._stream.close()
            self._stream = None
        self._done.clear()
        try:
            self._stream = sd.OutputStream(
                samplerate=self._sr, channels=self._data.shape[1], dtype="float32",
                device=self.device, blocksize=self.blocksize,
                callback=self._callback, finished_callback=self._on_stream_finished)
            self._stream.start()
        except Exception as e:
            self._done.set()
            raise PlaybackError(f"Could not open an audio output stream: {e}") from e
        return self

    def pause(self) -> None:
        """Pause playback, keeping the current position."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        """Resume after :meth:`pause` (restarts the stream if it had already ended)."""
        if self._stream is not None and self._done.is_set():
            self.play()
            return
        with self._lock:
            self._paused = False

    def toggle(self) -> None:
        """Pause if playing, resume if paused."""
        if self.is_playing:
            self.pause()
        else:
            self.resume()

    def stop(self) -> None:
        """Stop playback and rewind to the start of the region."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.abort()
            stream.close()
        with self._lock:
            self._pos = self._start
            self._paused = False
        self._done.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until playback ends. Returns False if ``timeout`` expired first."""
        return self._done.wait(timeout)

    def seek(self, seconds: float) -> None:
        """Jump to an absolute position in seconds (clamped to the region)."""
        with self._lock:
            frame = int(round(seconds * self._sr))
            self._pos = min(max(frame, self._start), self._end)

    def skip(self, seconds: float) -> None:
        """Move forward (or back, if negative) by ``seconds``."""
        self.seek(self.position + seconds)

    def set_region(self, start: float = 0.0, end: float | None = None) -> None:
        """Restrict playback (and looping) to ``start``..``end`` seconds."""
        total = len(self._data)
        s = min(max(int(round(start * self._sr)), 0), total)
        e = total if end is None else min(max(int(round(end * self._sr)), s), total)
        with self._lock:
            self._start, self._end = s, e
            self._pos = min(max(self._pos, s), e)

    # ---- state ------------------------------------------------------------

    @property
    def position(self) -> float:
        """Current playback position in seconds."""
        return self._pos / self._sr

    @position.setter
    def position(self, seconds: float) -> None:
        self.seek(seconds)

    @property
    def duration(self) -> float:
        return len(self._data) / self._sr

    @property
    def progress(self) -> float:
        """Position within the region, from 0.0 to 1.0."""
        span = self._end - self._start
        return 1.0 if span == 0 else (self._pos - self._start) / span

    @property
    def is_playing(self) -> bool:
        return not self._done.is_set() and not self._paused

    @property
    def is_paused(self) -> bool:
        return not self._done.is_set() and self._paused

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        if value < 0:
            raise ValueError("volume must be >= 0")
        self._volume = float(value)

    @property
    def audio(self) -> "Audio":
        return self._audio

    # ---- audio thread -----------------------------------------------------

    def _fill(self, out: np.ndarray) -> bool:
        """Write the next ``len(out)`` frames into ``out``.

        Returns False once the end of the region is reached (and not looping).
        """
        with self._lock:
            if self._paused:
                out.fill(0)
                return True
            gain = 0.0 if self.muted else self._volume
            written = 0
            n_out = len(out)
            while written < n_out:
                remaining = self._end - self._pos
                if remaining <= 0:
                    if self.loop and self._end > self._start:
                        self._pos = self._start
                        continue
                    out[written:] = 0
                    return False
                n = min(n_out - written, remaining)
                np.multiply(self._data[self._pos:self._pos + n], gain, out=out[written:written + n])
                written += n
                self._pos += n
            return True

    def _callback(self, outdata, frames, time_info, status):  # pragma: no cover - needs a device
        if not self._fill(outdata):
            raise _sounddevice().CallbackStop

    def _on_stream_finished(self):  # pragma: no cover - needs a device
        self._done.set()
        if self.on_finished is not None:
            self.on_finished(self)

    def __enter__(self) -> "Player":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def __repr__(self) -> str:
        state = "playing" if self.is_playing else "paused" if self.is_paused else "stopped"
        return f"<Player {state} {self.position:.2f}/{self.duration:.2f}s volume={self.volume:g}>"
