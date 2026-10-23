"""load(path) picks the right format plug-in (formats/) and returns a profiled Dataset."""

from __future__ import annotations

from pathlib import Path

from ..model import Dataset
from ..profile import profile_dataset


def detect(data: bytes, name: str) -> str:
    from .. import formats
    return formats.detect(data, name).name


def parse_bytes(data: bytes, name: str, profile: bool = True) -> Dataset:
    from .. import formats
    ds = formats.detect(data, name).read(data, name)
    if profile:
        profile_dataset(ds)
    return ds


def load(path: str | Path, profile: bool = True) -> Dataset:
    p = Path(path)
    return parse_bytes(p.read_bytes(), p.name, profile=profile)
