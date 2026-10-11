"""Manufacturer-independent audio/PTT contract and dry-run template.

SPDX-License-Identifier: Apache-2.0
Hardware drivers must implement bounded waits and idempotent release operations.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import io
import math
import threading
import time
import wave

from receiver import MAX_BYTES, decode_wav
from selcal import validate


@dataclass(frozen=True)
class Timing:
    lead_seconds: float = 0.3
    tail_seconds: float = 0.2
    max_ptt_seconds: float = 5.0

    def __post_init__(self):
        for value in (self.lead_seconds, self.tail_seconds, self.max_ptt_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('PTT時間は有限の数値で指定してください。')
        if not 0 <= self.lead_seconds <= 10 or not 0 <= self.tail_seconds <= 10:
            raise ValueError('前後待ち時間は0〜10秒で指定してください。')
        if not 0 < self.max_ptt_seconds <= 30:
            raise ValueError('PTT上限は0秒より大きく30秒以下にしてください。')


class AudioOutput(ABC):
    """Host audio output feeding the radio audio input; never browser audio."""
    @abstractmethod
    def prepare(self, wav_bytes):
        """Validate/open an explicit output device before activating PTT."""

    @abstractmethod
    def start(self):
        """Begin playback; return promptly or raise."""

    @abstractmethod
    def wait_complete(self, timeout_seconds):
        """True only after the device has drained PCM; False on bounded timeout."""

    @abstractmethod
    def stop(self):
        """Idempotently stop/discard playback, with a bounded operation."""


class PTTOutput(ABC):
    @abstractmethod
    def activate(self):
        """Assert PTT; the driver owns polarity and electrical conversion."""

    @abstractmethod
    def release(self):
        """Idempotently deassert PTT, even after partial activation failure."""


class RadioInterface:
    """One-device sequence template; not a real-time or hardware watchdog."""
    def __init__(self, audio, ptt, timing=None, *, clock=time.monotonic, sleep=time.sleep):
        self.audio, self.ptt = audio, ptt
        self.timing = timing or Timing()
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()

    def run(self, wav_bytes, expected_code, mode='selcal16', guard=None):
        """Verify PCM before keying; optional guard validates current HACS key/epoch.

        guard is called after preparation and after the lead delay. Drivers must
        honor the wait timeout; the template cannot interrupt a hung hardware call.
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('この無線機インターフェースは使用中です。')
        try:
            code = validate(expected_code, mode)
            if len(wav_bytes) > MAX_BYTES:
                raise ValueError('WAVは2 MB以下にしてください。')
            detection = decode_wav(wav_bytes, code, mode)
            if len(detection['calls']) != 1 or not detection['calls'][0]['matched']:
                raise ValueError('内部確認で期待コードと一致する信号を1件検出できませんでした。')
            with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
            timing = self.timing
            if timing.lead_seconds + duration + timing.tail_seconds >= timing.max_ptt_seconds:
                raise ValueError('音声長と前後待ち時間がPTT上限に収まりません。')
            try:
                self.audio.prepare(wav_bytes)
                if guard:
                    guard()
                deadline = self.clock() + timing.max_ptt_seconds
                self.ptt.activate()
                self.sleep(timing.lead_seconds)
                if guard:
                    guard()
                remaining = deadline - self.clock() - timing.tail_seconds
                if remaining <= duration:
                    raise TimeoutError('PTT上限を超えました。')
                self.audio.start()
                if not self.audio.wait_complete(remaining):
                    raise TimeoutError('音声出力が制限時間内に完了しませんでした。')
                if self.clock() + timing.tail_seconds >= deadline:
                    raise TimeoutError('PTT上限を超えました。')
                self.sleep(timing.tail_seconds)
                if self.clock() >= deadline:
                    raise TimeoutError('PTT上限を超えました。')
            finally:
                # Drop PTT first so audio-driver cleanup cannot delay release.
                try:
                    self.ptt.release()
                finally:
                    self.audio.stop()
            return {'status':'sequence_completed', 'mode':mode,
                    'code':code[:2]+'-'+code[2:], 'duration_seconds':duration,
                    'receiver_acknowledged':False}
        finally:
            self._lock.release()


class DryRunAudio(AudioOutput):
    def __init__(self, events):
        self.events = events

    def prepare(self, wav_bytes):
        self.events.append({'event':'audio_prepare', 'bytes':len(wav_bytes)})

    def start(self):
        self.events.append({'event':'audio_start', 'physical_output':False})

    def wait_complete(self, timeout_seconds):
        self.events.append({'event':'audio_complete_simulated', 'timeout_seconds':round(timeout_seconds,3)})
        return True

    def stop(self):
        self.events.append({'event':'audio_stop'})


class DryRunPTT(PTTOutput):
    def __init__(self, events):
        self.events = events

    def activate(self):
        self.events.append({'event':'ptt_on_simulated', 'physical_output':False})

    def release(self):
        self.events.append({'event':'ptt_off_simulated', 'physical_output':False})
