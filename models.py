from dataclasses import dataclass, field
from typing import Optional, TypedDict


class CellRef(TypedDict):
    row: int
    col: int
    text: str


_CONFIDENCE_MAP = {
    "structured_verbatim": "high",
    "freeform_verbatim": "medium",
    "freeform_inferred": "low",
    "edited": "medium",
    "absent": "none",
}


@dataclass
class FieldResult:
    value: Optional[str] = None
    confidence_basis: str = "absent"       # structured_verbatim | freeform_verbatim | freeform_inferred | edited | absent
    reason: str = ""
    edited: bool = False
    original_value: Optional[str] = None
    source_cell: Optional[dict] = None    # {"row": int, "col": int}
    source_snippet: Optional[str] = None  # exact matched text (max 200 chars)

    @property
    def confidence(self) -> str:
        """Backward-compatible confidence string for analytics and API responses."""
        return _CONFIDENCE_MAP.get(self.confidence_basis, "none")


@dataclass
class PatientBlock:
    id: str                                         # Legacy MRN-based ID (routing compat)
    unique_id: str = ""                             # {DDMMYYYY}_{initials}_{gender}_{disambiguator}
    initials: str = ""
    nhs_number: str = ""
    gender: str = ""
    mdt_date: str = ""
    raw_text: str = ""
    extractions: dict = field(default_factory=dict)
    raw_cells: list = field(default_factory=list)
    coverage_map: dict = field(default_factory=dict)   # {"{row},{col}": [{"start","end","used"}]}
    coverage_pct: Optional[float] = None


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
        "patient_times": [],
        "current_patient_start": 0,
        "average_seconds": 0,
        "active_patients": {},
        "phase": "idle",
        "regex_complete": 0,
        "llm_queue_size": 0,
        "llm_complete": 0,
        "completed_patients": [],
    })
