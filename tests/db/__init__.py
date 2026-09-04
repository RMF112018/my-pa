"""Shared PostgreSQL test provisioning.

Ordinary current-schema tests consume the worker-head template and clone path.
Migration and loader tests consume empty disposable databases. Nothing in this
package may target the configured canonical application database.
"""
