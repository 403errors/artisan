"""Typed inter-agent I/O. Per SYSTEM_DESIGN.md §6.2 — no raw string/dict passing between agents."""

from typing import Literal

from pydantic import BaseModel


class IntakeVerdict(BaseModel):
    sufficient: bool
    missing_context_question: str | None = None


class DomainExpertOutput(BaseModel):
    domain: Literal["frontend", "backend", "infra-devops"]
    technical_summary: str
    relevant_files: list[str]


class Plan(BaseModel):
    steps: list[str]
    touched_files: list[str]
    test_cases: list[str]
    doc_updates: list[str]


class ExecutionResult(BaseModel):
    branch: str
    diff_summary: str
    tests_passed: bool
    logs_uri: str


class VerificationVerdict(BaseModel):
    green: bool
    feedback: str | None = None


class ConflictVerdict(BaseModel):
    classification: Literal["trivial", "semantic"]
    resolution_branch: str | None = None
    comparison: str | None = None


class GitHubWebhookEnvelope(BaseModel):
    """The message published to `artisan-github-events`. Per SYSTEM_DESIGN.md §6.1 — the
    ingestion route's only job is producing this typed envelope, never a raw dict."""

    delivery_id: str
    event: Literal["issues", "issue_comment", "pull_request"]
    action: str
    repo: str
    payload: dict
