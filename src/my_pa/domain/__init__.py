"""Provider-independent domain model.

Domain modules depend only on the Python standard library. They must not import
transports, ORM models, provider SDKs, configuration loaders, or Pydantic.
"""
