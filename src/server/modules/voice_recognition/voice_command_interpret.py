
import threading, queue, sys, wave
import numpy as np
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel

_ALLOWED = {8000, 16000, 32000, 48000}

class VoiceCommandThread(threading.Thread):
    def __init__(self, handler, device=None, sample_rate=16000, model_name="medium.en"):
        super().__init__(daemon=True)
        self.handler = handler
        self.device = device
        self.sample_rate = sample_rate if sample_rate in _ALLOWED else 16000
        self.frame_ms = 20
        self.frame_samples = int(self.sample_rate * self.frame_ms / 1000)  # exact 20ms
        self.running = True
        self.vad = webrtcvad.Vad(2)
        self.model = WhisperModel(model_name, compute_type="int8")
        self.uk_bias = ("Use British English spelling and vocabulary. colour, metre, aluminium, "
                        "Glasgow, Edinburgh, Paisley, quid, aye, wee, bairn, lorry, postcode.")
        self.bytebuf = bytearray()
        self.voiced_ms = 0
        self.silence_ms = 0
        self.started = False
        self.pcm_chunks = []

    def _cb(self, indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        # indata is int16 mono -> append raw bytes
        self.bytebuf.extend(indata.tobytes())

    def run(self):
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=self._cb,
            device=self.device,
            blocksize=self.frame_samples  # deliver exact 20ms frames
        ):
            print("Voice command loop started.")
            while self.running:
                # produce exact 20ms frames from bytebuf
                need = self.frame_samples * 2  # int16 -> 2 bytes
                if len(self.bytebuf) < need:
                    sd.sleep(5)
                    continue
                frame_bytes = bytes(self.bytebuf[:need])
                del self.bytebuf[:need]

                try:
                    voiced = self.vad.is_speech(frame_bytes, self.sample_rate)
                except webrtcvad.Error:
                    # skip malformed frame
                    continue

                frame_i16 = np.frombuffer(frame_bytes, dtype=np.int16)

                if voiced:
                    self.pcm_chunks.append(frame_i16)
                    self.voiced_ms += self.frame_ms
                    self.silence_ms = 0
                    if not self.started and self.voiced_ms >= 400:
                        self.started = True
                else:
                    if self.started:
                        self.silence_ms += self.frame_ms
                        self.pcm_chunks.append(frame_i16)  # keep tail
                        if self.silence_ms >= 800:
                            self._flush_transcribe()
                            self._reset_state()
                    else:
                        self.voiced_ms = max(0, self.voiced_ms - self.frame_ms)

    def _flush_transcribe(self):
        if not self.pcm_chunks:
            return
        pcm16 = np.concatenate(self.pcm_chunks)
        tmp = "temp_audio/voice_temp.wav"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sample_rate)
            w.writeframes(pcm16.tobytes())

        segs, _ = self.model.transcribe(
            tmp,
            language="en",
            beam_size=5,
            vad_filter=True,
            temperature=[0.0, 0.2, 0.4],
            initial_prompt=self.uk_bias,
            condition_on_previous_text=False
        )
        text = "".join(s.text for s in segs).strip()
        if text:
            try:
                self.handler(text)
            except Exception as e:
                print(f"Handler error: {e}", file=sys.stderr)

    def _reset_state(self):
        self.pcm_chunks = []
        self.voiced_ms = 0
        self.silence_ms = 0
        self.started = False

    def stop(self):
        self.running = False

def start_voice_commands(handler, device=None, sample_rate=16000, model_name="medium.en"):
    t = VoiceCommandThread(handler=handler, device=device, sample_rate=sample_rate, model_name=model_name)
    t.start()
    return t
