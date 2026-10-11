"""Optional host audio and serial RTS/DTR drivers. SPDX-License-Identifier: Apache-2.0"""
import io
import sys
import threading
import wave

from radio_interface import AudioOutput, PTTOutput


def sounddevice_module():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as exc:
        raise RuntimeError('sounddevice/PortAudioが必要です。requirements-radio.txtを導入してください。') from exc


class SoundDeviceAudio(AudioOutput):
    def __init__(self, device, channels=1, module=None):
        if isinstance(device, bool) or not isinstance(device, (str,int)) or device == '' or (isinstance(device,int) and device < 0):
            raise ValueError('音声出力デバイスの名前またはIDを明示してください。')
        if type(channels) is not int or channels not in (1,2):
            raise ValueError('出力チャンネル数は1または2です。')
        self.device, self.channels, self.module = device, channels, module
        self.stream = None
        self.done = threading.Event()
        self.error = None

    def prepare(self, wav_bytes):
        self.stop()
        sd = self.module or sounddevice_module()
        self.module = sd
        with wave.open(io.BytesIO(wav_bytes),'rb') as wav:
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=48000 or wav.getcomptype()!='NONE':
                raise ValueError('48 kHz・16 bit・mono PCM WAVが必要です。')
            pcm = wav.readframes(wav.getnframes())
            if len(pcm)!=wav.getnframes()*2:
                raise ValueError('PCMデータが途中で切れています。')
        if sys.byteorder != 'little':
            pcm = b''.join(pcm[i:i+2][::-1] for i in range(0,len(pcm),2))
        if self.channels == 2:
            pcm = b''.join(pcm[i:i+2]*2 for i in range(0,len(pcm),2))
        # Exact device name; do not silently select a default or ambiguous device.
        device = self.device
        devices = sd.query_devices()
        if isinstance(device,str):
            matches = [i for i,item in enumerate(devices) if item['name']==device and item['max_output_channels']>=self.channels]
            if len(matches)!=1:
                raise ValueError('音声デバイス名が存在しないか曖昧です。デバイスIDを指定してください。')
            device = matches[0]
        if device >= len(devices) or devices[device]['max_output_channels'] < self.channels:
            raise ValueError('指定した音声デバイスは要求された出力に対応しません。')
        sd.check_output_settings(device=device,channels=self.channels,dtype='int16',samplerate=48000)
        self.done.clear(); self.error=None
        position = 0
        def callback(outdata, frames, time_info, status):
            nonlocal position
            try:
                size = frames * 2 * self.channels
                outdata[:] = b'\0'*size
                if status:
                    raise RuntimeError('音声出力でアンダーラン等のエラーが発生しました。')
                chunk = pcm[position:position+size]
                outdata[:len(chunk)] = chunk
                position += len(chunk)
            except Exception as exc:
                self.error = exc
                raise sd.CallbackAbort
            if position >= len(pcm):
                raise sd.CallbackStop
        self.stream = sd.RawOutputStream(device=device,samplerate=48000,channels=self.channels,dtype='int16',
                                         callback=callback,finished_callback=self.done.set)

    def start(self):
        if self.stream is None:
            raise RuntimeError('音声出力を準備してください。')
        self.stream.start()

    def wait_complete(self, timeout_seconds):
        completed = self.done.wait(timeout_seconds)
        if self.error:
            raise RuntimeError(str(self.error)) from self.error
        return completed

    def stop(self):
        if self.stream is not None:
            stream,self.stream = self.stream,None
            try:
                stream.abort()
            finally:
                stream.close()


class SerialPTT(PTTOutput):
    """Serial control-line driver; requires an external radio-compatible interface."""
    def __init__(self, port, line, active_high, module=None):
        if not isinstance(port,str) or not port.strip() or '://' in port:
            raise ValueError('ローカルシリアルポートを明示してください。')
        if line not in ('rts','dtr') or type(active_high) is not bool:
            raise ValueError('PTTはrts/dtrと有効極性（true/false）を指定してください。')
        self.port,self.line,self.active_high,self.module=port,line,active_high,module
        self.serial=None

    def activate(self):
        if self.serial is not None:
            raise RuntimeError('PTTは既に使用中です。')
        if self.module is None:
            try:
                import serial
                self.module=serial
            except ImportError as exc:
                raise RuntimeError('pyserialが必要です。requirements-radio.txtを導入してください。') from exc
        # Keep the unopened object so finally can release after a partial open failure.
        self.serial=self.module.Serial(port=None,timeout=0.5,write_timeout=0.5,rtscts=False,dsrdtr=False)
        self.serial.port=self.port
        self.serial.rts=False
        self.serial.dtr=False
        setattr(self.serial,self.line,not self.active_high)
        self.serial.open()
        setattr(self.serial,self.line,self.active_high)

    def release(self):
        if self.serial is not None:
            serial,self.serial=self.serial,None
            try:
                setattr(serial,self.line,not self.active_high)
            finally:
                serial.close()
