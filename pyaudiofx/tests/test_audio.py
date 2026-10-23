import numpy as np
import pytest

import pyaudiofx as pa
from pyaudiofx import Audio, effects as fx

SR = 44100


@pytest.fixture
def tone():
    return Audio.tone(440, 1.0, sample_rate=SR)


@pytest.fixture
def stereo():
    return Audio.noise(1.0, channels=2, seed=0, sample_rate=SR)


# ---- construction & raw access ----------------------------------------------

def test_shapes_and_properties(tone):
    assert tone.frames == SR
    assert tone.channels == 1
    assert tone.duration == pytest.approx(1.0)
    assert tone.peak == pytest.approx(0.5, abs=1e-3)
    assert tone.rms == pytest.approx(0.5 / np.sqrt(2), rel=1e-3)
    assert len(tone) == SR


def test_from_int16_scales_to_float():
    a = Audio.from_samples(np.array([0, 16384, -32768], dtype=np.int16))
    np.testing.assert_allclose(a.samples[:, 0], [0, 0.5, -1.0])


def test_samples_are_read_only_and_isolated():
    src = np.zeros(10)
    a = Audio(src)
    src[0] = 1
    assert a.samples[0, 0] == 0
    with pytest.raises(ValueError):
        a.samples[0, 0] = 1
    arr = a.to_numpy()
    arr[0] = 5  # the copy is writable and doesn't affect the clip
    assert a.samples[0, 0] == 0


def test_indexing(tone):
    assert tone[0].shape == (1,)
    part = tone[100:200]
    assert isinstance(part, Audio) and part.frames == 100
    np.testing.assert_array_equal(part.samples, tone.samples[100:200])
    assert tone.sample_at(0.5) == pytest.approx(tone.samples[SR // 2, 0])


def test_chunks(tone):
    chunks = list(tone.chunks(10000))
    assert sum(len(c) for c in chunks) == tone.frames
    assert all(len(c) == 10000 for c in chunks[:-1])
    overl = list(tone.chunks(1000, overlap=500))
    assert len(overl[0]) == 1000 and np.array_equal(overl[0][500:], overl[1][:500])
    assert list(Audio().chunks(10)) == []


def test_pcm_roundtrip(tone):
    pcm = tone.to_pcm()
    assert pcm.dtype == np.int16
    back = Audio.from_samples(pcm, SR)
    np.testing.assert_allclose(back.samples, tone.samples, atol=1e-4)


# ---- file io ----------------------------------------------------------------

@pytest.mark.parametrize("ext", ["wav", "flac", "ogg"])
def test_save_and_load(tmp_path, stereo, ext):
    path = tmp_path / f"x.{ext}"
    stereo.gain(-6).save(path)
    loaded = Audio.load(path)
    assert loaded.sample_rate == SR
    assert loaded.channels == 2
    assert loaded.frames == pytest.approx(stereo.frames, abs=2048)
    if ext != "ogg":  # lossless
        np.testing.assert_allclose(loaded.samples, stereo.gain(-6).samples, atol=1e-4)


def test_wave_fallback(tmp_path, stereo, monkeypatch):
    monkeypatch.setattr(pa.io, "_sf", None)
    monkeypatch.setattr(pa.io.shutil, "which", lambda _: None)
    path = tmp_path / "x.wav"
    stereo.save(path)
    loaded = Audio.load(path)
    np.testing.assert_allclose(loaded.samples, np.clip(stereo.samples, -1, 1), atol=1e-4)
    with pytest.raises(pa.AudioIOError):
        stereo.save(tmp_path / "x.flac")


def test_load_options(tmp_path, stereo):
    path = tmp_path / "x.wav"
    stereo.save(path)
    a = Audio.load(path, mono=True, sample_rate=22050)
    assert a.channels == 1 and a.sample_rate == 22050
    assert a.duration == pytest.approx(1.0, abs=1e-3)


def test_load_missing():
    with pytest.raises(FileNotFoundError):
        Audio.load("does-not-exist.wav")


# ---- editing ----------------------------------------------------------------

def test_gain_and_normalize(tone):
    assert tone.gain(6).peak == pytest.approx(0.5 * 10 ** (6 / 20), rel=1e-3)
    assert tone.normalize(-3).peak_db == pytest.approx(-3, abs=1e-3)
    assert (tone + 6).peak == pytest.approx(tone.gain(6).peak)
    assert (tone - 6).peak == pytest.approx(tone.gain(-6).peak)


def test_slice_and_negative_times(tone):
    assert tone.slice(0.25, 0.75).duration == pytest.approx(0.5)
    assert tone.slice(-0.1).duration == pytest.approx(0.1)


def test_concat_repeat_overlay(tone):
    assert (tone + tone).duration == pytest.approx(2.0)
    assert (tone * 3).duration == pytest.approx(3.0)
    assert tone.concat(tone, crossfade=0.1).duration == pytest.approx(1.9)
    mixed = tone.overlay(tone, at=0.5)
    assert mixed.duration == pytest.approx(1.5)
    np.testing.assert_allclose(mixed.samples[:SR // 2], tone.samples[:SR // 2])
    assert (tone & tone.invert()).peak < 1e-6


def test_overlay_conforms_rate_and_channels(tone, stereo):
    other = Audio.tone(220, 0.5, sample_rate=22050)
    out = stereo.overlay(other)
    assert out.sample_rate == SR and out.channels == 2 and out.duration == pytest.approx(1.0)


def test_channels(stereo, tone):
    assert stereo.to_mono().channels == 1
    assert tone.to_stereo().channels == 2
    left, right = stereo.split_channels()
    merged = Audio.merge_channels(left, right)
    np.testing.assert_array_equal(merged.samples, stereo.samples)


def test_resample_preserves_pitch(tone):
    r = tone.resample(22050)
    assert r.sample_rate == 22050
    assert r.frames == 22050
    assert r.dominant_frequency() == pytest.approx(440, abs=2)


def test_fades_and_trim(tone):
    f = tone.fade_in(0.5).fade_out(0.5)
    assert abs(f.samples[0, 0]) < 1e-6 and abs(f.samples[-1, 0]) < 1e-6
    padded = tone.pad(0.5, 0.25)
    assert padded.duration == pytest.approx(1.75)
    assert padded.trim_silence().duration == pytest.approx(1.0, abs=0.001)
    assert Audio.silence(1).trim_silence().frames == 0


def test_reverse(tone):
    np.testing.assert_array_equal(tone.reverse().samples, tone.samples[::-1])


def test_analysis(tone):
    assert tone.dominant_frequency() == pytest.approx(440, abs=1)
    f, t, s = tone.spectrogram()
    assert s.shape == (len(f), len(t))
    assert len(tone.envelope(0.1)) == 10


def test_generators():
    for w in ["sine", "square", "sawtooth", "triangle"]:
        assert Audio.tone(100, 0.1, waveform=w).frames == 4410
    for c in ["white", "pink", "brown"]:
        n = Audio.noise(0.5, color=c, seed=1)
        assert n.peak == pytest.approx(0.5)
    with pytest.raises(ValueError):
        Audio.tone(100, 1, waveform="nope")
