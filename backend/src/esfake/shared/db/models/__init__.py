"""ORM models. Importing this package registers every table on `Base.metadata`."""

from esfake.shared.db.models.corpus import Modality, PipelineManifest
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
    "Feedback",
    "Modality",
    "PipelineManifest",
    "Signal",
    "Url",
    "Verdict",
    "Verification",
    "VerificationQueue",
]
