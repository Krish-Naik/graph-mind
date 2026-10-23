"""Request/response models. These ARE the contract between Express and the engine."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class LookupSpec(BaseModel):
    """Optional second file that maps an ID in the main file to a behavior category.
    OULAD example: studentVle.id_site -> vle.activity_type"""
    path: str
    source_key: str            # column in the main file
    lookup_key: str            # column in the lookup file
    split_delimiter: Optional[str] = None   # e.g. '|' for MovieLens genres 'Action|Comedy'


class LabelSpec(BaseModel):
    """Optional ground-truth label per entity (used only for NMI)."""
    path: str
    entity_col: str
    label_col: str


class Mapping(BaseModel):
    path: str                                  # main data file (CSV)
    format: Literal["long", "wide"] = "long"
    entity_col: str
    # long format: behavior_col (+ value_col) ; wide format: feature_cols
    behavior_col: Optional[str] = None         # lives in lookup file if lookup is set
    value_col: Optional[str] = None
    agg: Literal["sum", "count", "mean", "max"] = "sum"
    feature_cols: Optional[list[str]] = None
    lookup: Optional[LookupSpec] = None
    label: Optional[LabelSpec] = None


class Params(BaseModel):
    sample_size: Optional[int] = Field(300, ge=10, le=5000)   # None = use all (capped)
    random_state: int = 42
    graph_method: Literal["threshold", "knn"] = "threshold"
    threshold: float = Field(0.85, ge=0.0, le=1.0)
    knn_k: int = Field(10, ge=1, le=100)
    algorithms: list[Literal["louvain", "leiden", "lpa"]] = ["louvain", "leiden", "lpa"]
    primary_algorithm: Literal["louvain", "leiden", "lpa", "best_modularity"] = "louvain"
    tier_method: Literal["quantile", "thresholds"] = "quantile"
    tier_labels: list[str] = ["Low Engagement / At-Risk", "Moderate Engagement", "High Engagement"]
    low_cut: Optional[float] = None            # for tier_method="thresholds"
    high_cut: Optional[float] = None
    min_community_size: int = Field(1, ge=1)   # smaller communities are flagged "Outlier group"
    max_edges_returned: int = 20000


class RunRequest(BaseModel):
    mapping: Mapping
    params: Params = Params()
    out_dir: Optional[str] = None              # where classified CSV is written


class CheckRequest(BaseModel):
    mapping: Mapping
    sample_size: Optional[int] = Field(300, ge=10, le=5000)
    random_state: int = 42
