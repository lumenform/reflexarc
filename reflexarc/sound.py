"""Tiny cute pet sounds, played through the lightest backend available.

Four one-second clips (happy / sad / surprise / land) were generated for the
project and normalised to 44.1kHz 16-bit mono here.  Playback is deliberately
quiet and rate-limited: the pet is meant to be a calm companion, so the
sounds stay short, soft, and never repeat within a short window.

Backend note: on Windows ``winsound`` with SND_ASYNC returns instantly.
QtMultimedia's QSoundEffect was tried first and rejected - its first real
playback can block the event loop for tens of milliseconds, which is long
enough to swallow the second click of a fast double-click (measured).

Set REFLEXARC_SOUND=0 to silence the pet entirely.
"""
from __future__ import annotations

import time
from pathlib import Path

try:
    import winsound
    _HAVE_WINSOUND = True
except ImportError:                       # non-Windows
    _HAVE_WINSOUND = False

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QSoundEffect
    _HAVE_QT_SOUND = True
except ImportError:                       # QtMultimedia not installed
    _HAVE_QT_SOUND = False


class SoundBoard:
    """Loads the bundled clips and plays them with per-sound cooldowns."""

    NAMES = ("happy", "sad", "surprise", "land")

    def __init__(self, sounds_dir: Path | None = None,
                 volume: float = 0.42) -> None:
        self._files: dict[str, Path] = {}
        self._effects: dict = {}
        self._last: dict[str, float] = {}
        self.backend = "none"
        if sounds_dir is None:
            sounds_dir = Path(__file__).resolve().parent / "sounds"
        for name in self.NAMES:
            f = sounds_dir / f"pet_{name}.wav"
            if f.exists():
                self._files[name] = f

        if not self._files:
            return
        if _HAVE_WINSOUND:
            self.backend = "winsound"
        elif _HAVE_QT_SOUND:
            self.backend = "qt"
            for name, f in self._files.items():
                eff = QSoundEffect()
                eff.setSource(QUrl.fromLocalFile(str(f)))
                eff.setVolume(volume)
                self._effects[name] = eff

    @property
    def available(self) -> bool:
        return bool(self._files) and self.backend != "none"

    @property
    def names(self) -> list[str]:
        return sorted(self._files)

    def play(self, name: str, cooldown: float = 1.2) -> None:
        """Play a clip unless it played more recently than its cooldown."""
        f = self._files.get(name)
        if f is None:
            return
        now = time.time()
        if now - self._last.get(name, 0.0) < cooldown:
            return
        self._last[name] = now
        if self.backend == "winsound":
            try:
                winsound.PlaySound(
                    str(f), winsound.SND_FILENAME | winsound.SND_ASYNC
                    | winsound.SND_NODEFAULT)
            except Exception:
                pass
        elif self.backend == "qt":
            eff = self._effects.get(name)
            if eff is not None:
                eff.play()

    def warm(self) -> None:
        """Qt backend only: pre-play at zero volume so the first real sound
        does not stall the interaction loop (the winsound backend returns
        immediately and needs no warm-up)."""
        if self.backend != "qt":
            return
        for name, eff in self._effects.items():
            try:
                vol = eff.volume()
                eff.setVolume(0.0)
                eff.play()
                eff.setVolume(vol)
                self._last[name] = time.time()
            except Exception:
                pass
