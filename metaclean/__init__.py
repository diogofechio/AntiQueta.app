"""AntiQueta.app: remove metadados de imagens localmente, sem recomprimir."""

from .core import FormatError, clean, cleaned_name, detect, inspect

__all__ = ["FormatError", "clean", "cleaned_name", "detect", "inspect"]
__version__ = "0.1.0"
