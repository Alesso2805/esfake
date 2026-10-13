"""Entry point for the `esfake` CLI: composes the command groups of the other modules."""

import typer

from esfake.cli import corpus_data, corpus_review, evaluation, rules, serving, similarity

app = typer.Typer(no_args_is_help=True, help="¿EsFake? command-line tools.")
evaluation.register(app)
serving.register(app)
rules.register(app)
similarity.register(app)

corpus_app = typer.Typer(no_args_is_help=True, help="Public corpus: add, review pairs, assign.")
corpus_data.register(corpus_app)
corpus_review.register(corpus_app)
app.add_typer(corpus_app, name="corpus")
