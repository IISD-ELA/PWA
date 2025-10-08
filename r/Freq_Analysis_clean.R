## Author : Aliana Fristensky



# Clean Data & Plot Hydrograph --------------------------------------------------------------
library(dplyr)
#Turtle River
  turtle<-read.csv("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI\\TURTLE_RIVER_NEAR_LAURIER.csv",
                 header = TRUE, skip = 1)

  #Keep only flow data, remove water level
  turtle <- turtle[ which(turtle$PARAM == "1"), ]

  #Remove ID, PARAM and SYM cols
  turtle <- turtle[,-c(1,2,5)]

  #Format date column
  turtle$Date <- as.Date(turtle$Date, format = "%Y/%m/%d")
  
library(CSHShydRology)
#Plot hydrograph
  turtle_plot <- ch_hydrograph_plot(
  flows = turtle, 
  flow_labels = "Turtle River",
  prd = "2022-01-01/2022-12-31") #select time period

#Ochre River
ochre<-read.csv("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI\\OCHRE_RIVER_AT_OCHRE_RIVER.csv",
                 header = TRUE, skip = 1)

#Keep only flow data, remove water level
ochre <- ochre[ which(ochre$PARAM == "1"), ]

#Remove ID, PARAM and SYM cols
ochre <- ochre[,-c(1,2,5)]

#Format date column
ochre$Date <- as.Date(ochre$Date, format = "%Y/%m/%d")

#Plot hydrograph
ochre_plot <- ch_hydrograph_plot(
  flows = ochre,
  flow_labels = "Ochre River",
  prd = "1948-01-01/2023-12-31") #select time period

#Refine data period
turtle2 <- turtle %>%
  filter(year(Date) %in% c(1949:2023))

ochre2 <- ochre %>%
  filter(year(Date) %in% c(1949:2023))

#Add water year column
#library(lfstat)
#turtle2$WY <- water_year(turtle2$Date, origin = 10, assign = "end")
#ochre2$WY <- water_year(ochre2$Date, origin = 10, assign = "end")

# Max Flow and Volume -------------------------------------------------------------------

#Get max discharge by water year **Not always during the spring so verify with hydrograph**

# Remove rows with missing flow values - won't work if there are NAs

ochre2 <- ochre %>%
  filter(!is.na(Value))

library(hydroEvents)
# Use hydroEvents to separate flow events
# Detect flow events using eventMinima (or other seelection method)
# Set a threshold window (e.g., 5 days) for detecting event minima
events <- eventMinima(
  data = ochre2$Value,
  delta.y = 20,    # Example threshold for trough difference; adjust as needed
  delta.x = 5,     # Minimum event length in days
  threshold = 0,   # Event must return above this value
  out.style = "summary"
)
# Prepare the events table by creating an event ID column and mapping dates to indices
# Ensure events is a dataframe and select the necessary columns
events <- events %>%
  mutate(
    event_id = row_number(),
    event_start_index = as.numeric(srt),
    event_end_index = as.numeric(end)
  )

# Create a dataframe for events with start, end, and max dates
# Compute the global max index by directly finding the max flow within each event
event_info <- events %>%
  rowwise() %>%
  mutate(
    max_index = event_start_index - 1 + which.max(ochre2$Value[event_start_index:event_end_index]),
    event_start_date = ochre2$Date[event_start_index],
    event_end_date = ochre2$Date[event_end_index],
    peak_flow_date = ochre2$Date[max_index]
  ) %>%
  ungroup() %>%
  dplyr::select(event_id, event_start_date, event_end_date, peak_flow_date, max)

#Add a column for spring peak/annual peak
spring_months <- 3:6
event_info$Type <- ifelse(month(event_info$peak_flow_date) %in% spring_months, "Spring", "Annual")

#Add a column for Water Year
library(lfstat)
event_info$WY <- water_year(event_info$peak_flow_date, origin = 10, assign = "end")

event_info <- event_info %>%
  dplyr::select(event_id, event_start_date, event_end_date, peak_flow_date, max, Type, WY)

#Save event info for later
setwd("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI")
write.csv(event_info, "ochre_event_info.csv")

