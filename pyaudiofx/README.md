# pyaudiofx

A small Python audio library: load a file, play it with live transport controls, edit it, read
and write raw samples, and run it through a chainable set of effects.

```python
import pyaudiofx as pyaudio

song = pyaudio.Audio.load("song.mp3")
wet = song.ApplyEffect(pyaudio.effects.Reverb(20))   # -> pyaudio.Audio
player = wet.play()
```

> The package is called `pyaudiofx` rather than `pyaudio` because `pyaudio` is already the
> import name of the popular PortAudio binding, PyAudio. `import pyaudiofx as pyaudio` gives you
> the API exactly as written above.

## Install

```bash
pip install -e .              # from this folder
pip install -e ".[test]"      # plus pytest
```

Dependencies: `numpy`, `scipy`, `soundfile` (file I/O) and `sounddevice` (playback/recording).
Playback also needs the PortAudio system library (`apt install libportaudio2` on Debian/Ubuntu,
`brew install portaudio` on macOS; Windows wheels bundle it).

## The `Audio` object

`Audio` holds float32 samples shaped `(frames, channels)`, nominally in [-1, 1], plus a sample
rate. It is **immutable**: every method and effect returns a new `Audio`, so chaining is safe.

### Loading, creating, saving

```python
a = pyaudio.Audio.load("in.flac")                       # WAV, FLAC, OGG, MP3, AIFF, ...
a = pyaudio.Audio.load("in.m4a", mono=True, sample_rate=22050)  # other formats go through ffmpeg if installed
a = pyaudio.Audio.from_samples(numpy_array, 48000)      # float or int PCM (int16 etc. is scaled)
a = pyaudio.Audio.tone(440, 2.0, waveform="square")     # sine / square / sawtooth / triangle
a = pyaudio.Audio.noise(1.0, color="pink")              # white / pink / brown
a = pyaudio.Audio.silence(0.5, channels=2)
a = pyaudio.Audio.record(5)                             # from the microphone

a.save("out.wav")                                       # format from the extension
a.save("out.wav", subtype="PCM_24")
```

### Reading samples directly

```python
a.samples              # read-only ndarray (frames, channels)
a.to_numpy()           # writable copy; layout="channels_first" for (channels, frames)
a.to_pcm(np.int16)     # integer PCM
a[1000]                # one frame (a value per channel)
a[1000:2000]           # frames 1000..1999 as a new Audio
a.sample_at(1.5)       # value at 1.5 s (channel 0)
a.frame_at(1.5)
a.channel(1)           # one channel as mono Audio
for block in a.chunks(seconds=0.1):   # iterate blocks of frames
    ...

a.sample_rate, a.channels, a.frames, a.duration
a.peak, a.peak_db, a.rms, a.rms_db
a.spectrum()           # (freqs, dB)
a.spectrogram()        # (freqs, times, dB)
a.envelope(0.05)       # RMS per 50 ms window
a.dominant_frequency()
```

### Editing

```python
a.slice(10, 20)               # seconds; negative counts from the end: a.slice(-5)
a.gain(-6)  /  a - 6  /  a + 3      # dB
a.normalize(-1)
a.fade_in(2).fade_out(3, curve="equal_power")
a.reverse(), a.invert(), a.clip()
a.to_mono(), a.to_stereo(), a.with_channels(6)
a.resample(48000)
a.pad(start=1, end=2), a.trim_silence(-50)
a + b                         # concatenate
a.concat(b, c, crossfade=0.5)
a * 4                         # repeat
a & b                         # mix together
a.overlay(b, at=3.0, gain_db=-6)
pyaudio.Audio.mix(a, b, c, normalize=True)
pyaudio.Audio.merge_channels(left, right)
```

## Playback

`play()` returns immediately with a `Player`; every control works while audio is playing.

```python
p = song.play()                 # or song.play(blocking=True)
p.pause(); p.resume(); p.toggle()
p.seek(30); p.skip(-5); p.position          # seconds
p.volume = 0.5; p.muted = True
p.loop = True
p.set_region(10, 20)            # play/loop only 0:10-0:20
p.progress, p.is_playing, p.is_paused
p.wait()                        # block until finished
p.stop()

song.play(start=60, end=90, loop=True, volume=0.7, device="MacBook Pro Speakers")
p = song.player(on_finished=lambda p: print("done"))   # create without starting
with song.play() as p:          # stops when the block exits
    p.wait(10)
```

## Effects

```python
from pyaudiofx import effects as fx

out = song.ApplyEffect(fx.Reverb(20))      # also: song.apply_effect(...), fx.Reverb(20)(song)
out = song | fx.Reverb(20) | fx.Gain(-3)   # pipe syntax
out = song.apply(fx.HighPass(80), fx.Compressor(), fx.Limiter())

vocal_chain = fx.HighPass(80) | fx.Compressor(-18, 3) | fx.PeakEQ(3000, 2) | fx.Reverb(15)
out = song | vocal_chain                   # chains are reusable effects
```

| Category | Effects |
|---|---|
| Level & utility | `Gain(db)`, `Volume(factor)`, `Normalize(peak_db)`, `Reverse()`, `Invert()`, `FadeIn(s)`, `FadeOut(s)`, `Trim(start, end)`, `Pad(start, end)`, `Resample(sr)`, `Mono()`, `Stereo()` |
| Space | `Reverb(amount, room_size, damping, width, pre_delay, tail)`, `ConvolutionReverb(impulse, mix)`, `Delay`/`Echo(time, feedback, mix, ping_pong)` |
| Modulation | `Chorus`, `Flanger`, `Vibrato`, `Phaser`, `Tremolo`, `AutoPan` |
| Stereo | `Pan(position)`, `StereoWidth(width)` |
| Distortion | `Distortion(drive)`, `Overdrive(drive, tone)`, `HardClip(threshold_db)`, `Bitcrush(bits, downsample)` |
| Filters & EQ | `LowPass`, `HighPass`, `BandPass`, `BandStop`, `Notch`, `PeakEQ`, `LowShelf`, `HighShelf`, `Equalizer(*bands)` |
| Dynamics | `Compressor(threshold_db, ratio, attack, release, knee_db, makeup_db, lookahead)`, `Limiter(ceiling_db)`, `NoiseGate(threshold_db)` |
| Time & pitch | `Speed(factor)` (tape-style), `TimeStretch(rate)` (tempo only), `PitchShift(semitones)` (pitch only) |
| Helpers | `Chain(*effects)`, `DryWet(effect, mix)`, `Custom(fn)` |

`mix`/`amount` parameters are percentages (0–100). Times are in seconds, frequencies in Hz,
levels in dB. Reverb and delay keep their tail by default (the clip gets longer); pass
`tail=False` to keep the original length.

### Writing your own effect

```python
class HalfWaveRectify(fx.Effect):
    def process(self, samples, sample_rate):   # float64 (frames, channels), yours to modify
        return np.maximum(samples, 0)

song | HalfWaveRectify()
song | fx.Custom(lambda x, sr: x[::-1])       # or wrap a function
```

## Tests

```bash
python -m pytest
```

Playback is tested by driving the player's buffer-filling logic directly, so the tests don't need
a sound card.
