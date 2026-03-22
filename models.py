from dataclasses import dataclass, field
from typing import Optional

@dataclass
class FieldResult:
    value: Optional[str] = None
    confidence: str = "low"
    reason: str = ""
    edited: bool = False
    original_value: Optional[str] = None

@dataclass
class PatientBlock:
    id: str
    initials: str = ""
    nhs_number: str = ""
    raw_text: str = ""
    extractions: dict = field(default_factory=dict)

@dataclass
class ExtractionSession:
    file_name: str = ""
    upload_time: str = ""
    patients: list = field(default_factory=list)
    status: str = "idle"
    stop_requested: bool = False
    concurrency: int = 1
    progress: dict = field(default_factory=lambda: {
        "current_patient": 0,
        "total": 0,
        "current_group": "",
        "patient_times": [],  # List of seconds per patient
        "current_patient_start": 0,
        "average_seconds": 0,
        "active_patients": {} # {patient_id: {group: name, start: time}}
    })
