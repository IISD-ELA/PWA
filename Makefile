# Test targets for the PWA dev repo (pwa-raven + pwa-calibration).
#
#   make test         unit tests for both packages (mirrors GitHub CI)
#   make integration  local-only integration tests (real data/binaries;
#                      skips cleanly when those are absent)
#
# Integration tests read their inputs from env vars — see each package's
# tests/integration/README.md.
.PHONY: test test-raven test-calibration integration integration-raven integration-calibration

UNIT_DESELECT = -m "not integration and not regression and not slow"

test: test-raven test-calibration

test-raven:
	cd pwa_raven && pytest tests/unit $(UNIT_DESELECT)

test-calibration:
	cd pwa_calibration && pytest tests/unit $(UNIT_DESELECT)

integration: integration-raven integration-calibration

integration-raven:
	cd pwa_raven && pytest tests/integration

integration-calibration:
	cd pwa_calibration && pytest tests/integration
