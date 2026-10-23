import numpy as np
import pytest

from pyaudiofx import Audio, effects as fx

SR = 44100


@pytest.fixture
def tone():
    return Audio.tone(440, 1.0, sample_rate=SR)


@pytest.fixture
def stereo():
    return Audio.noise(1.0, channels=2, seed=0, amplitude=0.3, sample_rate=SR)


ALL_EFFECTS = [
    fx.Gain(-3), fx.Volume(0.5), fx.Normalize(), fx.Reverse(), fx.Invert(),
    fx.FadeIn(0.1), fx.FadeOut(0.1), fx.Trim(0.1, 0.5), fx.Pad(0.1, 0.1), fx.Mono(), fx.Stereo(),
    fx.Reverb(20), fx.Delay(), fx.Chorus(), fx.Flanger(), fx.Vibrato(), fx.Phaser(),
    fx.Tremolo(), fx.AutoPan(), fx.Pan(0.5), fx.StereoWidth(),
    fx.Distortion(), fx.Overdrive(), fx.HardClip(), fx.Bitcrush(),
    fx.LowPass(1000), fx.HighPass(1000), fx.BandPass(300, 3000), fx.BandStop(300, 3000),
    fx.Notch(60), fx.PeakEQ(1000, 6), fx.LowShelf(200, 3), fx.HighShelf(5000, -3),
    fx.Equalizer((100, 3), (1000, -2, 2)),
    fx.Compressor(), fx.Limiter(), fx.NoiseGate(),
    fx.Speed(1.5), fx.TimeStretch(1.25), fx.PitchShift(3),
]


