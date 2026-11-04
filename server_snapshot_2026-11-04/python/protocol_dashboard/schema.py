from pydantic import BaseModel, Field
from typing import Literal, Optional
class ReportRequest(BaseModel):
    report_type: Literal["eos", "memo"]
    mode: Optional[str] = None
    group_ids: list[int] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    event_filter: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
