"""
Flood Frequency Analysis - Python Implementation
Converted from R script: Freq_Analysis_clean.R

This script performs comprehensive flood frequency analysis including:
- Data loading and cleaning
- Event detection and summarization
- Statistical plotting
- Frequency distribution fitting (Log-Pearson III)
- Confidence interval estimation via bootstrap
- Return period calculation
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats, special
from scipy.stats import gamma as scipy_gamma
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Set style for plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

# ============================================================================
# SECTION 1: LOAD AND CLEAN FLOW DATA
# ============================================================================

def load_flow_data(filepath, param_id=1, start_year=None, end_year=None, ):
    """
    Load and clean hydrological flow data from CSV file.
    
    Parameters:
    -----------
    filepath : str
        Path to CSV file with columns: ID, PARAM, Date, Value, SYM
    param_id : int
        Parameter ID to filter (1 = flow, 2 = water level, etc.)
    start_year : int, optional
        Start year for filtering
    end_year : int, optional
        End year for filtering
    
    Returns:
    --------
    pandas.DataFrame
        Cleaned dataframe with Date and Value columns
    """
    # Read CSV, skipping first row of metadata
    df = pd.read_csv(filepath, header=0, skiprows=1)
    
    # Keep only specified parameter (remove water level, etc.)
    df = df[df['PARAM'] == param_id].copy()
    
    # Remove unnecessary columns
    df = df[['Date', 'Value']].copy()
    
    # Convert date column
    df['Date'] = pd.to_datetime(df['Date'], format='%Y/%m/%d')
    
    # Filter by year if specified
    if start_year:
        df = df[df['Date'].dt.year >= start_year]
    if end_year:
        df = df[df['Date'].dt.year <= end_year]
    
    # Remove missing values
    df = df.dropna(subset=['Value'])
    
    # Reset index
    df = df.reset_index(drop=True)
    
    return df


def calculate_water_year(date_series, origin_month=10):
    """
    Calculate water year for a date series.
    Water year starts in October (month 10) by default.
    
    Parameters:
    -----------
    date_series : pandas.Series
        Series of datetime objects
    origin_month : int
        Month when water year begins (10 = October for North American hydrology)
    
    Returns:
    --------
    pandas.Series
        Water year for each date
    """
    water_year = date_series.dt.year.copy()
    # If month is after origin month, use next year's water year
    water_year[date_series.dt.month >= origin_month] += 1
    return water_year


# ============================================================================
# SECTION 2: GROUP AND SUMMARIZE TO GET MAX FLOW (PEAK & TOTAL) BY WATER YEAR
# ============================================================================

def detect_flow_events(df, delta_y=20, delta_x=5):
    """
    Detect flow events (floods) using simple threshold method.
    Identifies local minima separated by specified thresholds.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with 'Date' and 'Value' columns
    delta_y : float
        Minimum change in flow for event detection
    delta_x : int
        Minimum gap (days) between events
    
    Returns:
    --------
    pandas.DataFrame
        Event summary with start, end, peak dates and values
    """
    values = df['Value'].values
    dates = df['Date'].values
    
    events = []
    in_event = False
    event_start_idx = 0
    
    # Simple event detection: find local minima and maxima
    for i in range(1, len(values) - 1):
        if values[i] < values[i-1] and values[i] < values[i+1]:
            if not in_event:
                event_start_idx = i
                in_event = True
        elif in_event and values[i] > values[i-1] + delta_y:
            # Event ended
            event_end_idx = i
            peak_idx = np.argmax(values[event_start_idx:event_end_idx]) + event_start_idx
            
            events.append({
                'event_start_date': pd.Timestamp(dates[event_start_idx]),
                'event_end_date': pd.Timestamp(dates[event_end_idx]),
                'peak_flow_date': pd.Timestamp(dates[peak_idx]),
                'max_flow': float(values[peak_idx])
            })
            in_event = False
    
    return pd.DataFrame(events)


def summarize_by_water_year(df, origin_month=10, filepath='Data/freq/temp_summary.csv'):
    """
    Summarize flow data by water year: get annual maximum and total volume.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with 'Date' and 'Value' columns
    origin_month : int
        Water year origin month
    
    Returns:
    --------
    pandas.DataFrame
        Summary with annual peak flow, volume, and water year
    """
    df = df.copy()
    df['WaterYear'] = calculate_water_year(df['Date'], origin_month)
    df['Month'] = df['Date'].dt.month
    
    # Group by water year
    summary_list = []
    for wy in sorted(df['WaterYear'].unique()):
        wy_data = df[df['WaterYear'] == wy]
        
        # Peak flow (annual maximum)
        peak_idx = wy_data['Value'].idxmax()
        peak_flow = wy_data.loc[peak_idx, 'Value']
        peak_date = wy_data.loc[peak_idx, 'Date']
        
        # Total volume (sum of daily flows converted to m3)
        total_volume = (wy_data['Value'] * 86400).sum()  # m3/s * 86400 sec/day = m3
        
        # Classify as spring or annual peak
        peak_month = peak_date.month
        flow_type = "Spring" if 3 <= peak_month <= 6 else "Annual"
        
        summary_list.append({
            'WaterYear': wy,
            'PeakFlowDate': peak_date,
            'PeakFlow': peak_flow,
            'TotalVolume': total_volume,
            'Type': flow_type
        })
    
    summary_df = pd.DataFrame(summary_list)
    summary_df.to_csv(filepath, index=False)  # Save summary for reference

    return summary_df, filepath


# ============================================================================
# SECTION 3: GENERATE PLOTS
# ============================================================================

def plot_daily_statistics(df, start_year=None, end_year=None, title="Daily Flow Statistics"):
    """
    Plot daily statistics: min-max range, median, and percentiles.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with 'Date' and 'Value' columns
    start_year : int, optional
        Filter data by start year
    end_year : int, optional
        Filter data by end year
    title : str
        Plot title
    """
    if start_year or end_year:
        mask = pd.Series([True] * len(df))
        if start_year:
            mask &= df['Date'].dt.year >= start_year
        if end_year:
            mask &= df['Date'].dt.year <= end_year
        plot_data = df[mask].copy()
    else:
        plot_data = df.copy()
    
    # Create day-of-year column
    plot_data = plot_data.copy()
    plot_data['DayOfYear'] = plot_data['Date'].dt.dayofyear
    
    # Calculate daily statistics
    daily_stats = plot_data.groupby('DayOfYear')['Value'].agg([
        ('Minimum', 'min'),
        ('Q25', lambda x: x.quantile(0.25)),
        ('Median', 'median'),
        ('Q75', lambda x: x.quantile(0.75)),
        ('Maximum', 'max')
    ]).reset_index()
    
    # Create plot
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Plot min-max ribbon
    ax.fill_between(daily_stats['DayOfYear'], 
                     daily_stats['Minimum'], 
                     daily_stats['Maximum'],
                     alpha=0.3, color='lightblue', label='Min-Max Range')
    
    # Plot quartile bands
    ax.fill_between(daily_stats['DayOfYear'],
                     daily_stats['Q25'],
                     daily_stats['Q75'],
                     alpha=0.3, color='skyblue', label='Q25-Q75')
    
    # Plot median
    ax.plot(daily_stats['DayOfYear'], daily_stats['Median'], 
            color='black', linewidth=2, label='Median')
    
    # Format x-axis with months
    month_days = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365])
    month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan']
    ax.set_xticks(month_days)
    ax.set_xticklabels(month_labels)
    
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Flow (m³/s)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig


def plot_annual_statistics(df, title="Annual Flow Statistics"):
    """
    Plot annual statistics: annual maximum flows over time.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with 'WaterYear', 'PeakFlow', and 'Type' columns
    title : str
        Plot title
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Separate spring and annual peaks
    spring = df[df['Type'] == 'Spring']
    annual = df[df['Type'] == 'Annual']
    
    ax.scatter(spring['WaterYear'], spring['PeakFlow'], 
              label='Spring', alpha=0.6, s=60, color='blue')
    ax.scatter(annual['WaterYear'], annual['PeakFlow'], 
              label='Annual', alpha=0.6, s=60, color='red')
    
    ax.set_xlabel('Water Year', fontsize=12)
    ax.set_ylabel('Peak Flow (m³/s)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig


def plot_daily_minmax_with_overlay(df, overlay_years=[1975, 1986, 2011, 2022], 
                                   title="Daily Flow with Selected Years"):
    """
    Plot daily min-max statistics with overlay of specific flood years.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with 'Date' and 'Value' columns
    overlay_years : list
        List of years to highlight
    title : str
        Plot title
    """
    plot_data = df.copy()
    plot_data['DayOfYear'] = plot_data['Date'].dt.dayofyear
    plot_data['Year'] = plot_data['Date'].dt.year
    
    # Calculate daily statistics
    daily_stats = plot_data.groupby('DayOfYear')['Value'].agg([
        ('Minimum', 'min'),
        ('Median', 'median'),
        ('Maximum', 'max')
    ]).reset_index()
    
    # Filter overlay data
    overlay_data = plot_data[plot_data['Year'].isin(overlay_years)].copy()
    
    # Create plot
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # Min-max ribbon
    ax.fill_between(daily_stats['DayOfYear'],
                     daily_stats['Minimum'],
                     daily_stats['Maximum'],
                     alpha=0.3, color='lightblue', label='Min-Max Range')
    
    # Median line
    ax.plot(daily_stats['DayOfYear'], daily_stats['Median'],
            color='black', linewidth=2, label='Median')
    
    # Overlay selected years
    colors = {'1975': 'green', '1986': 'blue', '2011': 'orange', '2022': 'purple'}
    for year in overlay_years:
        if year in overlay_data['Year'].values:
            year_data = overlay_data[overlay_data['Year'] == year].sort_values('DayOfYear')
            ax.plot(year_data['DayOfYear'], year_data['Value'],
                   color=colors.get(str(year), 'gray'), linewidth=1.5,
                   label=f'{year}', alpha=0.8)
    
    # Format x-axis
    month_days = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365])
    month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan']
    ax.set_xticks(month_days)
    ax.set_xticklabels(month_labels)
    
    ax.set_xlabel('Month', fontsize=12)
    ax.set_ylabel('Flow (m³/s)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', ncol=2)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig




