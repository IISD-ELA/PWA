"""
Flood Frequency Report - Python Implementation
Converted from Jupyter Notebook: flood_freq_report.ipynb

This script performs comprehensive flood frequency analysis including:
- Data loading and cleaning
- Event detection and summarization
- Statistical plotting
- Frequency distribution fitting (Log-Pearson III)
- Confidence interval estimation via bootstrap
- Return period calculation
"""

### USER MUST UPDATE THE DATA DIRECTORY AND FILE NAME IN THE R FILE AS WELL AS THE USER INPUTS BELOW

### user_inputs
dir_path = "Data/Cypress_New/freq/"
file_name = "daily_20250911T1922.csv"
data_path = dir_path + file_name


# User input: specify watershed name
watershed_name = "Cypress River"  # Update this with desired watershed name



# Step 0. Imports and Setup
import os

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats, special
from scipy.stats import gamma as scipy_gamma
from scipy.stats import norm
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# Set style for plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

import flood_frequency_analysis as ffa


# Step 1. Load and clean data
print("=" * 80)
print("Step 1: Loading and cleaning flow data")
print("=" * 80)


flow_data = ffa.load_flow_data(data_path, param_id=1, start_year=1949)
print(f"Loaded {len(flow_data)} daily records")


# Step 2. Group and summarize to get max flow (peak and total event volume) by water year
print("\n" + "=" * 80)
print("Step 2: Group and summarize by water year")
print("=" * 80)
wy_summary, temp_path = ffa.summarize_by_water_year(flow_data, origin_month=10, filepath=dir_path + "wy_summary.csv")
print(f"Generated water year summary with {len(wy_summary)} years")


# Step 3. Generate Diagnostic Plots
print("\n" + "=" * 80)
print("Step 3: Generate diagnostic plots")
print("=" * 80)

print("\n### Daily Stats")
fig1 = ffa.plot_daily_statistics(flow_data, start_year=1950)
fig1.savefig(dir_path + 'daily_stats.png', dpi=150)

print("\n### Annual (Water Year) Statistics")
peak_years = wy_summary.sort_values('PeakFlow', ascending=False).head(3)['WaterYear']
print(peak_years)

fig2 = ffa.plot_annual_statistics(wy_summary)
fig2.savefig(dir_path + 'annual_stats.png', dpi=150)

print("\n### Daily stats with event overlay")
fig3 = ffa.plot_daily_minmax_with_overlay(flow_data, overlay_years=peak_years)
fig3.savefig(dir_path + 'overlay_years.png', dpi=150)

import subprocess

    
subprocess.run(["Rscript", "./src/r/freq_analysis_src.R"])
# subprocess.run(["Rscript", "src/r/freq_analysis_src.R"])

# Check the temp_path is the same as the one specified in the R file
print(f"\nTemporary path: {temp_path}")


# Plotting results
print("\n" + "=" * 80)
print("Plotting frequency analysis results")
print("=" * 80)

json_path = dir_path + "results.json"

# Load results from JSON
with open(json_path, 'r') as f:
    read_json = json.load(f)

print(f"Loaded keys from JSON: {read_json.keys()}")

# Extract confidence interval data
ci = pd.DataFrame(read_json['confidence'])
series = wy_summary['PeakFlow']


# Calculate plotting positions (Weibull formula)
series = wy_summary['PeakFlow'].values
n = len(series)
pp = (np.arange(1, n + 1)) / (n + 1)
sorted_series = np.sort(series)

# Set up y-axis breaks (log scale with powers of 10)
all_values = np.concatenate([series, ci.iloc[:, 1:].values.flatten()])
log_range = [np.log10(np.nanmin(all_values)), np.log10(np.nanmax(all_values))]
lower = 10 ** np.floor(log_range[0])
upper = 10 ** np.ceil(log_range[1])

ybreaks = []
if lower > 0:
    cap = lower
else :
    cap = 1
while cap < upper:
    ybreaks.extend(np.arange(cap, cap * 10, cap))
    cap *= 10

# Set up x-axis breaks (non-exceedance probabilities)
xbreaks = np.array([0.002, 0.01, 0.1, 0.25, 0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.998])
rp_labels = 1 / (1 - xbreaks)

# Create plot
fig, ax = plt.subplots(figsize=(12, 7))

# Plot observed data points using normal probability transformation
ax.scatter(norm.ppf(pp), sorted_series, s=50, alpha=0.6, label='Observed Data', color='black')

# Plot fitted curve using normal probability transformation
ax.plot(norm.ppf(ci['nonexceed_prob']), ci['true'], color='red', linewidth=2, label='Fitted LP3')
ax.plot(norm.ppf(ci['nonexceed_prob']), ci['lower'], color='red', linewidth=1, linestyle='--')
ax.plot(norm.ppf(ci['nonexceed_prob']), ci['upper'], color='red', linewidth=1, linestyle='--')

# Set up y-axis (log scale)
ax.set_yscale('log')
ax.set_yticks(ybreaks)

# Set up x-axis (probability scale with return period labels)
ax.set_xticks(norm.ppf(xbreaks))
ax.set_xticklabels([f'{rp:.4g}' for rp in rp_labels])

ax.set_ylabel('Flow (m³/s)', fontsize=12)
ax.set_xlabel('Return Period (years)', fontsize=12)
ax.set_title('Frequency Analysis - Flood Peak Flows', fontsize=14, fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, which='both', alpha=0.3)
ax.set_facecolor('white')

plt.tight_layout()
plt.savefig(dir_path + "frequency_plot.png", dpi=150)

print("\n" + "=" * 80)
print("Analysis complete! Generating report...")
print("=" * 80)

# Load template
template_path = "src/freq_analysis_tpl.md"
with open(template_path, 'r') as f:
    template_content = f.read()

# Generate recurrence table from freq_analysis data
freq_data = read_json['event_returns']
event_returns = "| Return Period (years) | Flow Estimate (m³/s) | Nearest Event (Water Year) |\n"
event_returns += "|---|---|---|\n"
for item in freq_data:
    rp = item['ReturnPeriod']
    estimate = item['Q']
    nearest_event = item['nearest_event']
    event_returns += f"| {rp:.2f} | {estimate:.2f} | {nearest_event} |\n"

# Extract values from results.json
mgbt_removed = read_json['mgbt_removed'][0]
mgbt_threshold = read_json['mgbt_threshold'][0]

# Build goodness of fit summary (handle null values)
gof = read_json['peak_flow_goodness_fit']
if gof['ad_pval'][0] is not None:
    peak_flow_gof = f"Anderson-Darling: p-value = {gof['ad_pval'][0]:.4f}"
else:
    peak_flow_gof = "Goodness of fit statistics not available"

# Replace placeholders in template
output_content = template_content.replace('{watershed}', watershed_name)
output_content = output_content.replace('{event_returns}', event_returns)
output_content = output_content.replace('{mgbt_removed}', str(mgbt_removed))
output_content = output_content.replace('{mgbt_threshold}', str(mgbt_threshold))
output_content = output_content.replace('{peak_flow_goodness_fit}', peak_flow_gof)

# Write to output file
output_path = dir_path + "freq_analysis.md"

with open(output_path, 'w') as f:
    f.write(output_content)

print(f"\n✓ Report generated successfully: {output_path}")
print(f"  Watershed: {watershed_name}")
print(f"  PILF events removed: {mgbt_removed}")
print(f"  PILF threshold: {mgbt_threshold}")

