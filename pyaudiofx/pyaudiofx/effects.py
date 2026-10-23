"""Audio effects.

Every effect is an object you configure once and apply to any number of clips::

    from pyaudiofx import Audio, effects

    song = Audio.load("song.wav")
    wet = song.ApplyEffect(effects.Reverb(20))

    # Chain effects with |  (or effects.Chain(...))
    radio = effects.HighPass(300) | effects.LowPass(3000) | effects.Distortion(12)
    out = song | radio

Writing your own effect means subclassing :class:`Effect` and implementing
``process(samples, sample_rate)``, where ``samples`` is a float64 array of
shape ``(frames, channels)`` that you may modify; return the processed array
(it may have a different length, e.g. to keep a reverb tail).
"""

from __future__ import annotations

import inspect
from fractions import Fraction
from typing import Callable, Iterable

import numpy as np
from scipy import ndimage, signal

from .audio import Audio, db_to_gain

__all__ = [
    "Effect", "Chain", "DryWet", "Custom",
    # level & utility
    "Gain", "Volume", "Normalize", "Reverse", "Invert", "FadeIn", "FadeOut",
    "Trim", "Pad", "Resample", "Mono", "Stereo",
    # space
    "Reverb", "ConvolutionReverb", "Delay", "Echo",
    # modulation
    "Chorus", "Flanger", "Vibrato", "Phaser", "Tremolo", "AutoPan",
    # stereo
    "Pan", "StereoWidth",
    # distortion
    "Distortion", "Overdrive", "HardClip", "Bitcrush",
    # filters & EQ
    "LowPass", "HighPass", "BandPass", "BandStop", "Notch",
    "PeakEQ", "LowShelf", "HighShelf", "Equalizer",
    # dynamics
    "Compressor", "Limiter", "NoiseGate",
    # time & pitch
    "Speed", "TimeStretch", "PitchShift",
]


# =============================================================================
# Base classes
# =============================================================================

class Effect:
    """Base class for all effects."""

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        raise NotImplementedError

    def apply(self, audio: Audio) -> Audio:
        data = np.array(audio.samples, dtype=np.float64)
        out = self.process(data, audio.sample_rate)
        return Audio._wrap(out, self.output_sample_rate(audio.sample_rate))

    __call__ = apply

    def output_sample_rate(self, sample_rate: int) -> int:
        """Override if the effect changes the sample rate."""
        return sample_rate

    def __or__(self, other: "Effect") -> "Chain":
        if not isinstance(other, Effect):
            return NotImplemented
        return Chain(self, other)

    __rshift__ = __or__

    def __repr__(self) -> str:
        params = inspect.signature(type(self).__init__).parameters
        shown = [f"{k}={getattr(self, k)!r}" for k in params
                 if k != "self" and hasattr(self, k)]
        return f"{type(self).__name__}({', '.join(shown)})"


class Chain(Effect):
    """Apply several effects in order: ``Chain(HighPass(80), Compressor(), Reverb(20))``."""

    def __init__(self, *effects: Effect):
        flat: list[Effect] = []
        for fx in effects:
            flat.extend(fx.effects if isinstance(fx, Chain) else [fx])
        self.effects = flat

    def apply(self, audio: Audio) -> Audio:
        for fx in self.effects:
            audio = fx.apply(audio)
        return audio

    __call__ = apply

    def process(self, samples, sample_rate):
        for fx in self.effects:
            if fx.output_sample_rate(sample_rate) != sample_rate:
                raise ValueError("use Chain.apply() for chains that change the sample rate")
            samples = fx.process(samples, sample_rate)
        return samples

    def __len__(self):
        return len(self.effects)

    def __iter__(self):
        return iter(self.effects)

    def __repr__(self):
        return " | ".join(map(repr, self.effects)) or "Chain()"


class DryWet(Effect):
    """Blend an effect with the original signal. ``mix`` is 0..100 (% wet)."""

    def __init__(self, effect: Effect, mix: float = 50):
        self.effect = effect
        self.mix = mix

    def process(self, samples, sample_rate):
        wet = self.effect.process(samples.copy(), sample_rate)
        n = max(len(samples), len(wet))
        dry = _fit(samples, n)
        wet = _fit(wet, n)
        m = _percent(self.mix)
        return dry * (1 - m) + wet * m


class Custom(Effect):
    """Wrap a function ``fn(samples, sample_rate) -> samples`` as an effect."""

    def __init__(self, fn: Callable[[np.ndarray, int], np.ndarray], name: str | None = None):
        self.fn = fn
        self.name = name or getattr(fn, "__name__", "custom")

    def process(self, samples, sample_rate):
        out = np.asarray(self.fn(samples, sample_rate), dtype=np.float64)
        return out[:, None] if out.ndim == 1 else out

    def __repr__(self):
        return f"Custom({self.name})"


