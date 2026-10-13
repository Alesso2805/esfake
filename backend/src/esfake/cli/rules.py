"""Rule layer commands: review config/rules.yaml against any message."""

from pathlib import Path
from typing import Annotated

import typer

from esfake.shared.config import ModelSettings


def rules_check(
    text: Annotated[
        str | None,
        typer.Argument(help="Message to check. Omit it to read messages from stdin, one per line."),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="UTF-8 file, one message per line."),
    ] = None,
) -> None:
    """Show which rules and URL signals a message triggers, and its level under policy v0.

    Local aid for reviewing the rules: nothing is stored or sent. Pass messages by stdin or
    --file to keep them out of your shell history.
    """
    from esfake.pipeline.normalize import normalize
    from esfake.pipeline.redaction import build_redactor
    from esfake.pipeline.rules.check import check_message
    from esfake.pipeline.rules.detector import RuleDetector
    from esfake.pipeline.text import RawText
    from esfake.pipeline.urls.detector import UrlDetector
    from esfake.pipeline.verifier import Detector
    from esfake.shared.thresholds import load_thresholds

    if text is not None:
        messages = [text]
    elif file is not None:
        messages = file.read_text(encoding="utf-8").splitlines()
    else:
        messages = typer.get_text_stream("stdin").read().splitlines()
    messages = [m for m in messages if m.strip()]
    if not messages:
        raise typer.BadParameter("no message given")

    config_dir = ModelSettings().config_dir
    detectors: list[Detector] = [
        RuleDetector.from_config(config_dir),
        UrlDetector.from_config(config_dir),
    ]
    policy = load_thresholds(config_dir).policy_v0
    redactor = build_redactor(config_dir)
    for number, message in enumerate(messages, start=1):
        redacted = redactor.redact(normalize(RawText(message)))
        typer.echo(f"[{number}] {check_message(redacted, detectors, policy)}")


def register(app: typer.Typer) -> None:
    rules_app = typer.Typer(no_args_is_help=True, help="Rule layer: review config/rules.yaml.")
    rules_app.command("check")(rules_check)
    app.add_typer(rules_app, name="rules")
    # The same check at the top level, where someone trying the project looks first.
    app.command("check")(rules_check)
