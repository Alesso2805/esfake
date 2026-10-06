"""ORM models. Importing this package registers every table on `Base.metadata`."""

from esfake.shared.db.models.corpus import (
    CorpusMessage,
    EvalResult,
    EvalRun,
    LabelingTask,
    Modality,
    PipelineManifest,
)
from esfake.shared.db.models.verification import (
    ChannelIdentity,
    Feedback,
    Signal,
    Url,
    Verdict,
    Verification,
    VerificationQueue,
)

__all__ = [
    "ChannelIdentity",
    "CorpusMessage",
    "EvalResult",
    "EvalRun",
    "Feedback",
    "LabelingTask",
    "Modality",
    "PipelineManifest",
    "Signal",
    "Url",
    "Verdict",
    "Verification",
    "VerificationQueue",
]