event_summary <- read.csv("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI\\ochre_event_info.csv")[,-1]
event_summary <- event_summary %>%
  group_by(WY, Type)%>%
  filter(max == max(max))

#Remover unnecessary cols and add a column for duration of each event
event_summary[,c(2,3,4)] <- lapply(event_summary[,c(2,3,4)], as.Date)
event_summary$Duration <- event_summary$event_end_date - event_summary$event_start_date

#Fix incorrect start/end dates
  # Not sure why but some dates end up wrong, need to manually check/fix each one 
  # Seems to be an issue when the peak of an event is at the end of the measurement period in a given year
  # Look for events with unreasonably long duration
event_summary[93,3] = as.Date("1994-10-31")

#Calculate volume for each peak flow event

# Create a new column to store the sum of streamflow values
event_summary$sum_streamflow <- 0

# Iterate through each row of dataframe 
for (i in 1:nrow(event_summary)) {
  # Extract start and end dates for the current time interval
  start_date <- event_summary$event_start_date[i]
  end_date <- event_summary$event_end_date[i]
  #duration <- event_summary$Duration[i]
  
  # Subset flow data to select rows within the current time interval
  subset_A <- ochre2_clean[ochre2_clean$Date >= start_date & ochre2_clean$Date <= end_date, ]
  
  # Calculate the sum of streamflow values within the current time interval
  sum_streamflow <- sum(subset_A$Value*86400)
  
  # Store the sum in the corresponding row of dataframe
  event_summary$sum_streamflow[i] <- sum_streamflow
}

#Save event summary for later
setwd("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI")
write.csv(event_summary, "ochre_QV_full.csv")


event_summary <- read.csv("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI\\turtle_QV_full.csv")[,-1]

spring <- event_summary %>%
  filter(Type == "Spring")

annual <- event_summary %>%
  group_by(WY)%>%
  filter(max == max(max))%>%
  filter(WY <= 2023)

##Plot histograms

library(fitdistrplus)
  plotdist(annual$max, histo = TRUE, demp = TRUE)
  plotdist(spring$max, histo = TRUE, demp = TRUE)

# Plot daily and annual stats ---------------------------------------------
#

plot_daily_stats(data = turtle2, values = Value,
                 start_year = 1949,
                 add_year = 1949,
                 log_discharge = FALSE, 
                 ignore_missing = TRUE)

plot_annual_stats(data = ochre2_clean, values = Value,
                 start_year = 1993, ignore_missing = TRUE)

# Calculate daily statistics for all years
daily_stats <- ochre2 %>%
  calc_daily_stats(dates = Date, values = Value, ignore_missing = TRUE)

daily_stats86 <- ochre2 %>%
  filter(year(Date) == 1986) %>%
  calc_daily_stats(dates = Date, values = Value, ignore_missing = TRUE)

write.csv(daily_stats86, "ochre1986.csv")


# Filter data for individual years to overlay
years_to_overlay <- c(1975,1986,2011,2022)
overlay_data <- ochre2 %>%
  filter(format(Date, "%Y") %in% years_to_overlay) %>%
  mutate(Year = format(Date, "%Y"),
         DOY = as.numeric(format(Date, "%j")))

# Prepare base plot with daily statistics

p <- ggplot() +
  # Min-max ribbon with legend
  geom_ribbon(data = daily_stats, aes(x = DayofYear, ymin = Minimum, ymax = Maximum, fill = "Min-Max Range"), alpha = 0.4) +
  # Median line with legend
  geom_line(data = daily_stats, aes(x = DayofYear, y = Median, color = "Median"), size = 0.65) +
  # Overlay individual years
  geom_line(data = overlay_data, aes(x = DOY, y = Value, color = Year), size = 0.65) +
  
  # Manual legend definitions
  scale_fill_manual(name = "", values = c("Min-Max Range" = "lightblue")) +
  scale_color_manual(name = "", values = c("Median" = "black",
                                           "1975" = "green", "1986" = "blue", "2011" = "orange", "2022" = "purple")) +
  
  # Format x-axis with month abbreviations
  scale_x_continuous(breaks = cumsum(c(0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30)) + 15,
                     labels = month.abb,
                     expand = c(0, 0)) +
  
  labs(title = "",
       x = "", y = "Flow (cms)") +
  theme_minimal()