# =============================================================================
# Helpers
# =============================================================================

def _percent(value: float) -> float:
    if not 0 <= value <= 100:
        raise ValueError(f"expected a percentage between 0 and 100, got {value}")
    return value / 100.0


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    """Pad with zeros or truncate to n frames."""
    if len(x) >= n:
        return x[:n]
    return np.pad(x, ((0, n - len(x)), (0, 0)))


def _ms(seconds: float, sample_rate: int) -> int:
    return int(round(seconds * sample_rate))


def _lfo(n: int, rate: float, sample_rate: int, phase: float = 0.0,
         shape: str = "sine") -> np.ndarray:
    """Low-frequency oscillator in [0, 1]."""
    t = np.arange(n) / sample_rate * rate + phase
    if shape == "sine":
        return 0.5 - 0.5 * np.cos(2 * np.pi * t)
    if shape == "triangle":
        return 1 - np.abs(2 * (t % 1) - 1)
    if shape == "square":
        return (t % 1 < 0.5).astype(np.float64)
    if shape == "sawtooth":
        return t % 1
    raise ValueError(f"unknown LFO shape {shape!r}")


def _modulated_delay(x: np.ndarray, delay: np.ndarray) -> np.ndarray:
    """Read ``x`` (1-D) delayed by a per-sample, fractional ``delay`` (in samples)."""
    idx = np.arange(len(x)) - delay
    return np.interp(idx, np.arange(len(x)), x, left=0.0)


def _peak_follower_db(level_db: np.ndarray, release_s: float, sample_rate: int,
                      range_db: float = 120.0) -> np.ndarray:
    """Instant-attack envelope with exponential release, fully vectorised.

    An exponential release is a straight line in dB, so
    ``env[n] = max_k(level[k] - (n - k) * slope)``, which is a running max.
    """
    slope = range_db / max(release_s * sample_rate, 1.0)  # dB per sample
    ramp = np.arange(len(level_db)) * slope
    return np.maximum.accumulate(level_db + ramp) - ramp


def _one_pole(x: np.ndarray, time_s: float, sample_rate: int) -> np.ndarray:
    """Smooth with a one-pole lowpass of the given time constant."""
    if time_s <= 0:
        return x
    a = np.exp(-1.0 / (time_s * sample_rate))
    zi = signal.lfilter_zi([1 - a], [1, -a]) * x[0] if len(x) else None
    if zi is None:
        return x
    y, _ = signal.lfilter([1 - a], [1, -a], x, zi=zi)
    return y


def _sos_apply(sos: np.ndarray, samples: np.ndarray) -> np.ndarray:
    return signal.sosfilt(sos, samples, axis=0)


# =============================================================================
# Level & utility
# =============================================================================

class Gain(Effect):
    """Change the level by ``db`` decibels."""

    def __init__(self, db: float):
        self.db = db

    def process(self, samples, sample_rate):
        return samples * db_to_gain(self.db)


class Volume(Effect):
    """Multiply the signal by ``factor`` (1.0 = unchanged, 0.5 = half)."""

    def __init__(self, factor: float):
        self.factor = factor

    def process(self, samples, sample_rate):
        return samples * self.factor


class Normalize(Effect):
    """Scale so the loudest sample reaches ``peak_db`` dBFS."""

    def __init__(self, peak_db: float = -1.0):
        self.peak_db = peak_db

    def process(self, samples, sample_rate):
        peak = np.max(np.abs(samples)) if samples.size else 0.0
        return samples if peak == 0 else samples * (db_to_gain(self.peak_db) / peak)


class Reverse(Effect):
    def process(self, samples, sample_rate):
        return samples[::-1]


class Invert(Effect):
    """Flip the polarity."""

    def process(self, samples, sample_rate):
        return -samples


class FadeIn(Effect):
    def __init__(self, seconds: float, curve: str = "linear"):
        self.seconds = seconds
        self.curve = curve

    def apply(self, audio):
        return audio.fade_in(self.seconds, self.curve)

    __call__ = apply

    def process(self, samples, sample_rate):
        return self.apply(Audio._wrap(samples, sample_rate)).samples.astype(np.float64)


class FadeOut(FadeIn):
    def apply(self, audio):
        return audio.fade_out(self.seconds, self.curve)

    __call__ = apply


class Trim(Effect):
    """Keep only ``start``..``end`` seconds."""

    def __init__(self, start: float = 0.0, end: float | None = None):
        self.start = start
        self.end = end

    def process(self, samples, sample_rate):
        s = _ms(self.start, sample_rate)
        e = None if self.end is None else _ms(self.end, sample_rate)
        return samples[s:e]


