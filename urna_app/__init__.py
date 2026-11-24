"""Aplicação didática de urna eletrônica."""

from .core import Candidato, Municipio, Urna
from .database import Database, DatabaseError

__all__ = ["Candidato", "Municipio", "Urna", "Database", "DatabaseError"]
