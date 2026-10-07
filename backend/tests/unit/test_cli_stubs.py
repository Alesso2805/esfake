import pytest
from typer.testing import CliRunner

from esfake.cli.main import app

runner = CliRunner()


@pytest.mark.parametrize(
    ("command", "story"),
    [("eval", "EF-08"), ("eval-record", "EF-08"), ("redteam", "EF-17")],
)
def test_stub_commands_warn_and_exit_zero(command: str, story: str) -> None:
    result = runner.invoke(app, [command])

    assert result.exit_code == 0
    assert "stub" in result.stderr
    assert story in result.stderr
