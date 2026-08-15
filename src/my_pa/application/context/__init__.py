"""Lexical/structured context preparation for `context.prepare`.

This package searches authorized planes, ranks and packs a bounded evidence
package, persists context-run metadata, and returns the packet. Remote grant
intersection is applied at prepare time so a `context.prepare` grant does not
search every readable plane. Semantic retrieval is WP-KC-07/08.
"""

from my_pa.application.context.service import ContextPreparationService

__all__ = ["ContextPreparationService"]
