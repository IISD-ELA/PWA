"""Backwards-compatibility alias for :mod:`pwa_raven.init_raven_inputs_config`.

Prefer the descriptive name in new code::

    python -m pwa_raven.init_raven_inputs_config raven_inputs.yml

The numbered alias is equivalent::

    python -m pwa_raven.init_step2_config step2.yml
"""

from __future__ import annotations

import sys

from pwa_raven.init_raven_inputs_config import (
    main,
    prompt_for_raven_inputs_config as prompt_for_step2_config,
)

__all__ = ["main", "prompt_for_step2_config"]


if __name__ == "__main__":
    sys.exit(main())
