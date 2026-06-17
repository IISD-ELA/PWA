"""CLI: ``python -m pwa_raven.run_raven_inputs --config raven_inputs.yml``.

Two equivalent ways to drive the Raven input file generation pipeline:

* **From the shell** (one-shot, after ``init_raven_inputs_config``)::

    python -m pwa_raven.run_raven_inputs --config raven_inputs.yml
    python -m pwa_raven.run_raven_inputs --config raven_inputs.yml --log-level DEBUG

* **From Python (notebook or script)**::

    from pwa_raven.raven_inputs import RavenInputsConfig, run_raven_inputs
    config = RavenInputsConfig.from_yaml("raven_inputs.yml")
    result = run_raven_inputs(config)
    print(result.rvi, result.rvh, result.wsc_rvt)

The CLI is a thin wrapper around :func:`pwa_raven.raven_inputs.run_raven_inputs`
— no behaviour difference. The :mod:`pwa_raven.run_step2` module is a
backwards-compatibility alias for this one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.raven_inputs import RavenInputsConfig, run_raven_inputs

# Re-export for notebook convenience.
__all__ = ["run_raven_inputs", "RavenInputsConfig", "main"]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-raven-inputs",
        description=(
            "Run the PWA Raven input file generation pipeline (.rv* files "
            "+ WSC RVT + calibration templates + aspect ratios)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("raven_inputs.yml"),
        help="Path to the raven_inputs.yml config file (default: ./raven_inputs.yml).",
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
            "Generate one with: python -m pwa_raven.init_raven_inputs_config "
            "raven_inputs.yml",
            file=sys.stderr,
        )
        return 1

    config = RavenInputsConfig.from_yaml(args.config)
    result = run_raven_inputs(config)

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
