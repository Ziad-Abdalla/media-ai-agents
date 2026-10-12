from gulf_srt.formats import to_transcript, to_vtt, vtt_timestamp
from gulf_srt.segment import Cue
from gulf_srt.srt import RLM, parse_srt

CUES = [Cue(0.0, 1.5, ["هلا والله"]), Cue(62.25, 64.0, ["Sadaf & co <b>", "كيفك؟"])]


def test_vtt_timestamp_uses_a_dot():
    assert vtt_timestamp(3725.042) == "01:02:05.042"


def test_vtt_layout_and_escaping():
    vtt = to_vtt(CUES)
    assert vtt.startswith("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.500\n")
    assert "Sadaf &amp; co &lt;b&gt;" in vtt  # < and & would start a tag or entity in WebVTT
    assert f"{RLM}كيفك؟{RLM}" in vtt


def test_vtt_can_be_read_back():
    back = parse_srt(to_vtt(CUES, rtl=False))
    assert [(c.start, c.end) for c in back] == [(0.0, 1.5), (62.25, 64.0)]


def test_transcript_has_one_timecoded_line_per_cue():
    text = to_transcript(CUES, title="ep01")
    assert "[00:00:00] هلا والله" in text
    assert "[00:01:02] Sadaf & co <b> كيفك؟" in text
    assert "Not checked by an editor" in text
