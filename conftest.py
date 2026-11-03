"""Keep test runs from littering the working tree with ``__pycache__``.

pytest imports this file before any test module, so turning off bytecode
writing here covers ``src/``, ``tests/`` and ``tools/``.  Only the bytecode for
this file itself can still be written, under ``__pycache__/conftest.*``; run
``uv run python -B -m pytest`` to suppress even that.
"""

import sys

sys.dont_write_bytecode = True
