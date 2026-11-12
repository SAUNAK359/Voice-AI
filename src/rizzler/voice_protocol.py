"""Rizzler real-time voice protocol V2: bounded, sequenced and owner-fenced PCM.

V1 remains supported for legacy clients until an explicit deprecation.
No model, TTS or Work action may consume provisional audio as final intent.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

VERSION = 2
FRAME_MAGIC = b"RZV2"
OUTPUT_MAGIC = b"RZO2"
INPUT_HEADER = struct.Struct("<4sIIII")   # magic, generation, seq, timestamp_ms, samples
OUTPUT_HEADER = struct.Struct("<4sIII")    # magic, generation, seq, sample_rate
MAX_SAMPLES = 2048
MAX_INPUT_BYTES = INPUT_HEADER.size + MAX_SAMPLES * 2


@dataclass
class AudioFrameState:
    generation: int
    rate: int
    max_seconds: int
    next_seq: int = 0
    last_timestamp: int = -1
    total_samples: int = 0

    def receive(self, packet: bytes) -> bytes:
        if not isinstance(packet, bytes) or not INPUT_HEADER.size < len(packet) <= MAX_INPUT_BYTES:
            raise ValueError("Invalid bounded audio frame size")
        magic, generation, seq, timestamp, samples = INPUT_HEADER.unpack_from(packet)
        if (magic != FRAME_MAGIC or generation != self.generation
                or seq != self.next_seq or not 1 <= samples <= MAX_SAMPLES
                or len(packet) != INPUT_HEADER.size + 2 * samples):
            raise ValueError("Invalid, duplicated, out-of-order or cross-turn PCM frame")
        if timestamp < self.last_timestamp or (
                self.last_timestamp >= 0 and timestamp - self.last_timestamp > 5000):
            raise ValueError("Invalid audio timestamp progression")
        if self.total_samples + samples > self.rate * self.max_seconds:
            raise ValueError("Audio frame duration limit exceeded")
        self.next_seq += 1
        self.last_timestamp = timestamp
        self.total_samples += samples
        return packet[INPUT_HEADER.size:]


def output_packet(generation: int, sequence: int, sample_rate: int, pcm: bytes) -> bytes:
    if (not 1 <= generation <= 2**31 - 1 or sequence < 0 or sequence >= 2**32
            or sample_rate != 24000 or not isinstance(pcm, bytes)
            or not pcm or len(pcm) % 2 or len(pcm) > MAX_SAMPLES * 2):
        raise ValueError("Invalid synthesized audio packet")
    return OUTPUT_HEADER.pack(OUTPUT_MAGIC, generation, sequence, sample_rate) + pcm


def legacy_output_packet(generation: int, pcm: bytes) -> bytes:
    return struct.pack("<I", generation) + pcm
