"""The :class:`Audio` type: an immutable buffer of samples plus a sample rate."""

from __future__ import annotations

import os
from fractions import Fraction
from typing import TYPE_CHECKING, Iterator

import numpy as np
from scipy import signal

from . import io as _io
from .player import Player, _sounddevice

if TYPE_CHECKING:
    from .effects import Effect

DEFAULT_SAMPLE_RATE = 44100


def db_to_gain(db: float) -> float:
    return 10.0 ** (db / 20.0)


def gain_to_db(gain: float) -> float:
    return -np.inf if gain <= 0 else 20.0 * np.log10(gain)


class Audio:
    """A clip of audio.

    Samples are stored as float32 in ``(frames, channels)`` layout, nominally
    in [-1.0, 1.0]. ``Audio`` objects are immutable: every operation and
    effect returns a new ``Audio``, so you can chain freely::

        song = Audio.load("song.wav")
        louder = song.gain(6)
        wet = song.ApplyEffect(effects.Reverb(20))
        clip = song.slice(10, 20).fade_in(0.5).fade_out(0.5)

    Indexing works on frames: ``song[1000]`` is one frame (an array with one
    value per channel) and ``song[1000:2000]`` is a new ``Audio``.
    """

    __slots__ = ("_samples", "_sample_rate")

    def __init__(self, samples=None, sample_rate: int = DEFAULT_SAMPLE_RATE):
        if samples is None:
            samples = np.zeros((0, 1), dtype=np.float32)
        arr = np.array(samples, dtype=np.float32)  # always a private copy
        if arr.ndim == 1:
            arr = arr[:, None]
        elif arr.ndim != 2:
            raise ValueError(f"samples must be 1-D or 2-D (frames, channels), got shape {arr.shape}")
        if arr.shape[1] == 0:
            raise ValueError("audio must have at least one channel")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        arr.flags.writeable = False
        self._samples = arr
        self._sample_rate = int(sample_rate)

    @classmethod
    def _wrap(cls, arr: np.ndarray, sample_rate: int) -> "Audio":
        """Build an Audio from an array we own, skipping the defensive copy."""
        obj = cls.__new__(cls)
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        arr.flags.writeable = False
        obj._samples = arr
        obj._sample_rate = int(sample_rate)
        return obj

    # ---- construction -----------------------------------------------------

    @classmethod
    def load(cls, path: str | os.PathLike, *, sample_rate: int | None = None,
             mono: bool = False) -> "Audio":
        """Load an audio file (WAV, FLAC, OGG, MP3, ... see :mod:`pyaudiofx.io`).

        Optionally resample to ``sample_rate`` and/or mix down to ``mono``.
        """
        data, sr = _io.read(path)
        audio = cls._wrap(data, sr)
        if mono:
            audio = audio.to_mono()
        if sample_rate is not None and sample_rate != sr:
            audio = audio.resample(sample_rate)
        return audio

    @classmethod
    def from_samples(cls, samples, sample_rate: int = DEFAULT_SAMPLE_RATE) -> "Audio":
        """Create audio from an array of samples.

        Float arrays are taken as-is; integer arrays (e.g. int16 PCM) are
        scaled to [-1, 1].
        """
        arr = np.asarray(samples)
        if np.issubdtype(arr.dtype, np.integer):
            info = np.iinfo(arr.dtype)
            if info.min == 0:  # unsigned PCM is offset-binary
                arr = (arr.astype(np.float64) - (info.max + 1) / 2) / ((info.max + 1) / 2)
            else:
                arr = arr.astype(np.float64) / -float(info.min)
        return cls(arr, sample_rate)

    @classmethod
    def silence(cls, duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE,
                channels: int = 1) -> "Audio":
        return cls._wrap(np.zeros((int(round(duration * sample_rate)), channels)), sample_rate)

    @classmethod
    def tone(cls, frequency: float, duration: float, *, amplitude: float = 0.5,
             waveform: str = "sine", sample_rate: int = DEFAULT_SAMPLE_RATE,
             channels: int = 1) -> "Audio":
        """Generate a test tone. ``waveform``: sine, square, sawtooth or triangle."""
        t = np.arange(int(round(duration * sample_rate))) / sample_rate
        phase = 2 * np.pi * frequency * t
        if waveform == "sine":
            wave = np.sin(phase)
        elif waveform == "square":
            wave = signal.square(phase)
        elif waveform == "sawtooth":
            wave = signal.sawtooth(phase)
        elif waveform == "triangle":
            wave = signal.sawtooth(phase, width=0.5)
        else:
            raise ValueError(f"unknown waveform {waveform!r}")
        return cls._wrap(np.repeat((amplitude * wave)[:, None], channels, axis=1), sample_rate)

    @classmethod
    def noise(cls, duration: float, *, amplitude: float = 0.5, color: str = "white",
              sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1,
              seed: int | None = None) -> "Audio":
        """Generate noise. ``color``: white, pink or brown."""
        rng = np.random.default_rng(seed)
        n = int(round(duration * sample_rate))
        white = rng.standard_normal((n, channels))
        if color == "white":
            data = white
        elif color in ("pink", "brown"):
            spectrum = np.fft.rfft(white, axis=0)
            f = np.fft.rfftfreq(n)
            f[0] = f[1] if n > 1 else 1.0
            exponent = 0.5 if color == "pink" else 1.0
            data = np.fft.irfft(spectrum / (f ** exponent)[:, None], n=n, axis=0)
        else:
            raise ValueError(f"unknown noise color {color!r}")
        peak = np.max(np.abs(data)) if n else 1.0
        return cls._wrap(data / (peak or 1.0) * amplitude, sample_rate)

    @classmethod
    def record(cls, duration: float, *, sample_rate: int = DEFAULT_SAMPLE_RATE,
               channels: int = 1, device: int | str | None = None) -> "Audio":
        """Record from the default (or given) input device. Blocks until done."""
        sd = _sounddevice()
        data = sd.rec(int(round(duration * sample_rate)), samplerate=sample_rate,
                      channels=channels, dtype="float32", device=device)
        sd.wait()
        return cls._wrap(data, sample_rate)

    # ---- saving & playback ------------------------------------------------

    def save(self, path: str | os.PathLike, *, subtype: str | None = None) -> None:
        """Write to a file; the format comes from the extension (.wav, .flac, .ogg, ...)."""
        _io.write(path, self._samples, self._sample_rate, subtype=subtype)

    def play(self, *, blocking: bool = False, volume: float = 1.0, loop: bool = False,
             start: float = 0.0, end: float | None = None,
             device: int | str | None = None) -> Player:
        """Play through the speakers and return a :class:`Player` to control it.

        With ``blocking=True`` this returns after playback finishes.
        """
        player = Player(self, volume=volume, loop=loop, start=start, end=end, device=device)
        player.play()
        if blocking:
            try:
                player.wait()
            finally:
                player.stop()
        return player

    def player(self, **kwargs) -> Player:
        """Create a :class:`Player` without starting it."""
        return Player(self, **kwargs)

    # ---- raw access -------------------------------------------------------

    @property
    def samples(self) -> np.ndarray:
        """The sample data, shape ``(frames, channels)``. Read-only; use ``.copy()`` to modify."""
        return self._samples

    def to_numpy(self, *, copy: bool = True, layout: str = "frames_first") -> np.ndarray:
        """Samples as a (writable, by default) array.

        ``layout="channels_first"`` gives ``(channels, frames)``.
        """
        arr = self._samples.T if layout == "channels_first" else self._samples
        return arr.copy() if copy else arr

    def to_pcm(self, dtype=np.int16) -> np.ndarray:
        """Samples converted to integer PCM (clipped)."""
        info = np.iinfo(dtype)
        scaled = np.clip(self._samples, -1.0, 1.0) * info.max
        return np.round(scaled).astype(dtype)

    def channel(self, index: int) -> "Audio":
        """A single channel as mono audio."""
        return Audio._wrap(self._samples[:, index].copy(), self._sample_rate)

    def split_channels(self) -> list["Audio"]:
        return [self.channel(i) for i in range(self.channels)]

    @staticmethod
    def merge_channels(*channels: "Audio") -> "Audio":
        """Combine mono clips into one multichannel clip (padded to the longest)."""
        sr = channels[0].sample_rate
        mono = [c.resample(sr).to_mono()._samples[:, 0] for c in channels]
        n = max(len(c) for c in mono)
        out = np.zeros((n, len(mono)), dtype=np.float32)
        for i, c in enumerate(mono):
            out[:len(c), i] = c
        return Audio._wrap(out, sr)

    def frame_at(self, seconds: float) -> np.ndarray:
        """The frame (one value per channel) at a time in seconds."""
        return self._samples[self.time_to_frame(seconds)]

    def sample_at(self, seconds: float, channel: int = 0) -> float:
        return float(self._samples[self.time_to_frame(seconds), channel])

    def time_to_frame(self, seconds: float) -> int:
        return int(round(seconds * self._sample_rate))

    def frame_to_time(self, frame: int) -> float:
        return frame / self._sample_rate

    def times(self) -> np.ndarray:
        """Timestamp (seconds) of every frame, handy for plotting."""
        return np.arange(self.frames) / self._sample_rate

    def chunks(self, size: int | None = None, *, seconds: float | None = None,
               overlap: int = 0) -> Iterator[np.ndarray]:
        """Iterate over blocks of frames, e.g. for streaming or analysis."""
        if seconds is not None:
            size = max(1, int(round(seconds * self._sample_rate)))
        if not size or size <= 0:
            raise ValueError("give a positive chunk size or seconds")
        if not 0 <= overlap < size:
            raise ValueError("overlap must be >= 0 and smaller than the chunk size")
        for i in range(0, self.frames, size - overlap):
            yield self._samples[i:i + size]
            if i + size >= self.frames:
                break

    # ---- properties -------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._samples.shape[1]

    @property
    def frames(self) -> int:
        return self._samples.shape[0]

    @property
    def duration(self) -> float:
        """Length in seconds."""
        return self.frames / self._sample_rate

    @property
    def peak(self) -> float:
        """Largest absolute sample value."""
        return float(np.max(np.abs(self._samples))) if self.frames else 0.0

    @property
    def peak_db(self) -> float:
        return gain_to_db(self.peak)

    @property
    def rms(self) -> float:
        """Root-mean-square level over all channels."""
        return float(np.sqrt(np.mean(np.square(self._samples, dtype=np.float64)))) if self.frames else 0.0

    @property
    def rms_db(self) -> float:
        return gain_to_db(self.rms)

    @property
    def is_mono(self) -> bool:
        return self.channels == 1

    def __len__(self) -> int:
        return self.frames

    def __getitem__(self, key):
        if isinstance(key, slice):
            return Audio._wrap(self._samples[key].copy(), self._sample_rate)
        return self._samples[key]

    def __repr__(self) -> str:
        return (f"<Audio {self.duration:.3f}s {self.sample_rate}Hz "
                f"{self.channels}ch peak={self.peak_db:.1f}dBFS>")

    # ---- effects ----------------------------------------------------------

    def apply_effect(self, effect: "Effect") -> "Audio":
        """Run an effect (or a chain of effects) and return the processed audio."""
        return effect.apply(self)

    ApplyEffect = apply_effect

    def apply(self, *effects: "Effect") -> "Audio":
        """Apply several effects in order."""
        out = self
        for fx in effects:
            out = fx.apply(out)
        return out

    def __or__(self, effect: "Effect") -> "Audio":
        """``audio | Reverb(20) | Gain(-3)``"""
        return self.apply_effect(effect)

    # ---- editing ----------------------------------------------------------

    def copy(self) -> "Audio":
        return Audio._wrap(self._samples.copy(), self._sample_rate)

    def slice(self, start: float = 0.0, end: float | None = None) -> "Audio":
        """The part between ``start`` and ``end`` seconds (negative values count from the end)."""
        s = self.time_to_frame(start if start >= 0 else self.duration + start)
        e = self.frames if end is None else self.time_to_frame(end if end >= 0 else self.duration + end)
        return self[max(s, 0):max(e, 0)]

    def gain(self, db: float) -> "Audio":
        """Change the level by ``db`` decibels."""
        return Audio._wrap(self._samples * db_to_gain(db), self._sample_rate)

    def scale(self, factor: float) -> "Audio":
        """Multiply every sample by ``factor``."""
        return Audio._wrap(self._samples * factor, self._sample_rate)

    def normalize(self, peak_db: float = -1.0) -> "Audio":
        """Scale so the loudest sample hits ``peak_db`` dBFS."""
        if self.peak == 0:
            return self.copy()
        return self.scale(db_to_gain(peak_db) / self.peak)

    def clip(self, limit: float = 1.0) -> "Audio":
        """Hard-clip samples to ±``limit``."""
        return Audio._wrap(np.clip(self._samples, -limit, limit), self._sample_rate)

    def reverse(self) -> "Audio":
        return Audio._wrap(self._samples[::-1].copy(), self._sample_rate)

    def invert(self) -> "Audio":
        """Flip the polarity."""
        return Audio._wrap(-self._samples, self._sample_rate)

    def to_mono(self) -> "Audio":
        if self.is_mono:
            return self
        return Audio._wrap(self._samples.mean(axis=1), self._sample_rate)

    def to_stereo(self) -> "Audio":
        return self.with_channels(2)

    def with_channels(self, channels: int) -> "Audio":
        """Convert to ``channels`` channels (mono is duplicated; otherwise down/up-mix)."""
        if channels == self.channels:
            return self
        if self.is_mono:
            return Audio._wrap(np.repeat(self._samples, channels, axis=1), self._sample_rate)
        if channels == 1:
            return self.to_mono()
        out = np.zeros((self.frames, channels), dtype=np.float32)
        keep = min(channels, self.channels)
        out[:, :keep] = self._samples[:, :keep]
        return Audio._wrap(out, self._sample_rate)

    def resample(self, sample_rate: int) -> "Audio":
        """Change the sample rate (high-quality polyphase filter; pitch is preserved)."""
        if sample_rate == self._sample_rate:
            return self
        ratio = Fraction(sample_rate, self._sample_rate).limit_denominator(1000)
        if self.frames == 0:
            return Audio._wrap(self._samples, sample_rate)
        data = signal.resample_poly(self._samples, ratio.numerator, ratio.denominator, axis=0)
        return Audio._wrap(data, sample_rate)

    def pad(self, start: float = 0.0, end: float = 0.0) -> "Audio":
        """Add silence before and/or after."""
        s, e = self.time_to_frame(start), self.time_to_frame(end)
        return Audio._wrap(np.pad(self._samples, ((s, e), (0, 0))), self._sample_rate)

    def trim_silence(self, threshold_db: float = -50.0, *, start: bool = True,
                     end: bool = True) -> "Audio":
        """Remove leading/trailing audio quieter than ``threshold_db``."""
        loud = np.flatnonzero(np.max(np.abs(self._samples), axis=1) > db_to_gain(threshold_db))
        if loud.size == 0:
            return self[0:0]
        s = loud[0] if start else 0
        e = loud[-1] + 1 if end else self.frames
        return self[s:e]

    def fade_in(self, seconds: float, curve: str = "linear") -> "Audio":
        n = min(self.time_to_frame(seconds), self.frames)
        data = self._samples.copy()
        data[:n] *= _fade_curve(n, curve)[:, None]
        return Audio._wrap(data, self._sample_rate)

    def fade_out(self, seconds: float, curve: str = "linear") -> "Audio":
        n = min(self.time_to_frame(seconds), self.frames)
        data = self._samples.copy()
        if n:
            data[-n:] *= _fade_curve(n, curve)[::-1, None]
        return Audio._wrap(data, self._sample_rate)

    def loop(self, times: int) -> "Audio":
        return self * times

    def _conform(self, other: "Audio") -> np.ndarray:
        """``other``'s samples at this clip's sample rate and channel count."""
        return other.resample(self._sample_rate).with_channels(self.channels)._samples

    def concat(self, *others: "Audio", crossfade: float = 0.0) -> "Audio":
        """Join clips end to end, optionally with an equal-power crossfade (seconds)."""
        out = self._samples
        for other in others:
            data = self._conform(other)
            n = min(self.time_to_frame(crossfade), len(out), len(data))
            if n:
                t = np.linspace(0, np.pi / 2, n, dtype=np.float32)[:, None]
                mixed = out[-n:] * np.cos(t) + data[:n] * np.sin(t)
                out = np.concatenate([out[:-n], mixed, data[n:]])
            else:
                out = np.concatenate([out, data])
        return Audio._wrap(out, self._sample_rate)

    def overlay(self, other: "Audio", *, at: float = 0.0, gain_db: float = 0.0) -> "Audio":
        """Mix ``other`` on top of this clip, starting ``at`` seconds in.

        The result is extended if ``other`` runs past the end.
        """
        data = self._conform(other) * db_to_gain(gain_db)
        offset = self.time_to_frame(at)
        if offset < 0:
            raise ValueError("'at' must be >= 0")
        n = max(self.frames, offset + len(data))
        out = np.zeros((n, self.channels), dtype=np.float32)
        out[:self.frames] = self._samples
        out[offset:offset + len(data)] += data
        return Audio._wrap(out, self._sample_rate)

    @staticmethod
    def mix(*clips: "Audio", normalize: bool = False) -> "Audio":
        """Sum several clips together (sample rate/channels follow the first clip)."""
        out = clips[0]
        for c in clips[1:]:
            out = out.overlay(c)
        return out.normalize() if normalize else out

    def __add__(self, other):
        """``a + b`` concatenates clips; ``a + 3`` adds 3 dB of gain."""
        if isinstance(other, Audio):
            return self.concat(other)
        if isinstance(other, (int, float)):
            return self.gain(other)
        return NotImplemented

    def __sub__(self, other):
        """``a - 6`` lowers the level by 6 dB."""
        if isinstance(other, (int, float)):
            return self.gain(-other)
        return NotImplemented

    def __mul__(self, times):
        """``a * 3`` repeats the clip three times."""
        if isinstance(times, int):
            return Audio._wrap(np.tile(self._samples, (max(times, 0), 1)), self._sample_rate)
        return NotImplemented

    def __and__(self, other: "Audio") -> "Audio":
        """``a & b`` mixes two clips together."""
        if isinstance(other, Audio):
            return self.overlay(other)
        return NotImplemented

    # ---- analysis ---------------------------------------------------------

    def spectrum(self, *, channel: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Magnitude spectrum of the whole clip: ``(frequencies_hz, magnitudes_db)``."""
        x = self._samples.mean(axis=1) if channel is None else self._samples[:, channel]
        window = np.hanning(len(x))
        mag = np.abs(np.fft.rfft(x * window)) / max(window.sum() / 2, 1e-12)
        return np.fft.rfftfreq(len(x), 1 / self._sample_rate), 20 * np.log10(mag + 1e-12)

    def spectrogram(self, *, window_size: int = 2048, hop: int = 512,
                    channel: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Short-time spectrum: ``(frequencies_hz, times_s, magnitudes_db)``."""
        x = self._samples.mean(axis=1) if channel is None else self._samples[:, channel]
        f, t, z = signal.stft(x, self._sample_rate, nperseg=window_size,
                              noverlap=window_size - hop)
        return f, t, 20 * np.log10(np.abs(z) + 1e-12)

    def envelope(self, window: float = 0.05) -> np.ndarray:
        """RMS level per window of ``window`` seconds (one value per window)."""
        size = max(1, self.time_to_frame(window))
        mono = self._samples.mean(axis=1)
        n = len(mono) // size
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        return np.sqrt(np.mean(mono[:n * size].reshape(n, size) ** 2, axis=1))

    def dominant_frequency(self) -> float:
        """Frequency (Hz) with the most energy, e.g. to find the pitch of a tone."""
        freqs, mags = self.spectrum()
        return float(freqs[np.argmax(mags[1:]) + 1]) if len(freqs) > 1 else 0.0


def _fade_curve(n: int, curve: str) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if curve == "linear":
        return t
    if curve == "exponential":
        return t ** 2
    if curve == "logarithmic":
        return np.sqrt(t)
    if curve in ("equal_power", "sine"):
        return np.sin(t * np.pi / 2)
    raise ValueError(f"unknown fade curve {curve!r}")
