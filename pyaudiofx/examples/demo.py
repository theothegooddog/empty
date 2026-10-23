"""Tour of pyaudiofx.  Usage:  python examples/demo.py [path/to/song.wav]

Without a file it synthesises a short melody to work with.
"""

import sys
import time

import pyaudiofx as pyaudio
from pyaudiofx import effects as fx


def melody() -> pyaudio.Audio:
    notes = [261.6, 329.6, 392.0, 523.3, 392.0, 329.6]
    clips = [pyaudio.Audio.tone(f, 0.3, waveform="triangle").fade_out(0.1) for f in notes]
    return clips[0].concat(*clips[1:]).to_stereo()


def main():
    song = pyaudio.Audio.load(sys.argv[1]) if len(sys.argv) > 1 else melody()
    print("loaded:", song)

    # Direct sample access
    print("first frame:", song[0], " sample at 0.5s:", song.sample_at(0.5))
    print("peak %.1f dBFS, rms %.1f dBFS" % (song.peak_db, song.rms_db))

    # The example from the original request
    wet = song.ApplyEffect(pyaudio.effects.Reverb(20))
    print("with reverb:", wet)

    # Chains
    radio = fx.HighPass(400) | fx.LowPass(3000) | fx.Distortion(10, mix=40) | fx.Normalize(-3)
    lofi = fx.Bitcrush(bits=6, downsample=3) | fx.LowPass(5000) | fx.Gain(-4)
    chipmunk = fx.PitchShift(7)
    space = fx.Chorus() | fx.Delay(0.3, feedback=0.45, mix=30) | fx.Reverb(45, room_size=0.85)

    for name, chain in [("radio", radio), ("lofi", lofi), ("chipmunk", chipmunk), ("space", space)]:
        out = song | chain
        out.save(f"demo_{name}.wav")
        print(f"wrote demo_{name}.wav  {out}")

    # Playback with live controls
    try:
        player = wet.play(volume=0.8)
    except pyaudio.PlaybackError as e:
        print("(no playback:", e, ")")
        return
    time.sleep(1)
    player.pause()
    print("paused at", round(player.position, 2))
    time.sleep(0.5)
    player.volume = 0.4
    player.resume()
    player.wait()
    print("done")


if __name__ == "__main__":
    main()