# ============================================================================
# SECTION 5: FREQUENCY ANALYSIS (LOG-PEARSON III DISTRIBUTION)
# ============================================================================

# class LogPearsonIII:
#     """
#     Log-Pearson Type III distribution for frequency analysis.
    
#     This is the standard distribution used in flood frequency analysis
#     across North America.
#     """
    
#     def __init__(self):
#         """Initialize the LP3 distribution."""
#         self.params = None
#         self.transformed_data = None
    
#     def fit(self, data):
#         """
#         Fit LP3 distribution to data using method of moments (L-moments).
        
#         Parameters:
#         -----------
#         data : array-like
#             Flow data (not log-transformed)
        
#         Returns:
#         --------
#         dict
#             Fitted parameters {mu, sigma, gamma}
#         """
#         data = np.asarray(data)
        
#         # Log-transform data
#         log_data = np.log10(data)
#         self.transformed_data = log_data
        
#         # Calculate L-moments (simplified version)
#         sorted_data = np.sort(log_data)
#         n = len(sorted_data)
        
#         # L1 (mean)
#         l1 = np.mean(sorted_data)
        
#         # L2 (L-moment of order 2)
#         weights = (np.arange(1, n + 1) - 0.5) / n
#         l2 = np.sum((2 * weights - 1) * sorted_data) / n
        
