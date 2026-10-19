"""Compatibility alias for :mod:`uiprotect.anonymize`."""

from __future__ import annotations

import sys

from .. import anonymize

sys.modules[__name__] = anonymize
