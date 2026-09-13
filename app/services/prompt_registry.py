"""Allowlisted, immutable prompt versions loaded from packaged UTF-8 files."""

from dataclasses import dataclass
from pathlib import Path

from app.config import PROJECT_ROOT

INCIDENT_ANALYSIS_PROMPT = "incident_analysis_v1"
RUNBOOK_QA_PROMPT = "runbook_qa_v1"
PROMPTS = {
    INCIDENT_ANALYSIS_PROMPT: "incident_analysis_v1.txt",
    RUNBOOK_QA_PROMPT: "runbook_qa_v1.txt",
}


@dataclass(frozen=True)
class Prompt:
    version: str
    instructions: str


def load_prompt(version: str, root: Path | None = None) -> Prompt:
    filename = PROMPTS.get(version)
    if filename is None:
        raise ValueError("Unknown prompt version.")
    instructions = ((root or PROJECT_ROOT / "app" / "prompts") / filename).read_text(
        encoding="utf-8"
    )
    if not instructions.strip():
        raise ValueError("Prompt is empty.")
    return Prompt(version=version, instructions=instructions)