#         # Coefficient of variation (L-CV)
#         t3 = l2 / l1 if l1 != 0 else 0
        
#         # Convert to standard moments for PE3
#         # Using Pearson Type III moments
#         mu = np.mean(log_data)
#         sigma = np.std(log_data, ddof=1)
        
#         # Skewness (gamma parameter for LP3)
#         if sigma > 0:
#             gamma = stats.skew(log_data)
#         else:
#             gamma = 0
        
#         self.params = {'mu': mu, 'sigma': sigma, 'gamma': gamma}
        
#         return self.params
    
#     def cdf(self, x, mu=None, sigma=None, gamma=None):
#         """
#         Calculate cumulative distribution function.
        
#         Parameters:
#         -----------
#         x : array-like
#             Values (original scale, not log-transformed)
#         mu, sigma, gamma : float
#             Parameters (use self.params if not provided)
        
#         Returns:
#         --------
#         numpy.ndarray
#             Probability values
#         """
#         if mu is None:
#             mu, sigma, gamma = self.params['mu'], self.params['sigma'], self.params['gamma']
        
#         x = np.asarray(x)
#         x_log = np.log10(x)
        
#         # Pearson Type III CDF
#         if sigma <= 0 or gamma == 0:
#             return np.full_like(x_log, np.nan, dtype=float)
        