print(p)

# Frequency Analysis  -----------------------------------------

##Original functions in this section from: https://headwateranalytics.weebly.com/blog/flood-frequency-analysis-in-r

# Extract instantaneous maxima flow series
event_summary <- read.csv("C:\\Users\\afristensky\\OneDrive - IISD\\Documents\\O_T_River_NI\\turtle_QV_full.csv")[,-1]

# Prep input data
library(fitdistrplus)

spring <- event_summary %>%
  filter(Type == "Spring")

annual <- event_summary %>%
  group_by(WY)%>%
  filter(max == max(max))%>%
  filter(WY <= 2023)

input_data <- annual$max #input can be peak flow or volume

# choose a distribution - lp3 is most commonly used in flood frequency analysis
# (see ?dist.list for available distributions)
# log Pearson 3 is not one of them but is a log-transformed equivalent of pe3
# note: this script recognizes 'lp3' to stand for log Pearson Type 3

dist <- "lp3" 

### Functions ###
#' FrequencyAnalysis Fits a given extreme value distribution to an extreme value series
#' @param series A vector representing an extreme value series (e.g., annual maximum flood)
#' @param distribution A three-character name of the extreme value distribution (see ?dist.list())
#' @param nep A vector of non-exceedance probabilities
#' @return A list object containing: (1) distribution information and (2) output
#'  (quantile estimates at various non-exceedance probabilities)
#' @export
#' @import lmomco
FrequencyAnalysis <- function( series, distribution, nep = nonexceeds() ) {
  
  library(lmomco)
  
  distribution <- tolower(distribution)
  transformed <- FALSE
  
  # add log Pearson Type 3 to list of distributions supported
  # by lmomco package
  base.dist <- c('lp3', dist.list())
  
  if( any(distribution %in% base.dist) ) {
    
    # log transform series 
    if( distribution == 'lp3' ) {
      series <- log10(series)
      transformed <- TRUE
      distribution <- 'pe3'
    }
    
    # compute L-moments
    samLmom <- lmom.ub(series)
    
    # estimate distribution parameters
    distPar <- lmom2par(samLmom, type = distribution)
    
    # compute quantiles for nonexceedances
    quant <- par2qua(f = nep, para = distPar)
    
    if( distribution == 'pe3' & transformed ) {
      distribution <- 'lp3'
      quant <- 10^quant
    }
    
    # return result as list object
    return(
      list(
        distribution = list(
          name = distribution,
          logTransformed = transformed,
          parameters = distPar),
        output = data.frame(nep = nep, rp = prob2T(nep), estimate = quant) 
      ) )
    
  } else {
    stop(
      sprintf('Distribution \'%s\' not recognized!', distribution))
  }
}

