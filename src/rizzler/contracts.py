"""Provider-neutral handoff, artifact receipt and job-completion invariants."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from .security import validate_session_id

DELIVERABLES = frozenset({
    'answer','research','data_analysis','automation_plan',
    'pdf','docx','pptx','xlsx','csv','json','md','html','png','svg','txt','zip',
})
FILE_FORMATS = frozenset(DELIVERABLES - {'answer','research','data_analysis','automation_plan'})

class JobStatus(str, Enum):
    QUEUED='queued'
    RUNNING='running'
    COMPLETED='completed'
    FAILED='failed'
    CANCELLED='cancelled'

@dataclass(frozen=True)
class Handoff:
    session_id: str
    objective: str
    deliverables: tuple[str,...]
    external_actions: bool = False
    max_tool_steps: int = 8
    max_output_files: int = 12
    context: dict[str,Any] = field(default_factory=dict)

    def validate(self) -> 'Handoff':
        validate_session_id(self.session_id)
        if not 3 <= len(self.objective.strip()) <= 8000:
            raise ValueError('Invalid objective length')
        if not self.deliverables or len(self.deliverables) > 16:
            raise ValueError('Expected 1–16 deliverables')
        if len(set(self.deliverables)) != len(self.deliverables):
            raise ValueError('Duplicate deliverable')
        invalid = set(self.deliverables) - DELIVERABLES
        if invalid:
            raise ValueError(f'Unsupported deliverables: {sorted(invalid)}')
        if self.external_actions:
            raise PermissionError('External actions require explicit approval and a separate policy')
        if not 1 <= self.max_tool_steps <= 16 or not 1 <= self.max_output_files <= 12:
            raise ValueError('Invalid execution budget')
        if len(set(self.deliverables) & FILE_FORMATS) > self.max_output_files:
            raise ValueError('File budget lower than requested file formats')
        return self

@dataclass(frozen=True)
class ArtifactReceipt:
    kind: str
    name: str
    sha256: str
    byte_size: int
    verified: bool

    def validate(self) -> 'ArtifactReceipt':
        if self.kind not in FILE_FORMATS:
            raise ValueError('Invalid artifact format')
        if self.byte_size <= 0 or not self.verified:
            raise ValueError('Unverified or empty artifact')
        if len(self.sha256) != 64 or any(c not in '0123456789abcdef' for c in self.sha256):
            raise ValueError('Invalid SHA256')
        return self


def completion_gate(handoff: Handoff, artifacts: list[ArtifactReceipt], outcome: str) -> bool:
    """Never return COMPLETED if a requested file is absent or unverified."""
    handoff.validate()
    if outcome != JobStatus.COMPLETED:
        return False
    receipts = {item.kind: item.validate() for item in artifacts}
    required = set(handoff.deliverables) & FILE_FORMATS
    if required - receipts.keys():
        raise ValueError(f'Missing required artifacts: {sorted(required - receipts.keys())}')
    return True