#         # Transform to gamma distribution
#         alpha = 4 / (gamma ** 2)
#         beta = sigma * np.abs(gamma) / 2
#         xi = mu - 2 * sigma / gamma
#         z = (x_log - xi) / beta
        
#         # Compute CDF
#         if gamma > 0:
#             cdf = scipy_gamma.cdf(z, a=alpha)
#         else:
#             cdf = 1 - scipy_gamma.cdf(-z, a=alpha)
        
#         # Constrain to [0, 1]
#         cdf = np.clip(cdf, 0.001, 0.999)
        
#         return cdf
    
#     def ppf(self, q, mu=None, sigma=None, gamma=None):
#         """
#         Calculate percent point function (quantiles).
        
#         Parameters:
#         -----------
#         q : array-like
#             Non-exceedance probabilities
#         mu, sigma, gamma : float
#             Parameters (use self.params if not provided)
        
#         Returns:
#         --------
#         numpy.ndarray
#             Quantile values (original scale)
#         """
#         if mu is None:
#             mu, sigma, gamma = self.params['mu'], self.params['sigma'], self.params['gamma']
        
#         q = np.asarray(q)
#         q = np.clip(q, 0.001, 0.999)
        
#         alpha = 4 / (gamma ** 2)
#         beta = sigma * np.abs(gamma) / 2
#         xi = mu - 2 * sigma / gamma
        
#         # Compute quantiles
#         if gamma > 0:
#             z = scipy_gamma.ppf(q, a=alpha)
#         else:
#             z = -scipy_gamma.ppf(1 - q, a=alpha)
        
#         x_log = xi + beta * z
#         x = 10 ** x_log
        
#         return x


# def frequency_analysis(data, dist='lp3', return_periods=None):
#     """
#     Perform frequency analysis on extreme value data.
    
#     Parameters:
#     -----------
#     data : array-like
#         Flow data
#     dist : str
#         Distribution type ('lp3' for Log-Pearson III)
#     return_periods : list, optional
#         Return periods to compute quantiles for
    
#     Returns:
#     --------
#     dict
#         Contains fitted distribution and quantile estimates
#     """
#     if return_periods is None:
#         return_periods = [2, 5, 10, 25, 50, 100, 200, 500, 1000]
    
#     # Fit distribution
#     if dist.lower() == 'lp3':
#         dist_obj = LogPearsonIII()
#         params = dist_obj.fit(data)
#     else:
#         raise ValueError(f"Distribution '{dist}' not implemented")
    
#     # Convert return periods to non-exceedance probabilities
#     nep = 1 - (1 / np.array(return_periods))
    
#     # Compute quantiles
#     quantiles = dist_obj.ppf(nep)
    
#     # Create output dataframe
#     output_df = pd.DataFrame({
#         'ReturnPeriod': return_periods,
#         'NonExceedanceProbability': nep,
#         'Quantile': quantiles
#     })
    
#     return {
#         'distribution': dist_obj,
#         'parameters': params,
#         'output': output_df
#     }


# def bootstrap_confidence_interval(data, dist_obj, n_resamples=2500, ci=0.90,
#                                  return_periods=None):
#     """
#     Compute confidence intervals for quantile estimates via bootstrap.
    
#     Parameters:
#     -----------
#     data : array-like
#         Original flow data
#     dist_obj : LogPearsonIII
#         Fitted distribution object
#     n_resamples : int
#         Number of bootstrap resamples
#     ci : float
#         Confidence level (e.g., 0.90 for 90%)
#     return_periods : list, optional
#         Return periods for which to estimate CI
    
#     Returns:
#     --------
#     pandas.DataFrame
#         Confidence interval bounds for each return period
#     """
#     if return_periods is None:
#         return_periods = [2, 5, 10, 25, 50, 100, 200, 500, 1000]
    
#     nep = 1 - (1 / np.array(return_periods))
    
#     # Store bootstrap quantile estimates
#     bootstrap_quantiles = np.zeros((n_resamples, len(return_periods)))
    
#     # Parameters for resampling
#     mu = dist_obj.params['mu']
#     sigma = dist_obj.params['sigma']
#     gamma = dist_obj.params['gamma']
    
