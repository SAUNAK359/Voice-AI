"""V19 cloud-native speech: provider adapters with no local model loads.

These tests never contact Gemini or access real credentials.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import types
import unittest
from unittest.mock import patch
import wave

import numpy as np

from rizzler.cloud_audio import GeminiCloudASR, GeminiCloudTTS, decode_tts_pcm, pcm_wav


class Config:
    gemini_api_key="synthetic-test-only"


def wav_bytes(pcm: bytes, rate=24000) -> bytes:
    output=io.BytesIO()
    with wave.open(output,"wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)
    return output.getvalue()


class CloudSpeechContracts(unittest.TestCase):
    def test_wav_from_mono_float_input(self):
        data=pcm_wav(np.zeros(16000,dtype=np.float32))
        with wave.open(io.BytesIO(data),"rb") as reader:
            self.assertEqual(reader.getframerate(),16000)
            self.assertEqual(reader.getnchannels(),1)
            self.assertEqual(reader.getnframes(),16000)

    def test_reject_nonfinite_and_oversized_audio(self):
        with self.assertRaises(ValueError):
            pcm_wav(np.array([np.nan]*3200,dtype=np.float32))
        with self.assertRaises(ValueError):
            pcm_wav(np.zeros(16000*121,dtype=np.float32))

    def test_wav_tts_strips_container_exactly(self):
        data=bytes([0,0,1,0])*100
        self.assertEqual(decode_tts_pcm(base64.b64encode(wav_bytes(data)).decode()),data)

    def test_reject_wrong_tts_sample_rate(self):
        data=wav_bytes(bytes(100),rate=16000)
        with self.assertRaises(ValueError):
            decode_tts_pcm(base64.b64encode(data).decode())

    def test_reject_invalid_base64(self):
        with self.assertRaises(ValueError):
            decode_tts_pcm("!!!notbase64")

    def test_cloud_stt_uses_no_local_weights(self):
        calls=[]
        class MockModels:
            def generate_content(self, **kw):
                calls.append(kw)
                return types.SimpleNamespace(text="Hello Rizzler")
        fake=types.SimpleNamespace(models=MockModels(),close=lambda:None)
        with patch("google.genai.Client",return_value=fake):
            result=GeminiCloudASR(Config()).transcribe(np.zeros(16000,dtype=np.float32))
        self.assertEqual(result,"Hello Rizzler")
        self.assertEqual(calls[0]["model"],"gemini-3.5-transcribe")
        self.assertEqual(calls[0]["contents"][0].inline_data.mime_type,"audio/wav")

    def test_cloud_tts_requests_wave_and_returns_24khz_pcm(self):
        data=bytes([0,0,1,0])*240
        calls=[]
        class MockInteractions:
            def create(self,**kw):
                calls.append(kw)
                return types.SimpleNamespace(output_audio=types.SimpleNamespace(
                    data=base64.b64encode(wav_bytes(data)).decode()))
        fake=types.SimpleNamespace(interactions=MockInteractions(),close=lambda:None)
        with patch("google.genai.Client",return_value=fake):
            pcm=GeminiCloudTTS(Config()).synthesize("Hello from Gemini.")
        self.assertEqual(pcm,data)
        self.assertEqual(calls[0]["model"],"gemini-3.8-flash-lite-tts")
        self.assertEqual(calls[0]["generation_config"]["speech_config"],[{"voice":"Kore"}])
        self.assertEqual(calls[0]["input"][0]["content"][0]["text"],"Hello from Gemini.")

    def test_missing_credentials_fail_closed(self):
        class Empty:
            gemini_api_key=""
        with self.assertRaises(RuntimeError):
            GeminiCloudTTS(Empty()).synthesize("Hi")
        with self.assertRaises(RuntimeError):
            GeminiCloudASR(Empty()).transcribe(np.zeros(16000,dtype=np.float32))

    def test_models_validate_without_provider_calls(self):
        with patch.dict(os.environ,{"RIZZLER_CLOUD_STT_MODEL":"bad model"}):
            with self.assertRaises(ValueError):
                GeminiCloudASR(Config())
        with patch.dict(os.environ,{"RIZZLER_CLOUD_TTS_VOICE":"invalid voice!"}):
            with self.assertRaises(ValueError):
                GeminiCloudTTS(Config())


if __name__=="__main__":
    unittest.main()
