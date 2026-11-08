"""Lecture du texte d'un PDF ou d'un fichier texte."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class UnreadableDocument(Exception):
    pass


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise UnreadableDocument(f"{path.name} : PDF protégé par mot de passe")
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except (PdfReadError, OSError, ValueError) as exc:
            raise UnreadableDocument(f"{path.name} : PDF illisible ({exc.__class__.__name__})") from exc
    raise UnreadableDocument(f"{path.name} : format non géré (attendu .pdf ou .txt)")
