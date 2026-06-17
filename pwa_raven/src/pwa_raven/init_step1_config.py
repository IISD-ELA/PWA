"""Backwards-compatibility alias for :mod:`pwa_raven.init_nc_processing_config`.

Prefer the descriptive name in new code::

    python -m pwa_raven.init_nc_processing_config nc_processing.yml

The numbered alias is equivalent::

    python -m pwa_raven.init_step1_config step1.yml
"""

from __future__ import annotations

import sys

from pwa_raven.init_nc_processing_config import (
    main,
    prompt_for_nc_processing_config as prompt_for_step1_config,
)

__all__ = ["main", "prompt_for_step1_config"]


if __name__ == "__main__":
    sys.exit(main())
