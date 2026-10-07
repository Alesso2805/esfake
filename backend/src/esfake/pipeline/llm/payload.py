"""What the judge receives (ADR-0001 §2), in its minimal form until EF-14.

It takes RedactedText only, so raw text cannot reach the provider; the message travels as
delimited data, never as instructions.
"""

from esfake.pipeline.text import RedactedText


def judge_payload(message: RedactedText) -> dict[str, object]:
    return {"message": message.value}
