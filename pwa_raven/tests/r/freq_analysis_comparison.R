#!/usr/bin/env Rscript
# freq_analysis_comparison.R
#
# Validation-only script: fits LP3 using R's lmomco and MGBT packages on
# a wy_summary.csv produced by the Python test, then writes
# r_comparison_results.json so the pytest comparison test can check agreement.
#
# Usage:
#   Rscript freq_analysis_comparison.R <data_dir>
#
# Reads:  <data_dir>/wy_summary.csv
# Writes: <data_dir>/r_comparison_results.json

suppressPackageStartupMessages({
  library(lmomco)
  library(MGBT)
  library(dplyr)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript freq_analysis_comparison.R <data_dir>")

data_dir <- args[1]
wy_path  <- file.path(data_dir, "wy_summary.csv")
out_path <- file.path(data_dir, "r_comparison_results.json")

if (!file.exists(wy_path)) stop(paste("File not found:", wy_path))

# ── Load and prepare ─────────────────────────────────────────────────────────
wy <- read.csv(wy_path)

# One row per water year – keep highest PeakFlow per year, drop NA
annual <- wy %>%
  group_by(WaterYear) %>%
  filter(PeakFlow == max(PeakFlow)) %>%
  ungroup() %>%
  filter(!is.na(PeakFlow))

series    <- annual$PeakFlow
log_series <- log10(series)

# ── MGBT ─────────────────────────────────────────────────────────────────────
mgbt_result <- MGBT(series)
lo_thresh   <- mgbt_result$LOThresh

# ── LP3 via L-moments (full series, matching current R notebook behaviour) ───
lmom   <- lmom.ub(log_series)
params <- lmom2par(lmom, type = "pe3")
# para[1] = mu (mean in log space), para[2] = sigma, para[3] = gamma (skewness)
mu    <- params$para[1]
sigma <- params$para[2]
gamma <- params$para[3]

# ── Quantiles at standard non-exceedance probabilities ───────────────────────
std_neps <- c(0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.998)
std_rps  <- 1 / (1 - std_neps)

log_quantiles <- par2qua(f = std_neps, para = params)  # still in log10 space
quantiles_orig <- 10^log_quantiles

# ── Per-event return periods ──────────────────────────────────────────────────
return_periods <- numeric(nrow(annual))
cdfs           <- numeric(nrow(annual))
for (i in seq_len(nrow(annual))) {
  log_q          <- log10(annual$PeakFlow[i])
  cdf_val        <- cdfpe3(log_q, params)       # lmomco CDF for PE3
  return_periods[i] <- 1 / (1 - cdf_val)
  cdfs[i]        <- cdf_val
}

# ── Write JSON ────────────────────────────────────────────────────────────────
results <- list(
  mgbt_threshold = lo_thresh,
  lp3_params = list(loc = mu, scale = sigma, skew = gamma),
  standard_quantiles = data.frame(
    nep = std_neps,
    rp  = std_rps,
    q   = quantiles_orig
  ),
  annual_return_periods = data.frame(
    WaterYear    = annual$WaterYear,
    PeakFlow     = annual$PeakFlow,
    CDF          = cdfs,
    ReturnPeriod = return_periods
  )
)

write_json(results, out_path, auto_unbox = TRUE, digits = 10)
cat("R comparison results written to", out_path, "\n")
