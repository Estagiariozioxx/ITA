"""Acesso aos dados: o extrato do cliente no BigQuery (ou no CSV local)."""
from .extratos import ClienteNaoEncontrado, get_repo

__all__ = ["ClienteNaoEncontrado", "get_repo"]