#' BootstrapCI Conducts bootstrap to randomly sample an extreme value series 'n' times for a 
#'  specified distribution to estimate confidence interval for each given 
#'  non-exceedance probability.
#' @param fitted.model Fitted distribution (see ?frequencyAnalysis)
#' @param series A vector representing an extreme value series (e.g., annual maximum flood)
#' @param distribution A three-character name of the extreme value distribution (see ?dist.list())
#' @param n.resamples An integer representing number of re-samples to conduct
#' @param nep A vector of non-exceedance probabilities
#' @param ci The confidence interval 
#' @export
#' @import lmomco
#' @return A list containing a data frame of confidence bounds for quantile estimates for each 
#' non-exceedance probability, a matrix containing estimated distribution parameters for each resample,
#' and a matrix of quantile estimates for each resample
BootstrapCI <- function(series, distribution, n.resamples=1E3, nep=nonexceeds(), ci=0.90) {
  
  # compute frequency analysis
  fa <- FrequencyAnalysis(series=series, distribution=distribution, nep=nep)
  
  # extract fitted model parameters and flag as to whether the 
  # distribution is based on log transformed data
  base.params <- fa$distribution$parameters
  isTransformed <- fa$distribution$logTransformed
  
  # create output matrices to store parameter sets and quantile estimates
  param.sets <- matrix(NA, nrow = n.resamples, ncol = length(base.params$para))
  quantile.estimates <- matrix(NA, nrow = n.resamples, ncol = length(nep), 
                               dimnames = list(NULL, nep) ) 
  
  # begin bootstrapping procedure
  for(i in 1:n.resamples) {
    
    valid.moments <- FALSE
    j <- 0
    
    # allow up to 20 re-tries to re-sample 
    while(!valid.moments & j < 20) {  
      
      # sample 'n' random variates from base distribution
      data <- rlmomco(n=length(series), base.params)
      
      # compute sample l-moments
      sample.moms = lmom.ub(data)
      
      valid.moments <- are.lmom.valid(sample.moms)
      j <- j + 1
    }
    
    # error handling
    if(!valid.moments) {
      stop("Bootstrapping failed to sample valid l-moments")
    } else {
      # estimate distribution parameters
      dist.par <- lmom2par(sample.moms, base.params$type)
      
      # store the distribution parameters
      param.sets[i,] <- dist.par$para
      
      # estimate quantiles at NEP
      estimated <- qlmomco(nep, dist.par)
      
      # convert quantile estimates to real values if
      # distribution was transformed
      if(isTransformed) estimated <- 10^estimated
      
      # store the quantiles at the desired AEP values
      quantile.estimates[i,] <- estimated
    } 
    
  }
  
  # now calculate confidence limits for quantiles
  p <- c((1-ci)/2, (1+ci)/2)
  ci <- sapply(colnames(quantile.estimates), 
               FUN=function(x){
                 quantile(quantile.estimates[,x], probs=p, na.rm=TRUE)})
  
  # now return list object containing output
  return(
    list(
      ci = data.frame(
        nonexceed_prob = nep,
        lower = as.vector(ci[1,]),
        true = fa$output$estimate,
        upper = as.vector(ci[2,]) ),
      parameters = param.sets,
      quantiles = quantile.estimates)
  )
  
}

#' FrequencyPlot Generates a nice-looking (hydrologist-centric) frequency plot
#' @param series A vector representing an extreme value series (e.g., annual maximum flood)
#' @param ci A data frame containing confidence intervals (lower, true, upper) derived from 
#'  calling BootstrapCI()
#' @export ggplot
#' @import ggplot2
#' @import scales
#' 
frequencyPlot <- function(series, ci) {
  
  library(ggplot2)
  library(scales)
  
  # determine plotting positions
  bwpeaks <- data.frame(PROB = pp(series, sort = FALSE), FLOW = series)
  xbreaks <- c(0.002,0.01,0.1,0.25,0.5,0.8,0.9,0.95,0.975,0.99,0.995, 0.998)
  log.range <- log10(range(series, ci[,-1], na.rm = TRUE))
  lower <- 10^floor(log.range[1])
  upper <- 10^ceiling(log.range[2])
  cap <- lower
  ybreaks <- NULL
  while(cap < upper) {
    ybreaks <- c(ybreaks, seq(cap, cap*9, by = cap))
    cap <- cap * 10
  }
  
  # now plot
  ggplot(bwpeaks) + 
    geom_point(aes(x=PROB, y=FLOW)) + 
    theme_bw() + 
    scale_y_continuous(trans="log10", breaks=ybreaks, name="Flow (m3/s)") +
    scale_x_continuous(trans=probability_trans(distribution="norm"),
                       breaks=xbreaks, labels=signif(prob2T(xbreaks), digits=4),
                       name="Return period [yrs]") +
    geom_line(data=ci, aes(x=nonexceed_prob, y=true), color="red") +
    geom_line(data=ci, aes(x=nonexceed_prob, y=lower), color="red", lty=2) +
    geom_line(data=ci, aes(x=nonexceed_prob, y=upper), color="red", lty=2)
}
labels=label_number(accuracy = 0.01)

# Fit frequency distribution
fa <- FrequencyAnalysis(series=input_data, distribution=dist)

# Estimate confidence intervals
ci <- BootstrapCI(series=input_data,   # flow data
                  distribution=dist,   # distribution
                  n.resamples = 2.5E4, # number of re-samples to conduct
                  ci = 0.90)           # confidence interval level

