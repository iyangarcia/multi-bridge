"""Multi Bridge: map any hospital format onto the shape your application expects."""

from .model import Dataset, Field
from .parsers import load

__all__ = ["Dataset", "Field", "load"]
__version__ = "0.1.0"
