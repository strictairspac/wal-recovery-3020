from pydantic import BaseModel, Field


class MergeSideInput(BaseModel):
    log_set_id: int = Field(gt=0)
    crash_after: int = Field(ge=0, le=200)


class MergePreviewInput(BaseModel):
    side_a: MergeSideInput
    side_b: MergeSideInput
    pinned: list[str] = Field(default_factory=list, max_length=200)


class MergeCommitInput(BaseModel):
    side_a: MergeSideInput
    side_b: MergeSideInput
    pinned: list[str] = Field(default_factory=list, max_length=200)
    verdict_key: str = Field(min_length=64, max_length=64)
    label: str = Field(min_length=2, max_length=120)
    new_log_set_name: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=500)