# Create frequency plot
frequencyPlot(series=input_data, ci$ci)

# Save output as data frame
fa_output <- as.data.frame(fa[["output"]])
ci_output <- as.data.frame(ci[["ci"]])


# Calculate return period for an observed flood ---------------------------

library(lmomco)

# Function to compute return period of an observed event
return_period_lp3 <- function(Q_obs, fa) {
  
  # Extract fitted parameters
  distPar <- fa$distribution$parameters
  transformed <- fa$distribution$logTransformed
  
  # If distribution was log-transformed (LP3 case)
  if (transformed) {
    Q_trans <- log10(Q_obs)
  } else {
    Q_trans <- Q_obs
  }
  
  # Compute nonexceedance probability (CDF)
  FQ <- cdfpe3(Q_trans, distPar)   # lmomco function for Pearson III
  
  # Return period = 1 / exceedance probability
  TQ <- 1 / (1 - FQ)
  
  return(list(Q = Q_obs, CDF = FQ, ReturnPeriod = TQ))
}

# -------------------------------
# Calculate for specific observed floods
# -------------------------------
observed_events <- c(5.72, 24.2, 12.3, 52.3, 90.3)  # Replace with your flood peaks, can be flow or volume
rp_results <- lapply(observed_events, return_period_lp3, fa = fa)

# Convert to dataframe for readability
rp_df <- do.call(rbind, lapply(rp_results, as.data.frame))
print(rp_df)

# Goodness-of-Fit Tests ---------------------------------------------------

### Check goodness of fit for peak flow & vol ###
### Using Anderson Darling and Cramer Von Mises tests ###
library(moments)
library(lmomco)

# Data (log10 space)
peak_flow_data <- log10(annual$max)
volume_data <- log10(annual$sum_streamflow)

# Get parameters
dist <- "lp3"

# Peak Flow
fa_peak <- FrequencyAnalysis(series = annual$max, distribution = dist)
# Specify mu/sigma/gamma (or shape, scale, location) parameters from frequency analysis output
peak_mu <- fa_peak$distribution$parameters$para[1]  # 1.424
peak_sigma <- fa_peak$distribution$parameters$para[2]  # 0.359
peak_gamma <- fa_peak$distribution$parameters$para[3]  # -0.176

# Volume
fa_vol <- FrequencyAnalysis(series = annual$sum_streamflow, distribution = dist)
vol_mu <- fa_vol$distribution$parameters$para[1]  # ~7.031
vol_sigma <- fa_vol$distribution$parameters$para[2]  # ~0.317
vol_gamma <- fa_vol$distribution$parameters$para[3]  # -0.233

# LP3 CDF
lp3_cdf <- function(y, mu, sigma, gamma) {
  if (sigma <= 0 || gamma == 0) return(rep(NA, length(y)))
  alpha <- 4 / (gamma^2)
  beta <- sigma * abs(gamma) / 2
  xi <- mu - 2 * sigma / gamma
  z <- (y - xi) / beta
  if (gamma > 0) cdf <- pgamma(z, shape = alpha) else cdf <- 1 - pgamma(-z, shape = alpha)
  cdf[is.nan(cdf) | is.infinite(cdf)] <- NA
  cdf <- pmax(0.001, pmin(0.999, cdf))
  return(cdf)
}

# LP3 Quantiles
lp3_quantile <- function(p, mu, sigma, gamma) {
  if (any(p <= 0 | p >= 1)) return(NA)
  alpha <- 4 / (gamma^2)
  beta <- sigma * abs(gamma) / 2
  xi <- mu - 2 * sigma / gamma
  if (gamma > 0) {
    q <- xi + beta * qgamma(p, shape = alpha)
  } else {
    q <- xi - beta * qgamma(p, shape = alpha, lower.tail = FALSE)
  }
  return(q)
}

