"""CLI: ``python -m pwa_raven.run_step2 --config step2.yml``.

Two equivalent ways to drive Step 2:

* **From the shell** (one-shot, after ``init_step2_config``)::

    python -m pwa_raven.run_step2 --config step2.yml
    python -m pwa_raven.run_step2 --config step2.yml --log-level DEBUG

* **From Python (notebook or script)**::

    from pwa_raven.step2 import Step2Config, run_step2
    config = Step2Config.from_yaml("step2.yml")
    result = run_step2(config)
    print(result.rvi, result.rvh, result.wsc_rvt)

The CLI is a thin wrapper around the same :func:`pwa_raven.step2.run_step2`
the notebook would import — no behaviour difference.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.step2 import Step2Config, run_step2

# Re-export for notebook convenience.
__all__ = ["run_step2", "Step2Config", "main"]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-run-step2",
        description=(
            "Run the PWA Step 2 pipeline (Raven .rv* file generation + "
            "calibration templates)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("step2.yml"),
        help="Path to the step2.yml config file (default: ./step2.yml).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.config.is_file():
        print(
            f"Config file not found: {args.config}\n"
            "Generate one with: python -m pwa_raven.init_step2_config step2.yml",
            file=sys.stderr,
        )
        return 1

    config = Step2Config.from_yaml(args.config)
    result = run_step2(config)

    print()
    print(f"RVI                : {result.rvi}")
    print(f"RVC                : {result.rvc}")
    print(f"RVP                : {result.rvp}")
    print(f"RVH                : {result.rvh}")
    print(f"Model RVT          : {result.model_rvt}")
    print(f"Channel RVP        : {result.channel_rvp}")
    print(f"WSC RVT            : {result.wsc_rvt}")
    print(f"WSC outlet text    : {result.wsc_outlet_txt}")
    if result.rvh_template is not None:
        print(f"RVH template       : {result.rvh_template}")
        print(f"RVP template       : {result.rvp_template}")
        print(f"Channel RVP tpl    : {result.channel_rvp_template}")
        print(f"HRU areas CSV      : {result.hru_areas_csv}")
        print(f"tp/tc CSV          : {result.tp_tc_csv}")
    if result.aspect_ratios_csv is not None:
        print(f"Aspect ratios CSV  : {result.aspect_ratios_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
