"""Suite-wide setup."""

import os

# `import diffus.app` builds the module-level app, which starts Sentry when a
# DSN is configured; a developer's .env must not make test errors reportable.
# An env var beats .env for pydantic-settings.
os.environ["SENTRY_DSN"] = ""
