from typer.testing import CliRunner

from esfake.cli.main import app

runner = CliRunner()


def test_the_redteam_stub_warns_and_exits_zero() -> None:
    result = runner.invoke(app, ["redteam"])

    assert result.exit_code == 0
    assert "stub" in result.stderr
    assert "EF-17" in result.stderr
