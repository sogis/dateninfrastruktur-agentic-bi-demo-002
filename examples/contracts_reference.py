from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr

class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

Scalar = StrictStr | StrictInt | FiniteFloat | StrictBool | None

class YearWindow(DTO):
    from_year: StrictInt
    to_year: StrictInt
    require_same_reference_date: StrictBool = False

class Predicate(DTO):
    field: str
    op: Literal["eq", "ne", "in", "not_in", "lt", "le", "gt", "ge", "between", "is_null", "not_null"]
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

Expr = Annotated[AggregateNode | ConstantNode | BinaryNode | PeriodNode, Field(discriminator="kind")]

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
