Synthetic plain-text fixture for the read-only source provider.

This file is invented. It contains no personal data and no content copied from
any real source. It exists so that a provider test can read bytes, truncate
them at a ceiling, and observe a version, without touching anything private.

The line below is long enough that a small max_bytes ceiling cuts through it,
which is what makes the truncation assertion meaningful rather than incidental.
