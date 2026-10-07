"""Entry point for the `esfake` CLI.

`eval`, `eval-record` and `redteam` are stubs until their stories land: they print a
warning and exit 0 so `make` targets and CI can call them from Sprint 0 on.
"""

import typer

app = typer.Typer(no_args_is_help=True, help="¿EsFake? command-line tools.")


def _warn_stub(command: str, story: str) -> None:
    typer.secho(
        f"WARNING: `esfake {command}` is a stub until {story}; nothing was evaluated.",
        fg=typer.colors.YELLOW,
        err=True,
    )


@app.command("eval")
def eval_() -> None:
    """Run the evaluation gate on `eval` in cached-strict mode (EF-08)."""
    _warn_stub("eval", "EF-08")


@app.command("eval-record")
def eval_record() -> None:
    """Record missing model responses into the evaluation cache (EF-08)."""
    _warn_stub("eval-record", "EF-08")


@app.command()
def redteam() -> None:
    """Run the `redteam/dev` attack suite (EF-17)."""
    _warn_stub("redteam", "EF-17")
