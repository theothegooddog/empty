"""pyaudiofx: load, play, edit and process audio with a small, chainable API.

    import pyaudiofx as pyaudio

    song = pyaudio.Audio.load("song.wav")
    wet = song.ApplyEffect(pyaudio.effects.Reverb(20))
    player = wet.play()
"""

from . import effects, io
from .audio import Audio, db_to_gain, gain_to_db
from .effects import Effect
from .io import AudioIOError
from .player import PlaybackError, Player

load = Audio.load

__all__ = [
    "Audio", "Player", "Effect", "effects", "io", "load",
    "AudioIOError", "PlaybackError", "db_to_gain", "gain_to_db",
]
__version__ = "0.1.0"
