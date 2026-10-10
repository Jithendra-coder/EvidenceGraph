from pydantic import BaseModel, ConfigDict, Field


class GroundedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=8, max_length=1000)
    citationIds: list[str] = Field(min_length=1, max_length=8)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=8, max_length=1200)
    summaryCitationIds: list[str] = Field(min_length=1, max_length=8)
    findings: list[GroundedFinding] = Field(max_length=6)


class SecContact(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class SyncRequest(BaseModel):
    cik: str
    form: str
    accession: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")


class ResearchRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1200)
    companies: list[str] = Field(default_factory=list, max_length=5)
    includeFinancials: bool = True


class CompareRequest(BaseModel):
    companies: list[str] = Field(min_length=2, max_length=5)
    metric: str = "revenue"
    periods: int = Field(default=3, ge=2, le=10)
