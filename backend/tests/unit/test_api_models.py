"""Structural test: no API model can echo its input in a validation error (CLAUDE.md rule 4)."""

import importlib
import inspect
import pkgutil

from pydantic import BaseModel

import esfake.api


def _api_models() -> list[type[BaseModel]]:
    models = []
    for info in pkgutil.walk_packages(esfake.api.__path__, prefix="esfake.api."):
        module = importlib.import_module(info.name)
        for _, member in inspect.getmembers(module, inspect.isclass):
            if issubclass(member, BaseModel) and member.__module__ == module.__name__:
                models.append(member)
    return models


def test_every_api_model_hides_its_input_in_errors() -> None:
    models = _api_models()

    assert models, "the scan found no API models"
    assert [m.__name__ for m in models if not m.model_config.get("hide_input_in_errors")] == []
