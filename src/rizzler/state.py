"""Deterministic live-session state transitions and barge-in generation tokens."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class Phase(str, Enum):
    IDLE = 'idle'
    LISTENING = 'listening'
    TRANSCRIBING = 'transcribing'
    THINKING = 'thinking'
    SPEAKING = 'speaking'
    INTERRUPTED = 'interrupted'
    ERROR = 'error'
    CLOSED = 'closed'

ALLOWED = {
    Phase.IDLE: {Phase.LISTENING, Phase.CLOSED, Phase.ERROR},
    Phase.LISTENING: {Phase.TRANSCRIBING, Phase.INTERRUPTED, Phase.CLOSED, Phase.ERROR},
    Phase.TRANSCRIBING: {Phase.THINKING, Phase.INTERRUPTED, Phase.CLOSED, Phase.ERROR},
    Phase.THINKING: {Phase.SPEAKING, Phase.INTERRUPTED, Phase.LISTENING, Phase.ERROR, Phase.CLOSED},
    Phase.SPEAKING: {Phase.LISTENING, Phase.INTERRUPTED, Phase.CLOSED, Phase.ERROR},
    Phase.INTERRUPTED: {Phase.LISTENING, Phase.CLOSED, Phase.ERROR},
    Phase.ERROR: {Phase.LISTENING, Phase.CLOSED},
    Phase.CLOSED: set(),
}

@dataclass
class LiveSession:
    phase: Phase = Phase.IDLE
    generation: int = 0
    events: int = 0

    def transition(self, to: Phase) -> None:
        to = Phase(to)
        if to not in ALLOWED[self.phase]:
            raise ValueError(f'Invalid phase transition: {self.phase} -> {to}')
        self.phase = to
        self.events += 1

    def start_speech(self) -> int:
        if self.phase == Phase.CLOSED:
            raise ValueError('Session closed')
        if self.phase not in (Phase.IDLE, Phase.LISTENING, Phase.INTERRUPTED, Phase.ERROR):
            self.interrupt()
        if self.phase != Phase.LISTENING:
            self.transition(Phase.LISTENING)
        self.generation += 1
        return self.generation

    def interrupt(self) -> int:
        if self.phase == Phase.CLOSED:
            raise ValueError('Session closed')
        if self.phase != Phase.INTERRUPTED:
            self.transition(Phase.INTERRUPTED)
        self.generation += 1
        return self.generation

    def current(self, generation: int) -> bool:
        return self.phase != Phase.CLOSED and self.generation == generation

    def close(self) -> None:
        if self.phase != Phase.CLOSED:
            self.transition(Phase.CLOSED)