@pytest.mark.parametrize("effect", ALL_EFFECTS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("source", ["tone", "stereo"])
def test_every_effect_runs(effect, source, request):
    audio = request.getfixturevalue(source)
    out = audio.ApplyEffect(effect)
    assert isinstance(out, Audio)
    assert out.samples.dtype == np.float32
    assert np.all(np.isfinite(out.samples))
    assert out.frames > 0
    assert repr(effect)


def test_example_from_the_request():
    import pyaudiofx as pyaudio
    out = pyaudio.Audio.tone(440, 0.5).ApplyEffect(pyaudio.effects.Reverb(20))
    assert isinstance(out, pyaudio.Audio)
    assert out.duration > 0.5  # reverb tail


def test_effects_do_not_mutate_input(tone):
    before = tone.samples.copy()
    for e in ALL_EFFECTS:
        tone.apply_effect(e)
    np.testing.assert_array_equal(tone.samples, before)


def test_chaining_styles_agree(tone):
    chain = fx.HighPass(200) | fx.Gain(-6) | fx.Reverb(10, tail=False)
    assert isinstance(chain, fx.Chain) and len(chain) == 3
    a = tone | chain
    b = tone.apply(fx.HighPass(200), fx.Gain(-6), fx.Reverb(10, tail=False))
    c = fx.Chain(fx.HighPass(200), fx.Gain(-6), fx.Reverb(10, tail=False))(tone)
    np.testing.assert_allclose(a.samples, b.samples, atol=1e-6)
    np.testing.assert_allclose(a.samples, c.samples, atol=1e-6)


def test_reverb(tone):
    wet = tone | fx.Reverb(50)
    assert wet.duration > tone.duration
    assert (tone | fx.Reverb(50, tail=False)).frames == tone.frames
    dry = tone | fx.Reverb(0, tail=False)
    np.testing.assert_allclose(dry.samples, tone.samples, atol=1e-6)
    # Bigger rooms ring longer.
    assert (tone | fx.Reverb(50, room_size=0.95)).duration > (tone | fx.Reverb(50, room_size=0.2)).duration
    with pytest.raises(ValueError):
        fx.Reverb(150)


def test_reverb_tail_decays():
    impulse = Audio.from_samples(np.r_[1.0, np.zeros(SR * 2)], SR)
    env = (impulse | fx.Reverb(100)).envelope(0.1)
    assert env[1] > env[5] > env[10]


def test_convolution_reverb_with_impulse(tone):
    ir = Audio.from_samples(np.r_[1.0, np.zeros(99)], SR)  # identity IR
    out = tone | fx.ConvolutionReverb(ir, mix=100, tail=False)
    np.testing.assert_allclose(out.samples, tone.samples, atol=1e-5)


def test_delay_repeats():
    click = Audio.from_samples(np.r_[1.0, np.zeros(SR - 1)], SR)
    out = click | fx.Delay(time=0.1, feedback=0.5, mix=100)
    d = int(0.1 * SR)
    assert out.samples[d, 0] == pytest.approx(1.0)
    assert out.samples[2 * d, 0] == pytest.approx(0.5)
    assert out.samples[3 * d, 0] == pytest.approx(0.25)


def test_filters_attenuate(tone):
    low = Audio.tone(100, 1)
    high = Audio.tone(8000, 1)
    lp = fx.LowPass(1000)
    assert (low | lp).rms > 0.95 * low.rms
    assert (high | lp).rms < 0.01 * high.rms
    hp = fx.HighPass(1000)
    assert (low | hp).rms < 0.01 * low.rms


def test_peak_eq_gain(tone):
    boosted = tone | fx.PeakEQ(440, 6, q=2)
    assert boosted.slice(0.2).rms_db - tone.slice(0.2).rms_db == pytest.approx(6, abs=0.2)


def test_compressor_reduces_loud_parts():
    quiet = Audio.tone(440, 0.5, amplitude=0.05)
    loud = Audio.tone(440, 0.5, amplitude=0.9)
    sig = quiet + loud
    out = sig | fx.Compressor(threshold_db=-20, ratio=4, makeup_db=0)
    assert out.slice(0, 0.5).rms == pytest.approx(quiet.rms, rel=0.05)
    assert out.slice(0.6).rms < loud.rms * 0.5


def test_limiter_ceiling():
    hot = Audio.tone(440, 0.5, amplitude=1.0).gain(6)
    assert (hot | fx.Limiter(-3)).peak_db <= -3 + 1e-6


def test_noise_gate():
    sig = Audio.tone(440, 0.5, amplitude=0.5) + Audio.noise(0.5, amplitude=0.001, seed=0)
    out = sig | fx.NoiseGate(threshold_db=-40)
    assert out.slice(0.8).peak < 1e-4
    assert out.slice(0.1, 0.4).rms == pytest.approx(sig.slice(0.1, 0.4).rms, rel=0.01)


@pytest.mark.parametrize("semitones,expected", [(12, 880), (-12, 220), (7, 659.3)])
def test_pitch_shift(tone, semitones, expected):
    out = tone | fx.PitchShift(semitones)
    assert out.frames == tone.frames
    assert out.dominant_frequency() == pytest.approx(expected, rel=0.01)


def test_time_stretch_keeps_pitch(tone):
    out = tone | fx.TimeStretch(0.5)
    assert out.duration == pytest.approx(2.0, abs=0.001)
    assert out.dominant_frequency() == pytest.approx(440, rel=0.01)


def test_speed_changes_pitch_and_length(tone):
    out = tone | fx.Speed(2)
    assert out.duration == pytest.approx(0.5, abs=0.001)
    assert out.dominant_frequency() == pytest.approx(880, rel=0.01)


def test_pan_and_width(tone):
    left = tone | fx.Pan(-1)
    assert left.channels == 2
    assert left.channel(1).peak < 1e-6
    st = Audio.noise(0.5, channels=2, seed=1)
    assert np.allclose((st | fx.StereoWidth(0)).channel(0).samples, (st | fx.StereoWidth(0)).channel(1).samples)


def test_bitcrush_levels(tone):
    out = tone | fx.Bitcrush(bits=3)
    assert len(np.unique(out.samples)) <= 2 ** 3 + 1


def test_drywet_and_custom(tone):
    half = tone | fx.DryWet(fx.Invert(), mix=50)
    assert half.peak < 1e-6
    doubled = tone | fx.Custom(lambda x, sr: x * 2)
    np.testing.assert_allclose(doubled.samples, tone.samples * 2, atol=1e-6)


def test_custom_effect_subclass(tone):
    class Square(fx.Effect):
        def process(self, samples, sample_rate):
            return np.sign(samples) * 0.5

    assert (tone | Square()).peak == pytest.approx(0.5)


def test_resample_effect_in_chain(tone):
    out = tone | (fx.Resample(22050) | fx.Gain(-6))
    assert out.sample_rate == 22050
