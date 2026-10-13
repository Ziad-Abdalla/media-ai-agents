"""Feed Whisper 20 seconds of random noise, with the VAD filter off and on.

    python scripts/noise_check.py

With VAD off, Whisper usually invents text (often «اشتركوا في القناة», "subscribe to the
channel"). With VAD on, there is no speech to send, so it should print nothing.
"""

import sys

import numpy as np

from gulf_srt.transcribe import load_model

sys.stdout.reconfigure(encoding="utf-8")
noise = np.random.default_rng(seed=0).normal(0, 0.1, 20 * 16000).astype(np.float32)  # 20 s at 16 kHz
model, device = load_model()
for vad in (False, True):
    segments, _ = model.transcribe(noise, language="ar", vad_filter=vad)
    text = " ".join(s.text.strip() for s in segments)
    print(f"VAD {'on ' if vad else 'off'}: {text!r}")
