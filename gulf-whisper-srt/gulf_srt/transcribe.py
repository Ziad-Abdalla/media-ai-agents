"""Load a Whisper model (faster-whisper) and get word-level timestamps."""

import glob
import os
import sys

import numpy as np

from gulf_srt.segment import Word
from gulf_srt.transcript import SpeechSegment, Transcript


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


def fit_hotwords(model, names: list[str]) -> tuple[str, list[str]]:
    """Return (the hotwords text to send, the names dropped). faster-whisper silently cuts
    hotwords to max_length // 2 - 1 tokens (223 for Whisper). Arabic names take several tokens
    each, so a long cast list can go over. We drop whole names from the end instead, so «أبو حمد»
    is never cut down to «أبو», and we know exactly what reached the model."""
    limit = model.max_length // 2 - 1

    def tokens(text: str) -> int:
        return len(model.hf_tokenizer.encode(" " + text, add_special_tokens=False).ids)

    kept = len(names)
    while kept and tokens(" ".join(names[:kept])) > limit:
        kept -= 1
    return " ".join(names[:kept]), names[kept:]


def detect_speech(audio) -> list[list[float]]:
    """Where the voice-activity detector hears speech, as [start, end] pairs in seconds.

    Whisper's own VAD filter joins speech across pauses of up to 2 seconds, which is right for
    cutting audio but too coarse for checking it. Here a pause of half a second ends a stretch,
    so the QC report can measure how much speech sits in a gap between subtitles."""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    samples = decode_audio(audio) if isinstance(audio, str) else audio
    chunks = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
    return [[round(c["start"] / 16000, 2), round(c["end"] / 16000, 2)] for c in chunks]


def transcribe(model, audio, hotwords: list[str] | str | None = None) -> Transcript:
    """Transcribe Arabic audio (a file path or 16 kHz numpy array).

    hotwords: names and words to favour (cast, characters, places), as a list of names like
    ["عبود", "أبو حمد"] or as one text (then each word counts as a name). faster-whisper adds
    them to every 30-second window, joined by spaces. It is a hint, not a guarantee, so measure
    it on your own clips before trusting it. A list over Whisper's token limit is cut by whole
    names from the end, with a warning, and the cut is recorded.

    Returns the words with their timings and confidence, Whisper's per-window
    confidence numbers (used by the QC report), where speech was heard, and the audio
    length in seconds.
    """
    names = hotwords.split() if isinstance(hotwords, str) else list(hotwords or [])
    hotwords, dropped_names = fit_hotwords(model, names)
    dropped = "، ".join(dropped_names)
    if dropped:
        print(f"Hotwords over Whisper's limit of {model.max_length // 2 - 1} tokens; "
              f"these names were not used: {dropped}", file=sys.stderr)
    segments, info = model.transcribe(
        audio,
        language="ar",  # don't let Whisper guess; dialect speech can be mis-detected
        vad_filter=True,  # skip stretches with no speech, where Whisper tends to invent text
        word_timestamps=True,  # we need per-word times to cut subtitles well
        beam_size=5,
        condition_on_previous_text=False,  # stops one mistake repeating down the file
        hotwords=hotwords or None,  # unlike initial_prompt, this reaches every window
    )
    words, decoded = [], []
    for segment in segments:  # segments is a generator; the work happens here
        decoded.append(
            SpeechSegment(
                segment.start, segment.end, segment.text.strip(),
                segment.avg_logprob, segment.no_speech_prob, segment.compression_ratio,
            )
        )
        for w in segment.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(w.start, w.end, text, w.probability))
    source = audio if isinstance(audio, str) else ""
    return Transcript(words, info.duration, decoded, source=source, hotwords=hotwords or "",
                      hotwords_dropped=dropped, speech=detect_speech(audio))
