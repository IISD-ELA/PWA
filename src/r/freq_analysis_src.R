
#!/C:/users/tsaleh/.conda/envs/pwa_dev/Scripts/Rscript

library(dplyr)
library(lubridate)
library(CSHShydRology)
library(hydroEvents)

data_dir = "Data/grassmere/freq/"
file_name = "wy_summary.csv"
temp_path = paste0(data_dir, file_name)

event_summary <- read.csv(temp_path)
event_summary <- event_summary %>%
  group_by(WaterYear, Type)%>%
  filter(PeakFlow == max(PeakFlow))

spring <- event_summary %>%
  filter(Type == "Spring")

annual <- event_summary %>%
  group_by(WaterYear)%>%
  filter(PeakFlow == max(PeakFlow))%>%
  filter(WaterYear <= 2023)

# Low Outlier Test ------------------------------------------------------------
## Multiple Grubbs-Beck test (MGBT) can be used to identify influential low floods
## influential low floods should be removed before running frequency analysis

library(MGBT)
mgbt <- MGBT(annual$PeakFlow)
mgbt_v <- MGBT(annual$TotalVolume)
mgbtp <- as.data.frame(mgbt$p)

annual_filtered <- annual %>% 
  filter(PeakFlow >= mgbt$LOThresh)

annual_lowthresh <- annual %>% 
  mutate(PeakFlow = ifelse(PeakFlow >= mgbt$LOThresh, PeakFlow, mgbt$LOThresh))

annual_w_null <- annual %>% 
  mutate(PeakFlow = ifelse(PeakFlow >= mgbt$LOThresh, PeakFlow, NA))


# Frequency Analysis  -----------------------------------------

##Original functions in this section from: https://headwateranalytics.weebly.com/blog/flood-frequency-analysis-in-r

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
#' 
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


library(scales)
labels=label_number(accuracy = 0.01)

annual_non_null <- annual_filtered %>% 
  filter(!is.na(PeakFlow))

annual_series <- annual_non_null

# Fit frequency distribution
fa <- FrequencyAnalysis(series=annual_series$PeakFlow, distribution=dist)

# Estimate confidence intervals
ci <- BootstrapCI(series=annual_series$PeakFlow,   # flow data
                  distribution=dist,   # distribution
                  n.resamples = 2.5E4, # number of re-samples to conduct
                  ci = 0.90)           # confidence interval level

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
observed_events <- sort(annual_series$PeakFlow, decreasing = T)[1:3] # Replace with your flood peaks, can be flow or volume
rp_results <- lapply(observed_events, return_period_lp3, fa = fa)

# Convert to dataframe for readability
rp_df <- do.call(rbind, lapply(rp_results, as.data.frame))
print(rp_df)

standard_rps <- c(2, 5, 10)
standard_cdfs <- 1-(1/standard_rps)
dist_quantiles <- function(cdfs){
    log_val = quape3(cdfs, fa$distribution$parameters)
    return(10^log_val)
}

standard_quantiles <- lapply(standard_cdfs, FUN = dist_quantiles) %>% 
  as.numeric()

standard_rp_df <- data_frame(Q = standard_quantiles, CDF = standard_cdfs, ReturnPeriod = standard_rps)

rp_df <- rp_df %>% 
  add_row(standard_rp_df) %>% 
  arrange(ReturnPeriod) %>% 
  mutate(nearest_event = NA)

for (i in 1:nrow(rp_df)){
  j = DescTools::Closest(annual$PeakFlow, rp_df$Q[i], which = T)
  rp_df$nearest_event[i] = annual$WaterYear[j]
}

View(rp_df)

# Goodness-of-Fit Tests ---------------------------------------------------

### Check goodness of fit for peak flow & vol ###
### Using Anderson Darling and Cramer Von Mises tests ###
library(moments)
library(lmomco)

# Data (log10 space)
peak_flow_data <- log10(annual$PeakFlow)
volume_data <- log10(annual$TotalVolume)

# Get parameters
dist <- "lp3"

# Peak Flow
fa <- FrequencyAnalysis(series = annual$PeakFlow, distribution = dist)
# Specify mu/sigma/gamma (or shape, scale, location) parameters from frequency analysis output
peak_mu <- fa$distribution$parameters$para[1]  # 1.424
peak_sigma <- fa$distribution$parameters$para[2]  # 0.359
peak_gamma <- fa$distribution$parameters$para[3]  # -0.176

# Volume
fa_vol <- FrequencyAnalysis(series = annual$TotalVolume, distribution = dist)
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

peak_flow_log <- log10(annual$PeakFlow)
volume_log <- log10(annual$TotalVolume)

# Run tests
peak_results <- perform_gof_tests(peak_flow_log, peak_mu, peak_sigma, peak_gamma, "Peak Flow")
vol_results <- perform_gof_tests(volume_log, vol_mu, vol_sigma, vol_gamma, "Volume")


library(jsonlite)

json_output <- list(freq_analysis = fa_output,
  confidence = ci_output,
  event_returns = rp_df,
  peak_flow_goodness_fit = peak_results,
  mgbt_removed = nrow(annual) - nrow(annual_filtered),
  mgbt_threshold = mgbt$LOThresh,
  annual_mgbt_filtered = annual_filtered
)

json_path <- paste0(data_dir,"results.json")

if (!file.exists(json_path)){
  file.create(json_path)
  write_json(json_output, json_path)
} else{
  usr_input <- readline(prompt = "json file found, enter 'over' to overwrite, or enter new file name (without the '.json' extension)") %>% 
    snakecase::to_snake_case()
  if((usr_input == "over") | (usr_input == "results")){
    file.remove(json_path)
    file.create(json_path)
    write_json(json_output, json_path)
  } else {
    new_path <- paste0("Data/freq/", usr_input)
    file.create(new_path)
    write_json(json_output, new_path)
  }
}


 