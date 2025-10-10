---
title: "Cypress River Hydrology Model Evaluation"
author: "Thomas Saleh"
date: "10/22/2024"
output: 
  html_document:
    keep_md: true
---



## Pilot Description

We decided to pilot ___ on the Cypress River because xy


## Assessing PHyDAP Performance

### Loading Data


``` r
data <- read_csv(here("Data/Raw/phydap_v2_flow_allWSC.csv"))

glimpse(data)
```

```
## Rows: 52,601
## Columns: 3
## $ Date          <chr> "1998-11-01 0:00", "1998-11-01 3:00", "1998-11-01 6:00",…
## $ FLOW          <dbl> 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,…
## $ FLOW.OBSERVED <dbl> 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,…
```

The mean observed flow is 0.5132862

### Cleaning Data


``` r
data$Date <- ymd_hm(data$Date)

data <- as_tbl_time(data, index = Date) %>% 
  filter(year(Date) >= 2003)
```

### Filtering Data

``` r
agg_tbl_year <- data %>%
  group_by(year = lubridate::year(Date)) %>%
  summarize(FLOW = sum(FLOW), FLOW.OBSERVED = sum(FLOW.OBSERVED))

df_by_year <- agg_tbl_year %>% as.data.frame()

top_half_obs <- df_by_year %>%
  top_n(7, FLOW.OBSERVED)

btm_half_obs <- df_by_year %>%
  top_n(-8, FLOW.OBSERVED)

top_yy <- unique(top_half_obs$year)
btm_yy <- unique(btm_half_obs$year)

wet_yy_data <- data %>% 
  filter(year(Date) %in% top_yy)

dry_yy_data <- data %>% 
  filter(year(Date) %in% btm_yy)
```


``` r
spring_data <- data %>% 
  filter(month(Date) > 3 & month(Date) < 7)

summer_data <- data %>% 
  filter(month(Date) > 6 & month(Date) < 10)

fall_data <- data %>% 
  filter(month(Date) > 9)
```

### Calculating Performance Metrics


``` r
model_summary <- function(phydap_data){
  results <- list(pct_bias = pbias(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED),
  nse = round(NSE(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED), digits = 4),
  rmse = round(rmse(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED), digits = 4),
  mean_val = round(mean(phydap_data$FLOW.OBSERVED)), digits = 4)
  
  return(results)
  }

spring_smy <- model_summary(spring_data)
summer_smy <- model_summary(summer_data)
fall_smy <- model_summary(fall_data)
wet_yy_smy <- model_summary(wet_yy_data)
dry_yy_smy <- model_summary(dry_yy_data)
alldata_smy <- model_summary(data)
```

### Displaying Performance Metrics

``` r
results <- matrix(c(alldata_smy$pct_bias,alldata_smy$nse,alldata_smy$rmse,
                    alldata_smy$mean_val,wet_yy_smy$pct_bias,wet_yy_smy$nse,
                    wet_yy_smy$rmse,wet_yy_smy$mean_val,dry_yy_smy$pct_bias,
                    dry_yy_smy$nse,dry_yy_smy$rmse,dry_yy_smy$mean_val,
                    spring_smy$pct_bias,spring_smy$nse,spring_smy$rmse,
                    spring_smy$mean_val,summer_smy$pct_bias,summer_smy$nse,
                    summer_smy$rmse,summer_smy$mean_val,fall_smy$pct_bias,
                    fall_smy$nse,fall_smy$rmse,fall_smy$mean_val), ncol=4, 
                  byrow=TRUE)

colnames(results) <- c('% Bias', 'NSE', 'RMSE', 'Mean')
rownames(results) <- c('All Data', 'Wet Years', 'Dry Years', 'Spring', 'Summer', 'Fall')

results_table <- as.table(results)
results_table
```

```
##             % Bias      NSE     RMSE     Mean
## All Data  -10.0000   0.2819   2.3055   1.0000
## Wet Years -19.3000   0.3504   2.9974   1.0000
## Dry Years  18.9000  -1.2864   1.3937   0.0000
## Spring     -5.7000   0.2890   4.0274   2.0000
## Summer    -94.0000   0.0022   0.9068   0.0000
## Fall      -99.7000  -0.0386   0.1329   0.0000
```

