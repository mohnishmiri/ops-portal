"""
Pydantic v2 data models for the AI candidate-mapping layer.

Models define the contract between evidence importers and any
CandidateMapper implementation (mock or live provider). All models
are frozen to reinforce that AI output is a candidate only and must
never be written directly as a canonical answer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProposedMapping(BaseModel):
    """
    A single AI-proposed mapping from a source fragment to a question value.

    This is a candidate only. It requires human or system review before
    it may be promoted to a canonical answer.
    """

    model_config = ConfigDict(frozen=True)

    question_id: str = Field(description="Identifier for the question being answered.")
    proposed_value: dict = Field(
        description="Typed candidate value per the relevant response schema."
    )
    confidence_metadata: dict = Field(
        description=(
            "Model-level metadata about confidence. "
            "Must not encode authority claims or credentials."
        )
    )
    grounding_quote: str = Field(
        description=(
            "Exact substring from source_fragment that supports this mapping. "
            "Must appear verbatim in the originating MappingRequest.source_fragment."
        )
    )
    source_locator: str = Field(
        description="Locator for the source cell or region (e.g. Sheet:APP/Row:5/Col:B)."
    )


class MappingRequest(BaseModel):
    """
    Input to a CandidateMapper for a single evidence fragment.

    Carries a bounded text fragment, its provenance, and the narrow
    subset of question definitions and response schemas required to
    produce candidate mappings. Only the fields relevant to the current
    fragment are included; the full questionnaire is never transmitted.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(description="UUID string identifying this mapping request.")
    source_fragment: str = Field(
        description="Bounded text from the evidence source to be mapped."
    )
    source_locator: str = Field(
        description="Location of the fragment (e.g. Sheet:APP_DATA/Row:5/Col:B)."
    )
    source_type: str = Field(
        description="Category of source (e.g. workbook_app_sheet, narrative_text)."
    )
    application_scope: str = Field(
        description=(
            "Safe application identifier used for logging. "
            "Must not contain credentials or PII."
        )
    )
    question_definitions: list[dict] = Field(
        description="Narrow subset of question definitions relevant to this fragment."
    )
    response_schemas: list[dict] = Field(
        description="Relevant response type schemas for the listed questions."
    )
    allowed_values: dict[str, list[str]] = Field(
        description="Allowed value codes per question_id."
    )
    prompt_template_version: str = Field(
        description="Version of the prompt template used to construct the AI request."
    )
    classification: str = Field(
        default="SYNTHETIC",
        description=(
            "Data classification for this request. "
            "Must be 'SYNTHETIC' for live-provider calls; "
            "client evidence is prohibited in the first slice."
        ),
    )


class MappingResult(BaseModel):
    """
    AI candidate output for a single MappingRequest.

    All proposed_mappings are candidates only. Importers and runtime AI
    create candidates, never approved facts. Proposed mappings require
    authorized review before they may become canonical answers.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(
        description="UUID string matching the originating MappingRequest."
    )
    provider: str = Field(
        description="Provider identifier (e.g. 'mock', 'openai_compatible')."
    )
    model_metadata: dict = Field(
        description=(
            "Safe model metadata (e.g. model name, fixture version). "
            "Must not contain credentials, tokens, or keys."
        )
    )
    proposed_mappings: list[ProposedMapping] = Field(
        description="Candidate mappings produced by the AI provider."
    )
    unmapped_fragments: list[str] = Field(
        description="Sub-fragments the provider could not map to any question."
    )
    warnings: list[str] = Field(
        description="Non-fatal issues encountered during mapping."
    )
    grounding_quotes: list[str] = Field(
        description=(
            "Exact quotes from source_fragment that ground the proposed_mappings. "
            "Each entry must appear verbatim in the originating source_fragment."
        )
    )
    raw_response_hash: str = Field(
        description=(
            "SHA-256 hex digest of the raw provider response payload. "
            "Used for audit traceability. 64 lowercase hex characters."
        )
    )
    validation_status: str = Field(
        description=(
            "Validation outcome: 'VALID', 'GROUNDING_FAILED', or 'SCHEMA_FAILED'."
        )
    )