class Pad(Effect):
    """Add ``start`` / ``end`` seconds of silence."""

    def __init__(self, start: float = 0.0, end: float = 0.0):
        self.start = start
        self.end = end

    def process(self, samples, sample_rate):
        return np.pad(samples, ((_ms(self.start, sample_rate), _ms(self.end, sample_rate)), (0, 0)))


class Resample(Effect):
    """Convert to a new sample rate (pitch and tempo are preserved)."""

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def apply(self, audio):
        return audio.resample(self.sample_rate)

    __call__ = apply

    def output_sample_rate(self, sample_rate):
        return self.sample_rate


class Mono(Effect):
    def process(self, samples, sample_rate):
        return samples.mean(axis=1, keepdims=True)


class Stereo(Effect):
    def process(self, samples, sample_rate):
        if samples.shape[1] == 2:
            return samples
        mono = samples.mean(axis=1, keepdims=True)
        return np.repeat(mono, 2, axis=1)


# =============================================================================
# Space: reverb & delay
# =============================================================================

# Freeverb tunings (in samples at 44.1 kHz).
_COMB_TUNING = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASS_TUNING = (556, 441, 341, 225)
_STEREO_SPREAD = 23


def _feedback_comb(x: np.ndarray, delay: int, feedback: float, damp: float) -> np.ndarray:
    """Lowpass-feedback comb filter: y[n] = x[n] + g * lp(y[n - D]).

    Processed in blocks of D samples: each block only depends on the previous
    one, so the inner work is vectorised.
    """
    n = len(x)
    blocks = -(-n // delay)
    xp = np.zeros(blocks * delay)
    xp[:n] = x
    y = np.empty_like(xp)
    prev = np.zeros(delay)
    zi = np.zeros(1)
    for k in range(blocks):
        f, zi = signal.lfilter([1 - damp], [1, -damp], prev, zi=zi)
        prev = xp[k * delay:(k + 1) * delay] + feedback * f
        y[k * delay:(k + 1) * delay] = prev
    return y[:n]


def _allpass(x: np.ndarray, delay: int, feedback: float = 0.5) -> np.ndarray:
    """Freeverb allpass: v[n] = x[n] + g v[n-D];  y[n] = v[n-D] - x[n]."""
    n = len(x)
    blocks = -(-n // delay)
    xp = np.zeros(blocks * delay)
    xp[:n] = x
    y = np.empty_like(xp)
    v_prev = np.zeros(delay)
    for k in range(blocks):
        xk = xp[k * delay:(k + 1) * delay]
        y[k * delay:(k + 1) * delay] = v_prev - xk
        v_prev = xk + feedback * v_prev
    return y[:n]


def _freeverb_ir(sample_rate: int, room_size: float, damping: float,
                 spread: int, max_seconds: float) -> np.ndarray:
    scale = sample_rate / 44100
    feedback = 0.7 + 0.28 * room_size
    damp = 0.4 * damping
    longest = int((_COMB_TUNING[-1] + spread) * scale)
    rt60 = longest * np.log(1e-3) / np.log(feedback)  # samples to decay 60 dB
    n = int(min(rt60 * 1.1, max_seconds * sample_rate)) + longest
    impulse = np.zeros(n)
    impulse[0] = 1.0
    out = np.zeros(n)
    for d in _COMB_TUNING:
        out += _feedback_comb(impulse, max(1, int((d + spread) * scale)), feedback, damp)
    for d in _ALLPASS_TUNING:
        out = _allpass(out, max(1, int((d + spread) * scale)))
    out[0] = 0.0  # the comb sum starts with a direct copy of the input; remove it
    # Trim the inaudible tail.
    loud = np.flatnonzero(np.abs(out) > np.max(np.abs(out)) * 1e-4)
    out = out[:loud[-1] + 1] if loud.size else out[:1]
    return out / (np.sqrt(np.sum(out ** 2)) or 1.0)


class Reverb(Effect):
    """Algorithmic room reverb (Freeverb-style).

    Args:
        amount: wet level, 0-100 (``Reverb(20)`` = a light touch, ``Reverb(80)`` = cavernous).
        room_size: 0-1, bigger rooms ring longer.
        damping: 0-1, how quickly high frequencies die away.
        width: 0-1 stereo width of the reverb (stereo input only).
        pre_delay: seconds before the reverb starts.
        tail: keep the reverb tail after the clip ends (makes the clip longer).
    """

    def __init__(self, amount: float = 30, room_size: float = 0.5, damping: float = 0.5,
                 width: float = 1.0, pre_delay: float = 0.0, tail: bool = True,
                 max_decay: float = 10.0):
        _percent(amount)
        self.amount = amount
        self.room_size = float(np.clip(room_size, 0, 1))
        self.damping = float(np.clip(damping, 0, 1))
        self.width = float(np.clip(width, 0, 1))
        self.pre_delay = pre_delay
        self.tail = tail
        self.max_decay = max_decay
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def impulse_response(self, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
        """The (left, right) impulse responses used for ``sample_rate``."""
        if sample_rate not in self._cache:
            left = _freeverb_ir(sample_rate, self.room_size, self.damping, 0, self.max_decay)
            right = _freeverb_ir(sample_rate, self.room_size, self.damping,
                                 _STEREO_SPREAD, self.max_decay)
            n = max(len(left), len(right))
            pre = _ms(self.pre_delay, sample_rate)
            left = np.pad(left, (pre, n - len(left)))
            right = np.pad(right, (pre, n - len(right)))
            self._cache[sample_rate] = (left, right)
        return self._cache[sample_rate]

    def process(self, samples, sample_rate):
        n, ch = samples.shape
        left, right = self.impulse_response(sample_rate)
        # Alternate the two decorrelated responses across channels, then set width.
        wet = np.stack([signal.oaconvolve(samples[:, c], right if c % 2 else left)
                        for c in range(ch)], axis=1)
        if ch > 1:
            mid = wet.mean(axis=1, keepdims=True)
            wet = mid + (wet - mid) * self.width
        m = _percent(self.amount)
        dry_gain, wet_gain = np.cos(m * np.pi / 2), np.sin(m * np.pi / 2)
        out = wet * wet_gain
        out[:n] += samples * dry_gain
        return out if self.tail else out[:n]


class ConvolutionReverb(Effect):
    """Reverb from a recorded impulse response (a real room, plate, cabinet...).

    ``impulse`` is an :class:`Audio` or a path to an audio file.
    """

    def __init__(self, impulse: Audio | str, mix: float = 30, tail: bool = True):
        self.impulse = impulse if isinstance(impulse, Audio) else Audio.load(impulse)
        self.mix = mix
        self.tail = tail

    def process(self, samples, sample_rate):
        ir = self.impulse.resample(sample_rate).with_channels(samples.shape[1]).samples
        ir = ir / (np.sqrt(np.sum(ir.astype(np.float64) ** 2, axis=0)) + 1e-12)
        wet = np.stack([signal.oaconvolve(samples[:, c], ir[:, c])
                        for c in range(samples.shape[1])], axis=1)
        m = _percent(self.mix)
        out = wet * np.sin(m * np.pi / 2)
        out[:len(samples)] += samples * np.cos(m * np.pi / 2)
        return out if self.tail else out[:len(samples)]


class Delay(Effect):
    """Feedback delay / echo.

    Args:
        time: seconds between repeats.
        feedback: 0-1, how much of each repeat feeds the next.
        mix: 0-100, level of the echoes.
        ping_pong: bounce repeats between left and right (stereo input).
        tail: keep the echoes that run past the end of the clip.
    """

    def __init__(self, time: float = 0.35, feedback: float = 0.4, mix: float = 40,
                 ping_pong: bool = False, tail: bool = True):
        if not 0 <= feedback < 1:
            raise ValueError("feedback must be in [0, 1)")
        self.time = time
        self.feedback = feedback
        self.mix = mix
        self.ping_pong = ping_pong
        self.tail = tail

    def process(self, samples, sample_rate):
        n, ch = samples.shape
        d = max(1, _ms(self.time, sample_rate))
        repeats = 1 if self.feedback == 0 else int(np.ceil(np.log(1e-3) / np.log(self.feedback))) + 1
        repeats = max(1, min(repeats, 200))
        m = _percent(self.mix)
        out = np.zeros((n + d * repeats, ch))
        out[:n] += samples
        for k in range(1, repeats + 1):
            level = m * self.feedback ** (k - 1)
            src = samples[:, ::-1] if self.ping_pong and ch == 2 and k % 2 else samples
            out[k * d:k * d + n] += src * level
        return out if self.tail else out[:n]


Echo = Delay


# =============================================================================
# Modulation
# =============================================================================

class _ModDelay(Effect):
    def __init__(self, rate, depth, delay, mix, shape="sine"):
        self.rate = rate
        self.depth = depth
        self.delay = delay
        self.mix = mix
        self.shape = shape

    def process(self, samples, sample_rate):
        n, ch = samples.shape
        m = _percent(self.mix)
        out = np.empty_like(samples)
        for c in range(ch):
            phase = 0.25 * c  # spread the LFO across channels for a wider sound
            lfo = _lfo(n, self.rate, sample_rate, phase, self.shape)
            d = (self.delay + self.depth * lfo) * sample_rate
            wet = _modulated_delay(samples[:, c], d)
            out[:, c] = samples[:, c] * (1 - m) + wet * m
        return out


class Chorus(_ModDelay):
    """Thickens the sound with a slowly modulated, slightly delayed copy."""

    def __init__(self, rate: float = 1.5, depth: float = 0.003, delay: float = 0.02,
                 mix: float = 50):
        super().__init__(rate, depth, delay, mix)


class Flanger(_ModDelay):
    """Jet-plane sweep from a very short modulated delay."""

    def __init__(self, rate: float = 0.25, depth: float = 0.002, delay: float = 0.001,
                 mix: float = 50):
        super().__init__(rate, depth, delay, mix, shape="triangle")


class Vibrato(_ModDelay):
    """Pitch wobble (``depth`` is the delay swing in seconds)."""

    def __init__(self, rate: float = 5.0, depth: float = 0.002):
        super().__init__(rate, depth, 0.0, 100)


class Phaser(Effect):
    """Sweeping notches from a chain of modulated allpass filters."""

    def __init__(self, rate: float = 0.5, stages: int = 4, min_freq: float = 300,
                 max_freq: float = 3000, mix: float = 50, block: int = 512):
        self.rate = rate
        self.stages = stages
        self.min_freq = min_freq
        self.max_freq = max_freq
        self.mix = mix
        self.block = block

    def process(self, samples, sample_rate):
        n, ch = samples.shape
        wet = np.empty_like(samples)
        zi = np.zeros((self.stages, 2, ch))
        # The allpass coefficient is updated once per block from the LFO.
        starts = np.arange(0, n, self.block)
        sweep = 0.5 - 0.5 * np.cos(2 * np.pi * self.rate * starts / sample_rate)
        fc = np.minimum(self.min_freq * (self.max_freq / self.min_freq) ** sweep, sample_rate * 0.45)
        k = np.tan(np.pi * fc / sample_rate)
        coeffs = (k - 1) / (k + 1)
        sos = np.tile([0.0, 1.0, 0.0, 1.0, 0.0, 0.0], (self.stages, 1))
        for start, a in zip(starts, coeffs):
            sos[:, 0] = sos[:, 4] = a
            blk = samples[start:start + self.block]
            wet[start:start + self.block], zi = signal.sosfilt(sos, blk, axis=0, zi=zi)
        m = _percent(self.mix)
        return samples * (1 - m) + wet * m


class Tremolo(Effect):
    """Rhythmic volume modulation. ``depth`` 0-1."""

    def __init__(self, rate: float = 5.0, depth: float = 0.5, shape: str = "sine"):
        self.rate = rate
        self.depth = depth
        self.shape = shape

    def process(self, samples, sample_rate):
        lfo = _lfo(len(samples), self.rate, sample_rate, shape=self.shape)
        return samples * (1 - self.depth * lfo)[:, None]


class AutoPan(Effect):
    """Sweeps the sound between left and right. Output is stereo."""

    def __init__(self, rate: float = 0.5, depth: float = 1.0):
        self.rate = rate
        self.depth = depth

    def process(self, samples, sample_rate):
        mono = samples.mean(axis=1)
        pos = (2 * _lfo(len(mono), self.rate, sample_rate) - 1) * self.depth  # -1..1
        angle = (pos + 1) * np.pi / 4
        return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1) * np.sqrt(2)


# =============================================================================
# Stereo
# =============================================================================

class Pan(Effect):
    """Place the sound in the stereo field: -1 = left, 0 = centre, 1 = right."""

    def __init__(self, position: float = 0.0):
        if not -1 <= position <= 1:
            raise ValueError("position must be between -1 and 1")
        self.position = position

    def process(self, samples, sample_rate):
        angle = (self.position + 1) * np.pi / 4
        gl, gr = np.cos(angle) * np.sqrt(2), np.sin(angle) * np.sqrt(2)
        if samples.shape[1] == 1:
            return np.concatenate([samples * gl, samples * gr], axis=1)
        out = samples[:, :2].copy()
        out[:, 0] *= gl
        out[:, 1] *= gr
        return out


class StereoWidth(Effect):
    """Narrow (0) or widen (>1) a stereo image using mid/side processing."""

    def __init__(self, width: float = 1.5):
        self.width = width

    def process(self, samples, sample_rate):
        if samples.shape[1] != 2:
            return samples
        mid = (samples[:, 0] + samples[:, 1]) / 2
        side = (samples[:, 0] - samples[:, 1]) / 2 * self.width
        return np.stack([mid + side, mid - side], axis=1)


# =============================================================================
# Distortion
# =============================================================================

class Distortion(Effect):
    """Soft-clipping (tanh) distortion. ``drive`` in dB; ``mix`` 0-100."""

    def __init__(self, drive: float = 20.0, mix: float = 100, output_db: float = 0.0):
        self.drive = drive
        self.mix = mix
        self.output_db = output_db

    def process(self, samples, sample_rate):
        g = db_to_gain(self.drive)
        wet = np.tanh(samples * g) / np.tanh(g)
        m = _percent(self.mix)
        return (samples * (1 - m) + wet * m) * db_to_gain(self.output_db)


class Overdrive(Effect):
    """Warm, asymmetric tube-style saturation."""

    def __init__(self, drive: float = 12.0, tone: float = 4000.0):
        self.drive = drive
        self.tone = tone

    def process(self, samples, sample_rate):
        x = samples * db_to_gain(self.drive)
        y = np.where(x >= 0, np.tanh(x), np.tanh(0.7 * x) / 0.7 * 0.9)
        y -= y.mean(axis=0)  # the asymmetry adds DC; remove it
        sos = signal.butter(2, min(self.tone, sample_rate * 0.45), "low", fs=sample_rate, output="sos")
        return _sos_apply(sos, y) / max(np.tanh(db_to_gain(self.drive)), 1e-9)


class HardClip(Effect):
    """Clip anything above ``threshold_db`` dBFS."""

    def __init__(self, threshold_db: float = -6.0):
        self.threshold_db = threshold_db

    def process(self, samples, sample_rate):
        t = db_to_gain(self.threshold_db)
        return np.clip(samples, -t, t)


class Bitcrush(Effect):
    """Lo-fi: reduce bit depth and/or hold samples to fake a lower sample rate."""

    def __init__(self, bits: int = 8, downsample: int = 1):
        self.bits = bits
        self.downsample = max(1, int(downsample))

    def process(self, samples, sample_rate):
        out = samples
        if self.downsample > 1:
            held = out[::self.downsample]
            out = np.repeat(held, self.downsample, axis=0)[:len(samples)]
        step = 2.0 / (2 ** self.bits)
        return np.round(out / step) * step


# =============================================================================
# Filters & EQ
# =============================================================================

class _Butter(Effect):
    btype = ""

    def _cutoffs(self, sample_rate):
        raise NotImplementedError

    def process(self, samples, sample_rate):
        sos = signal.butter(self.order, self._cutoffs(sample_rate), self.btype,
                            fs=sample_rate, output="sos")
        return _sos_apply(sos, samples)


def _nyquist_clamp(f: float, sample_rate: int) -> float:
    return min(max(f, 1.0), sample_rate * 0.499)


class LowPass(_Butter):
    """Remove frequencies above ``cutoff`` Hz. Higher ``order`` = steeper."""
    btype = "lowpass"

    def __init__(self, cutoff: float, order: int = 4):
        self.cutoff = cutoff
        self.order = order

    def _cutoffs(self, sr):
        return _nyquist_clamp(self.cutoff, sr)


class HighPass(LowPass):
    """Remove frequencies below ``cutoff`` Hz."""
    btype = "highpass"


class BandPass(_Butter):
    """Keep only ``low``..``high`` Hz."""
    btype = "bandpass"

    def __init__(self, low: float, high: float, order: int = 4):
        self.low = low
        self.high = high
        self.order = order

    def _cutoffs(self, sr):
        return [_nyquist_clamp(self.low, sr), _nyquist_clamp(self.high, sr)]


class BandStop(BandPass):
    """Remove ``low``..``high`` Hz."""
    btype = "bandstop"


class Notch(Effect):
    """Remove a narrow band around ``frequency`` (e.g. 50/60 Hz mains hum)."""

    def __init__(self, frequency: float, q: float = 30.0):
        self.frequency = frequency
        self.q = q

    def process(self, samples, sample_rate):
        b, a = signal.iirnotch(_nyquist_clamp(self.frequency, sample_rate), self.q, fs=sample_rate)
        return signal.lfilter(b, a, samples, axis=0)


def _rbj_sos(kind: str, f0: float, gain_db: float, q: float, sample_rate: int) -> np.ndarray:
    """Audio-EQ-cookbook biquads (Robert Bristow-Johnson)."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * _nyquist_clamp(f0, sample_rate) / sample_rate
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(A) * alpha
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw),
                 A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw),
                 (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw),
                 A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw),
                 (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b, a = np.array(b) / a[0], np.array(a) / a[0]
    return np.concatenate([b, a])[None, :]


class PeakEQ(Effect):
    """Boost or cut ``gain_db`` around ``frequency`` Hz. Higher ``q`` = narrower."""
    kind = "peak"

    def __init__(self, frequency: float, gain_db: float, q: float = 1.0):
        self.frequency = frequency
        self.gain_db = gain_db
        self.q = q

    def sos(self, sample_rate: int) -> np.ndarray:
        return _rbj_sos(self.kind, self.frequency, self.gain_db, self.q, sample_rate)

    def process(self, samples, sample_rate):
        return _sos_apply(self.sos(sample_rate), samples)


class LowShelf(PeakEQ):
    """Boost or cut everything below ``frequency`` Hz."""
    kind = "lowshelf"

    def __init__(self, frequency: float, gain_db: float, q: float = 0.707):
        super().__init__(frequency, gain_db, q)


class HighShelf(LowShelf):
    """Boost or cut everything above ``frequency`` Hz."""
    kind = "highshelf"


class Equalizer(Effect):
    """Multi-band EQ.

    Pass EQ effects, or ``(frequency, gain_db)`` / ``(frequency, gain_db, q)`` tuples
    for peaking bands::

        Equalizer((100, +3), (1000, -2, 2.0), HighShelf(8000, +4))
    """

    def __init__(self, *bands: PeakEQ | tuple):
        self.bands = [b if isinstance(b, PeakEQ) else PeakEQ(*b) for b in bands]

    def process(self, samples, sample_rate):
        if not self.bands:
            return samples
        sos = np.concatenate([b.sos(sample_rate) for b in self.bands])
        return _sos_apply(sos, samples)

    def response(self, sample_rate: int = 44100, n: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """Frequency response: ``(frequencies_hz, gain_db)``."""
        sos = np.concatenate([b.sos(sample_rate) for b in self.bands])
        w, h = signal.sosfreqz(sos, worN=n, fs=sample_rate)
        return w, 20 * np.log10(np.abs(h) + 1e-12)


# =============================================================================
# Dynamics
# =============================================================================

class Compressor(Effect):
    """Reduce dynamic range.

    Args:
        threshold_db: level above which gain reduction starts.
        ratio: 4 means 4 dB over the threshold comes out as 1 dB over.
        attack: seconds to clamp down.
        release: seconds to recover.
        knee_db: width of the soft knee.
        makeup_db: gain added afterwards. ``None`` = automatic.
        lookahead: seconds of lookahead (lets fast transients be caught cleanly).
    """

    def __init__(self, threshold_db: float = -20.0, ratio: float = 4.0, attack: float = 0.005,
                 release: float = 0.1, knee_db: float = 6.0, makeup_db: float | None = 0.0,
                 lookahead: float = 0.0):
        if ratio < 1:
            raise ValueError("ratio must be >= 1")
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack = attack
        self.release = release
        self.knee_db = knee_db
        self.makeup_db = makeup_db
        self.lookahead = lookahead

    def gain_reduction_db(self, level_db: np.ndarray) -> np.ndarray:
        """Static curve: how many dB to turn down for a given input level."""
        over = level_db - self.threshold_db
        slope = 1 - 1 / self.ratio
        k = self.knee_db / 2
        gr = np.where(over > k, over * slope, 0.0)
        if k > 0:
            in_knee = np.abs(over) <= k
            gr = np.where(in_knee, slope * (over + k) ** 2 / (4 * k), gr)
        return gr

    def process(self, samples, sample_rate):
        if len(samples) == 0:
            return samples
        level = np.max(np.abs(samples), axis=1)  # linked across channels
        level_db = 20 * np.log10(level + 1e-10)
        env = _peak_follower_db(level_db, self.release, sample_rate)
        gr = self.gain_reduction_db(env)
        la = _ms(self.lookahead, sample_rate)
        if la > 0:  # take the max reduction over the next `la` samples
            gr = ndimage.maximum_filter1d(gr, size=la + 1, origin=-(la // 2) - (la % 2), mode="nearest")
        gr = _one_pole(gr, self.attack, sample_rate)
        makeup = self.makeup_db
        if makeup is None:  # make up for the reduction a full-scale signal would get
            makeup = float(self.gain_reduction_db(np.array([0.0]))[0]) / 2
        return samples * (10 ** ((makeup - gr) / 20))[:, None]


class Limiter(Compressor):
    """Brick-wall limiter: nothing gets past ``ceiling_db``."""

    def __init__(self, ceiling_db: float = -1.0, release: float = 0.05, lookahead: float = 0.005):
        super().__init__(threshold_db=ceiling_db, ratio=1000.0, attack=lookahead / 3,
                         release=release, knee_db=0.0, makeup_db=0.0, lookahead=lookahead)
        self.ceiling_db = ceiling_db

    def process(self, samples, sample_rate):
        out = super().process(samples, sample_rate)
        c = db_to_gain(self.ceiling_db)
        return np.clip(out, -c, c)


class NoiseGate(Effect):
    """Silence audio that falls below ``threshold_db`` (e.g. hiss between phrases)."""

    def __init__(self, threshold_db: float = -50.0, attack: float = 0.002,
                 release: float = 0.1, floor_db: float = -80.0):
        self.threshold_db = threshold_db
        self.attack = attack
        self.release = release
        self.floor_db = floor_db

    def process(self, samples, sample_rate):
        if len(samples) == 0:
            return samples
        level_db = 20 * np.log10(np.max(np.abs(samples), axis=1) + 1e-10)
        env = _peak_follower_db(level_db, self.release, sample_rate)
        target = np.where(env > self.threshold_db, 1.0, db_to_gain(self.floor_db))
        gain = _one_pole(target, self.attack, sample_rate)
        return samples * gain[:, None]


# =============================================================================
# Time & pitch
# =============================================================================

def _resample_ratio(samples: np.ndarray, ratio: float) -> np.ndarray:
    """Resample to ``ratio`` x as many frames."""
    frac = Fraction(ratio).limit_denominator(256)
    return signal.resample_poly(samples, frac.numerator, frac.denominator, axis=0)


def _phase_vocoder(x: np.ndarray, rate: float, n_fft: int = 2048, hop: int = 512,
                   chunk: int = 256) -> np.ndarray:
    """Time-stretch a 1-D signal by ``1 / rate`` without changing pitch.

    The STFT is computed ``chunk`` output frames at a time to keep memory flat
    on long inputs; the running phase is carried across chunks.
    """
    n = len(x)
    if n == 0:
        return x
    window = signal.get_window("hann", n_fft)
    padded = np.pad(x, (n_fft // 2, n_fft // 2 + n_fft))
    n_frames = 1 + (len(padded) - n_fft) // hop
    steps = np.arange(0, n_frames - 1, rate)
    expected = 2 * np.pi * hop * np.arange(n_fft // 2 + 1) / n_fft
    if n_fft % hop:
        raise ValueError("n_fft must be a multiple of hop")
    out = np.zeros(n_fft + hop * (len(steps) - 1))
    norm = np.zeros_like(out)
    out_blocks, norm_blocks = out.reshape(-1, hop), norm.reshape(-1, hop)
    phase = None
    for c0 in range(0, len(steps), chunk):
        st = steps[c0:c0 + chunk]
        i = st.astype(int)
        lo = i[0]
        idx = np.arange(n_fft)[None, :] + hop * np.arange(lo, i[-1] + 2)[:, None]
        spec = np.fft.rfft(padded[idx] * window, axis=1)
        i = i - lo
        frac = (st - st.astype(int))[:, None]
        mag = (1 - frac) * np.abs(spec[i]) + frac * np.abs(spec[i + 1])
        dphi = np.angle(spec[i + 1]) - np.angle(spec[i]) - expected
        dphi -= 2 * np.pi * np.round(dphi / (2 * np.pi))
        incr = expected + dphi
        if phase is None:
            phase = np.angle(spec[0])
        ph = phase + np.concatenate([np.zeros((1, len(expected))), np.cumsum(incr, axis=0)[:-1]])
        phase = np.mod(ph[-1] + incr[-1], 2 * np.pi)
        frames = np.fft.irfft(mag * np.exp(1j * ph), n=n_fft, axis=1) * window
        # Overlap-add, one hop-sized slice of every frame at a time.
        for q in range(n_fft // hop):
            out_blocks[c0 + q:c0 + q + len(frames)] += frames[:, q * hop:(q + 1) * hop]
            norm_blocks[c0 + q:c0 + q + len(frames)] += window[q * hop:(q + 1) * hop] ** 2
    out /= np.where(norm > 1e-8, norm, 1.0)
    target = int(round(n / rate))
    return _fit(out[n_fft // 2:][:, None], target)[:, 0]


class Speed(Effect):
    """Play faster or slower like a tape machine: pitch changes with tempo.

    ``Speed(2)`` = twice as fast, an octave up; ``Speed(0.5)`` = half speed, an octave down.
    """

    def __init__(self, factor: float):
        if factor <= 0:
            raise ValueError("factor must be positive")
        self.factor = factor

    def process(self, samples, sample_rate):
        return _resample_ratio(samples, 1 / self.factor)


class TimeStretch(Effect):
    """Change tempo without changing pitch. ``rate`` 2 = twice as fast."""

    def __init__(self, rate: float, n_fft: int = 2048):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.n_fft = n_fft

    def process(self, samples, sample_rate):
        return np.stack([_phase_vocoder(samples[:, c], self.rate, self.n_fft, self.n_fft // 4)
                         for c in range(samples.shape[1])], axis=1)


class PitchShift(Effect):
    """Change pitch by ``semitones`` without changing duration (12 = one octave up)."""

    def __init__(self, semitones: float, n_fft: int = 2048):
        self.semitones = semitones
        self.n_fft = n_fft

    def process(self, samples, sample_rate):
        if self.semitones == 0:
            return samples
        factor = 2 ** (self.semitones / 12)
        stretched = TimeStretch(1 / factor, self.n_fft).process(samples, sample_rate)
        return _fit(_resample_ratio(stretched, 1 / factor), len(samples))


def chain(effects: Iterable[Effect]) -> Chain:
    """Build a :class:`Chain` from any iterable of effects."""
    return Chain(*effects)
