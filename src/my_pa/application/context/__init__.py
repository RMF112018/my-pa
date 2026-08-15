"""Lexical/structured context preparation for `context.prepare`.

This package searches authorized planes, ranks and packs a bounded evidence
package, and returns it. Persistence of context runs is WP-KC-04; grant
intersection is WP-KC-05; semantic retrieval is WP-KC-07/08.
"""

from my_pa.application.context.service import ContextPreparationService

__all__ = ["ContextPreparationService"]
