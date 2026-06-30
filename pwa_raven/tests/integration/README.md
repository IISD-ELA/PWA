# pwa-raven integration tests

End-to-end tests that generate Raven input files from a real config and run the
real **Raven** binary against them. They are **local-only** — GitHub CI runs
`pytest tests/unit` and never enters this directory, so no dataset or binary is
ever needed in CI.

Every test **skips cleanly** when its inputs are absent, so `pytest
tests/integration` on a bare checkout reports skips, not failures.

## Inputs (environment)

| Variable | Purpose | Required for |
|---|---|---|
| `PWA_RAVEN_INPUTS_CONFIG` | Path to a filled-in `raven_inputs.yml` (`pwa-init-raven-inputs`) | both tests |
| `PWA_RAVEN_BINARY` | Explicit Raven executable path (else resolved from PATH) | the binary test only |

## Run

```bash
# From the PWA repo root:
make integration-raven

# Or directly:
cd pwa_raven
PWA_RAVEN_INPUTS_CONFIG=/path/to/raven_inputs.yml \
  pytest tests/integration -v

# Skip the slow real-Raven run, keep the fast structural check:
PWA_RAVEN_INPUTS_CONFIG=/path/to/raven_inputs.yml \
  pytest tests/integration -m "not slow"
```

## What they prove

- `regression` (data, no binary): the full generation step emits non-empty,
  directive-bearing `.rvi/.rvp/.rvh/.rvc/.rvt` files — catches a broken
  template substitution.
- `integration` + `slow` (data + Raven): the real Raven binary parses and runs
  the generated model with no error (including the silent `Raven_errors.txt`
  case).
