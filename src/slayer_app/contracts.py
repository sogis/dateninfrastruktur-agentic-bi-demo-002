from __future__ import annotations
from typing import Annotated, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
    model_serializer,
)


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


Scalar = StrictStr | StrictInt | FiniteFloat | StrictBool | None


class YearWindow(DTO):
    from_year: StrictInt
    to_year: StrictInt
    require_same_reference_date: StrictBool = False


class Predicate(DTO):
    field: str
    op: Literal[
        "eq",
        "ne",
        "in",
        "not_in",
        "lt",
        "le",
        "gt",
        "ge",
        "between",
        "is_null",
        "not_null",
    ]
    values: list[Scalar] = Field(default_factory=list)


class AggregateNode(DTO):
    kind: Literal["aggregate"]
    metric: str
    op: Literal["sum", "min", "max"] = "sum"
    where: list[Predicate] = Field(default_factory=list)
    grain: list[str] | None = None
    temporal_reduce: Literal["none", "mean_annual_totals"] = "none"


class ConstantNode(DTO):
    kind: Literal["constant"]
    value: StrictInt | FiniteFloat


class BinaryNode(DTO):
    kind: Literal["binary"]
    op: Literal["add", "subtract", "multiply", "divide"]
    left: Expr
    right: Expr
    scale: FiniteFloat = 1.0


class PeriodNode(DTO):
    kind: Literal["period"]
    op: Literal["shift", "fixed_year", "absolute_change", "relative_change"]
    value: Expr
    years: StrictInt | None = None
    year: StrictInt | None = None


Expr = Annotated[
    AggregateNode | ConstantNode | BinaryNode | PeriodNode, Field(discriminator="kind")
]


class OutputSpec(DTO):
    id: str
    expr: Expr


class SortSpec(DTO):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class AnalysisRequest(DTO):
    period: YearWindow
    group_by: list[str] = Field(default_factory=list)
    filters: list[Predicate] = Field(default_factory=list)
    outputs: list[OutputSpec]
    order_by: list[SortSpec] = Field(default_factory=list)
    limit: StrictInt = 100


for cls in (BinaryNode, PeriodNode, OutputSpec, AnalysisRequest):
    cls.model_rebuild()


class AnalysisError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict | None = None,
        *,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.retryable = details or {}, retryable


class ToolEnvelope(DTO):
    ok: bool
    request_id: str
    catalog_version: str | None
    data: dict | None = None
    error: dict | None = None

    @model_validator(mode="after")
    def _one_payload(self):
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("Successful envelopes require only data")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("Failed envelopes require only error")
        return self

    @model_serializer(mode="wrap")
    def _payload_only(self, handler):
        result = handler(self)
        result.pop("error" if self.ok else "data", None)
        return result


def success(request_id: str, catalog_version: str, data: dict) -> ToolEnvelope:
    return ToolEnvelope(
        ok=True, request_id=request_id, catalog_version=catalog_version, data=data
    )


def failure(
    request_id: str, catalog_version: str | None, error: AnalysisError
) -> ToolEnvelope:
    return ToolEnvelope(
        ok=False,
        request_id=request_id,
        catalog_version=catalog_version,
        error=dict(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        ),
    )


class WorkerJob(DTO):
    protocol_version: Literal[1]
    operation: Literal["validate", "analyse"]
    request_id: str
    deadline_monotonic_ns: int
    bundle_dir: str
    catalog_version: str
    allowed_model_ids: list[str]
    request: AnalysisRequest | None

    @model_validator(mode="after")
    def _operation_payload(self):
        if (self.operation == "analyse") != (self.request is not None):
            raise ValueError("Worker operation and request disagree")
        return self
