"""Player transport logic, tested without an audio device by driving its fill routine."""

import numpy as np
import pytest

from pyaudiofx import Audio, Player

SR = 1000


@pytest.fixture
def ramp():
    return Audio(np.arange(1000, dtype=np.float32) / 1000, SR)


def pull(player, n):
    out = np.empty((n, 1), dtype=np.float32)
    more = player._fill(out)
    return out[:, 0], more


def test_reads_sequentially(ramp):
    p = Player(ramp)
    a, more = pull(p, 100)
    np.testing.assert_allclose(a, ramp.samples[:100, 0])
    assert more
    assert p.position == pytest.approx(0.1)
    b, _ = pull(p, 100)
    np.testing.assert_allclose(b, ramp.samples[100:200, 0])


def test_stops_at_end_and_zero_fills(ramp):
    p = Player(ramp)
    p.seek(0.95)
    out, more = pull(p, 100)
    assert not more
    np.testing.assert_allclose(out[:50], ramp.samples[950:, 0])
    assert np.all(out[50:] == 0)


def test_loop_wraps(ramp):
    p = Player(ramp, loop=True)
    p.seek(0.95)
    out, more = pull(p, 100)
    assert more
    np.testing.assert_allclose(out[50:], ramp.samples[:50, 0])


def test_region_and_loop(ramp):
    p = Player(ramp, loop=True, start=0.2, end=0.3)
    assert p.position == pytest.approx(0.2)
    out, _ = pull(p, 150)
    np.testing.assert_allclose(out[:100], ramp.samples[200:300, 0])
    np.testing.assert_allclose(out[100:], ramp.samples[200:250, 0])


def test_pause_outputs_silence_and_holds_position(ramp):
    p = Player(ramp)
    pull(p, 100)
    p.pause()
    out, more = pull(p, 100)
    assert more and np.all(out == 0)
    assert p.position == pytest.approx(0.1)
    p.resume()
    out, _ = pull(p, 10)
    np.testing.assert_allclose(out, ramp.samples[100:110, 0])


def test_volume_and_mute(ramp):
    p = Player(ramp, volume=0.5)
    p.seek(0.5)
    out, _ = pull(p, 10)
    np.testing.assert_allclose(out, ramp.samples[500:510, 0] * 0.5)
    p.muted = True
    out, _ = pull(p, 10)
    assert np.all(out == 0)
    with pytest.raises(ValueError):
        p.volume = -1


def test_seek_clamps_and_skip(ramp):
    p = Player(ramp)
    p.seek(-5)
    assert p.position == 0
    p.seek(99)
    assert p.position == pytest.approx(1.0)
    p.seek(0.5)
    p.skip(-0.2)
    assert p.position == pytest.approx(0.3)
    p.position = 0.7
    assert p.progress == pytest.approx(0.7)
