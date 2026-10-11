"""Copy and implement on the radio-connected host after interface review.

SPDX-License-Identifier: Apache-2.0
This template is deliberately not registered as a selectable live driver.
"""
from radio_interface import AudioOutput, PTTOutput


class HostAudioOutput(AudioOutput):
    def prepare(self, wav_bytes):
        # Open an explicitly configured device and buffer PCM without playback.
        raise NotImplementedError('Implement host audio output and calibrated level')

    def start(self):
        raise NotImplementedError('Implement non-blocking playback start')

    def wait_complete(self, timeout_seconds):
        # Must return within timeout_seconds and wait for hardware buffer drain.
        raise NotImplementedError('Implement bounded completion wait')

    def stop(self):
        raise NotImplementedError('Implement bounded, idempotent audio stop')


class HostPTTOutput(PTTOutput):
    def activate(self):
        # Use the radio-specific isolated contact, logic converter or CAT driver.
        raise NotImplementedError('Implement reviewed PTT activation')

    def release(self):
        # Must also work when activate() has raised after partial assertion.
        raise NotImplementedError('Implement bounded, idempotent PTT release')
