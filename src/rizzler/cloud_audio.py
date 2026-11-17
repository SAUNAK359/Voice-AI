"""Gemini cloud speech adapters for the compatibility VoiceEngine.

Real-time conversation uses native Gemini Live audio-to-audio and does not make
extra STT/TTS requests. These adapters serve legacy /ws and /api/turn callers
without requiring local Whisper, PyTorch, CUDA, Kitten or ONNX weights.
"""
from __future__ import annotations

import base64
import io
import os
import re
import wave

import numpy as np

_MODEL=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$")
_VOICE=re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,39}$")


def _choice(env: str, default: str, rule) -> str:
    value=os.environ.get(env,default)
    if not rule.fullmatch(value):
        raise ValueError("Invalid cloud speech model/voice identifier")
    return value


def pcm_wav(waveform) -> bytes:
    """Convert the VoiceEngine's 16 kHz float32 mono samples to bounded WAV."""
    values=np.asarray(waveform,dtype=np.float32).reshape(-1)
    if (not 3200 <= values.size <= 16000*120 or
            not np.isfinite(values).all()):
        raise ValueError("Invalid speech input")
    pcm=(np.clip(values,-1,1)*32767).astype("<i2").tobytes()
    out=io.BytesIO()
    with wave.open(out,"wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    return out.getvalue()


def decode_tts_pcm(encoded) -> bytes:
    """Gemini returns a base64 audio block: WAV or raw 24 kHz mono PCM16."""
    if not isinstance(encoded,(str,bytes)) or not encoded:
        raise ValueError("Gemini TTS returned no audio data")
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,base64.binascii.Error) as exc:
        raise ValueError("Gemini TTS returned invalid audio encoding") from exc
    if raw.startswith(b"RIFF"):
        try:
            with wave.open(io.BytesIO(raw),"rb") as reader:
                if (reader.getnchannels()!=1 or reader.getsampwidth()!=2
                        or reader.getframerate()!=24000
                        or reader.getcomptype()!="NONE"):
                    raise ValueError("Unsupported Gemini TTS WAV format")
                pcm=reader.readframes(reader.getnframes())
        except (EOFError,wave.Error) as exc:
            raise ValueError("Malformed Gemini TTS WAV") from exc
    else:
        pcm=raw
    if not 2<=len(pcm)<=24000*2*90 or len(pcm)%2:
        raise ValueError("Gemini TTS audio length or alignment invalid")
    return pcm


class GeminiCloudASR:
    """Low-overhead short-utterance recognition; no local speech model."""
    def __init__(self,settings):
        self.settings=settings
        self.model=_choice("RIZZLER_CLOUD_STT_MODEL","gemini-3.5-transcribe",_MODEL)

    def transcribe(self,waveform) -> str:
        if not self.settings.gemini_api_key:
            raise RuntimeError("Gemini cloud speech requires GEMINI_API_KEY")
        from google import genai
        from google.genai import types
        client=genai.Client(api_key=self.settings.gemini_api_key)
        try:
            # Inline short speech avoids an extra Files API upload/round trip.
            response=client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(
                    data=pcm_wav(waveform),mime_type="audio/wav")])
            result=(getattr(response,"text",None) or "").strip()
            if not result or len(result)>8000:
                raise ValueError("Gemini cloud STT returned no valid transcript")
            return result
        finally:
            client.close()


class GeminiCloudTTS:
    """Cloud-native Gemini TTS for exact-text legacy speech; 24 kHz PCM16."""
    enforce_audibility=True
    def __init__(self,settings):
        self.settings=settings
        self.model=_choice("RIZZLER_CLOUD_TTS_MODEL","gemini-3.8-flash-lite-tts",_MODEL)
        self.voice=_choice("RIZZLER_CLOUD_TTS_VOICE","Kore",_VOICE)

    def synthesize(self,text: str) -> bytes:
        if not self.settings.gemini_api_key:
            raise RuntimeError("Gemini cloud speech requires GEMINI_API_KEY")
        if not isinstance(text,str) or not 1<=len(text.strip())<=1500:
            raise ValueError("Invalid bounded Gemini speech text")
        from google import genai
        client=genai.Client(api_key=self.settings.gemini_api_key)
        try:
            interaction=client.interactions.create(
                model=self.model,
                input=text,
                response_format={"type":"audio"},
                generation_config={"speech_config":[{"voice":self.voice}]})
            audio=getattr(interaction,"output_audio",None)
            return decode_tts_pcm(getattr(audio,"data",None))
        finally:
            client.close()