#     # Bootstrap resampling
#     for i in range(n_resamples):
#         # Resample from fitted distribution
#         if gamma > 0:
#             alpha = 4 / (gamma ** 2)
#             beta = sigma * np.abs(gamma) / 2
#             xi = mu - 2 * sigma / gamma
#             z = scipy_gamma.rvs(a=alpha, size=len(data))
#             log_sample = xi + beta * z
#         else:
#             # For symmetric case
#             log_sample = np.random.normal(mu, sigma, len(data))
        
#         # Fit distribution to bootstrap sample
#         try:
#             temp_dist = LogPearsonIII()
#             temp_params = temp_dist.fit(10 ** log_sample)
#             bootstrap_quantiles[i, :] = temp_dist.ppf(nep)
#         except:
#             pass
    
#     # Compute confidence bounds
#     alpha = (1 - ci) / 2
#     lower_percentile = alpha * 100
#     upper_percentile = (1 - alpha) * 100
    
#     ci_results = pd.DataFrame({
#         'ReturnPeriod': return_periods,
#         'NonExceedanceProbability': nep,
#         'Lower': np.percentile(bootstrap_quantiles, lower_percentile, axis=0),
#         'Estimate': dist_obj.ppf(nep),
#         'Upper': np.percentile(bootstrap_quantiles, upper_percentile, axis=0)
#     })
    
#     return ci_results


# def plot_frequency_curve(data, ci_df, title="Frequency Analysis - Flood Peak Flows"):
#     """
#     Plot frequency curve with confidence intervals.
    
#     Parameters:
#     -----------
#     data : array-like
#         Original flow data
#     ci_df : pandas.DataFrame
#         Confidence interval dataframe from bootstrap
#     title : str
#         Plot title
#     """
#     # Calculate plotting positions for data
#     n = len(data)
#     sorted_data = np.sort(data)
#     # Weibull plotting position
#     pp = (np.arange(1, n + 1)) / (n + 1)
    
#     # Convert plotting positions to return periods
#     rp_data = 1 / (1 - pp)
    
#     # Create figure
#     fig, ax = plt.subplots(figsize=(12, 7))
    
#     # Plot observed data (with return periods on x-axis)
#     ax.scatter(rp_data, sorted_data, s=50, alpha=0.6, label='Observed Data', color='black')
    
#     # Convert ci_df non-exceedance probabilities to return periods for plotting
#     rp_fitted = 1 / (1 - ci_df['nonexceed_prob'])
    
#     # Plot fitted curve
#     ax.plot(rp_fitted, ci_df['true'],
#            color='red', linewidth=2, label='Fitted LP3')
    
#     # Plot confidence bands
#     ax.fill_between(rp_fitted,
#                     ci_df['lower'],
#                     ci_df['upper'],
#                     alpha=0.3, color='red', label='90% Confidence Interval')
    
#     # Format x-axis with return periods on log scale
#     rp_ticks = [1.01, 1.05, 1.1, 1.25, 1.5, 2, 5, 10, 25, 50, 100, 250, 500, 1000]
    
#     ax.set_xscale('log', base = 2)
#     ax.set_xticks(rp_ticks)
#     ax.set_xticklabels([f'{int(rp)}' if rp >= 10 else f'{rp:.1f}' for rp in rp_ticks])
#     ax.set_xlim(left=1.001, right = 500)
    
#     ax.set_yscale('log')
    
#     ax.set_xlabel('Return Period (years)', fontsize=12)
#     ax.set_ylabel('Flow Magnitude (m³/s)', fontsize=12)
#     ax.set_title(title, fontsize=14, fontweight='bold')
#     ax.legend(loc='upper left')
#     ax.grid(True, which='both', alpha=0.3)
    
#     plt.tight_layout()
#     return fig

# ============================================================================
# SECTION 6: CALCULATE RETURN PERIODS FOR SPECIFIC HISTORICAL EVENTS
# ============================================================================

# def calculate_return_period(Q_obs, dist_obj):
#     """
#     Calculate the return period for an observed event.
    
#     Parameters:
#     -----------
#     Q_obs : float
#         Observed discharge value
#     dist_obj : LogPearsonIII
#         Fitted distribution object
    