# Goodness-of-fit test - function runs both AD and CVM tests
perform_gof_tests <- function(data, mu, sigma, gamma, dataset_name) {
  if (!is.numeric(data) || any(is.na(data))) stop("Data must be numeric, no NAs.")
  if (!is.numeric(c(mu, sigma, gamma)) || sigma <= 0 || gamma == 0) stop("Invalid parameters.")
  
  cat("Parameters for", dataset_name, ":\n")
  cat("mu =", mu, ", sigma =", sigma, ", gamma =", gamma, "\n")
  
  tryCatch({
    n <- length(data)
    data_sorted <- sort(data)
    emp_cdf <- (1:n) / (n + 1)
    theo_cdf <- lp3_cdf(data_sorted, mu, sigma, gamma)
    
    valid <- !is.na(theo_cdf) & !is.infinite(theo_cdf)
    data_sorted <- data_sorted[valid]
    emp_cdf <- emp_cdf[valid]
    theo_cdf <- theo_cdf[valid]
    n_valid <- length(data_sorted)
    
    if (n_valid < n) cat("Warning: Invalid CDF values removed.\n")
    if (n_valid < 2) stop("Too few valid points.")
    
    ad_stat <- -n_valid - sum((2 * (1:n_valid) - 1) * (log(theo_cdf) + log(1 - theo_cdf[seq(n_valid, 1, -1)]))) / n_valid
    cvm_stat <- sum((emp_cdf - theo_cdf)^2) + 1 / (12 * n_valid)
    
    n_sim <- 1000
    ad_sim <- numeric(n_sim)
    cvm_sim <- numeric(n_sim)
    
    for (i in 1:n_sim) {
      sim_data <- rnorm(n, mean = mu, sd = sigma)
      sim_sorted <- sort(sim_data)
      sim_theo_cdf <- lp3_cdf(sim_sorted, mu, sigma, gamma)
      sim_valid <- !is.na(sim_theo_cdf) & !is.infinite(sim_theo_cdf)
      sim_sorted <- sim_sorted[sim_valid]
      sim_theo_cdf <- sim_theo_cdf[sim_valid]
      sim_n <- length(sim_sorted)
      sim_emp_cdf <- (1:sim_n) / (sim_n + 1)
      ad_sim[i] <- -sim_n - sum((2 * (1:sim_n) - 1) * (log(sim_theo_cdf) + log(1 - sim_theo_cdf[seq(sim_n, 1, -1)]))) / sim_n
      cvm_sim[i] <- sum((sim_emp_cdf - sim_theo_cdf)^2) + 1 / (12 * sim_n)
    }
    
    ad_pval <- mean(ad_sim >= ad_stat, na.rm = TRUE)
    cvm_pval <- mean(cvm_sim >= cvm_stat, na.rm = TRUE)
    
    probs <- seq(0.01, 0.99, length.out = n_valid)
    emp_quantiles <- quantile(data_sorted, probs, na.rm = TRUE)
    theo_quantiles <- sapply(probs, lp3_quantile, mu = mu, sigma = sigma, gamma = gamma)
    data_range <- range(data_sorted, na.rm = TRUE)
    plot(emp_quantiles, theo_quantiles, main = paste("Q-Q Plot for", dataset_name),
         xlab = "Empirical Quantiles (log10)", ylab = "Theoretical Quantiles (log10)", pch = 19,
         xlim = data_range, ylim = data_range)
    abline(0, 1, col = "red", lwd = 2)
    
    cat("\nGoodness-of-Fit Tests for", dataset_name, "\n")
    cat("----------------------------------------\n")
    cat("Anderson-Darling Test:\n")
    cat("Statistic =", ad_stat, ", p-value =", ad_pval, "\n")
    cat("Cramer-von Mises Test:\n")
    cat("Statistic =", cvm_stat, ", p-value =", cvm_pval, "\n\n")
    cat("Note: p-values are approximate due to simplified simulation.\n")
    
    return(list(ad_stat = ad_stat, ad_pval = ad_pval, cvm_stat = cvm_stat, cvm_pval = cvm_pval))
  }, error = function(e) {
    cat("Error:", e$message, "\n")
    return(list(ad_stat = NA, ad_pval = NA, cvm_stat = NA, cvm_pval = NA))
  })
}

# Run tests
peak_results <- perform_gof_tests(peak_flow_data, peak_mu, peak_sigma, peak_gamma, "Peak Flow")
vol_results <- perform_gof_tests(volume_data, vol_mu, vol_sigma, vol_gamma, "Volume")
