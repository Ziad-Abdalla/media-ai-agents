"""Load a Whisper model (faster-whisper) and get word-level timestamps."""

import glob
import os
import sys

import numpy as np

from gulf_srt.segment import Word


def _add_cuda_dll_paths() -> None:
    """On Windows, the pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 put
    their DLLs in site-packages/nvidia/*/bin, which Windows does not search by
    default. CTranslate2 (the engine under faster-whisper) needs them for the GPU."""
    if sys.platform != "win32":
        return
    for site in sys.path:
        for folder in glob.glob(os.path.join(site, "nvidia", "*", "bin")):
            os.add_dll_directory(folder)
            os.environ["PATH"] = folder + os.pathsep + os.environ["PATH"]


def load_model(name: str = "large-v3-turbo", device: str = "auto"):
    """Return (model, device). 'auto' tries the GPU in float16, then falls back to CPU int8."""
    _add_cuda_dll_paths()
    from faster_whisper import WhisperModel  # imported late so the DLL paths are set first

    if device in ("auto", "cuda"):
        try:
            model = WhisperModel(name, device="cuda", compute_type="float16")
            # Loading can succeed even when a CUDA library (like cuBLAS) is missing; the
            # error only shows up on the first real run. So do a one-second test run now.
            segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ar")
            list(segments)  # segments is a generator; this makes the work actually happen
            return model, "cuda"
        except Exception as error:  # no GPU, or CUDA libraries missing
            if device == "cuda":
                raise
            print(f"GPU not available ({error}); using CPU int8.", file=sys.stderr)
    return WhisperModel(name, device="cpu", compute_type="int8"), "cpu"


def transcribe(model, audio) -> tuple[list[Word], float]:
    """Transcribe Arabic audio (a file path or 16 kHz numpy array).

    Returns the words with their timings, and the audio length in seconds.
    """
    segments, info = model.transcribe(
        audio,
        language="ar",  # don't let Whisper guess; dialect speech can be mis-detected
        vad_filter=True,  # skip stretches with no speech, where Whisper tends to invent text
        word_timestamps=True,  # we need per-word times to cut subtitles well
        beam_size=5,
        condition_on_previous_text=False,  # stops one mistake repeating down the file
    )
    words = []
    for segment in segments:  # segments is a generator; the work happens here
        for w in segment.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(w.start, w.end, text))
    return words, info.duration