#     Returns:
#     --------
#     dict
#         CDF, exceedance probability, and return period
#     """
#     # Get CDF value
#     cdf = dist_obj.cdf(Q_obs)
    
#     # Exceedance probability
#     aep = 1 - cdf
    
#     # Return period = 1 / AEP
#     if aep > 0 and aep < 1:
#         return_period = 1 / aep
#     else:
#         return_period = np.inf
    
#     return {
#         'Discharge': Q_obs,
#         'CDF': cdf,
#         'AEP': aep,
#         'ReturnPeriod': return_period
#     }


# def calculate_return_periods_batch(observed_events, dist_obj):
#     """
#     Calculate return periods for multiple observed events.
    
#     Parameters:
#     -----------
#     observed_events : list or array-like
#         List of observed discharge values
#     dist_obj : LogPearsonIII
#         Fitted distribution object
    
#     Returns:
#     --------
#     pandas.DataFrame
#         Return period results for all events
#     """
#     results = []
#     for Q_obs in observed_events:
#         results.append(calculate_return_period(Q_obs, dist_obj))
    
#     return pd.DataFrame(results)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    """
    Example workflow demonstrating the flood frequency analysis pipeline.
    Modify data paths and parameters as needed for your specific watershed.
    """
    
    print("=" * 80)
    print("FLOOD FREQUENCY ANALYSIS - Python Implementation")
    print("=" * 80)
    
    # SECTION 1: Load and clean data
    print("\n[SECTION 1] Loading and cleaning flow data...")
    # Example: Load Ochre River data
    # data_path = "../Data/freq/OCHRE_RIVER_AT_OCHRE_RIVER.csv"
    # ochre = load_flow_data(data_path, param_id=1, start_year=1949)
    # print(f"Loaded {len(ochre)} daily records")
    
    # SECTION 2: Summarize by water year
    print("[SECTION 2] Grouping and summarizing by water year...")
    # wy_summary = summarize_by_water_year(ochre, origin_month=10)
    # print(f"Generated water year summary with {len(wy_summary)} years")
    
    # SECTION 3: Generate plots
    print("[SECTION 3] Generating diagnostic plots...")
    # fig1 = plot_daily_statistics(ochre, start_year=1950)
    # fig1.savefig('../scratch/daily_stats.png', dpi=150)
    # fig2 = plot_annual_statistics(wy_summary)
    # fig2.savefig('../scratch/annual_stats.png', dpi=150)
    # fig3 = plot_daily_minmax_with_overlay(ochre)
    # fig3.savefig('../scratch/overlay_years.png', dpi=150)
    
    # SECTION 4: Remove low outliers
    print("[SECTION 4] Identifying and removing low outliers...")
    # annual_peaks = wy_summary[wy_summary['Type'] == 'Annual']['PeakFlow'].values
    # filtered_peaks = remove_low_outliers(annual_peaks, method='mgbt')
    # print(f"Removed {len(annual_peaks) - len(filtered_peaks)} low outliers")
    
    # SECTION 5: Frequency analysis
    print("[SECTION 5] Performing frequency analysis (Log-Pearson III)...")
    # fa = frequency_analysis(filtered_peaks, dist='lp3')
    # print("Fitted Log-Pearson III distribution:")
    # print(f"  mu = {fa['parameters']['mu']:.4f}")
    # print(f"  sigma = {fa['parameters']['sigma']:.4f}")
    # print(f"  gamma = {fa['parameters']['gamma']:.4f}")
    # print("\nReturn period estimates:")
    # print(fa['output'].to_string(index=False))
    
    # Compute confidence intervals
    # ci_results = bootstrap_confidence_interval(filtered_peaks, fa['distribution'], 
    #                                           n_resamples=2500, ci=0.90)
    # print("\nWith 90% Confidence Intervals:")
    # print(ci_results.to_string(index=False))
    
    # SECTION 6: Calculate return periods for specific events
    print("[SECTION 6] Calculating return periods for historical events...")
    # observed_events = [5.72, 24.2, 12.3, 52.3, 90.3]  # Example flow values
    # rp_results = calculate_return_periods_batch(observed_events, fa['distribution'])
    # print("\nReturn periods for observed events:")
    # print(rp_results.to_string(index=False))
    
    print("\n" + "=" * 80)
    print("Analysis complete. Uncomment lines above to run with your data.")
    print("=" * 80)
