"""Adapters that talk to the outside world.

Infrastructure implements ports and executes I/O. Composition — deciding which
adapter runs with which configuration — belongs to bootstrap and entry points,
so nothing here reads process settings for itself.
"""
