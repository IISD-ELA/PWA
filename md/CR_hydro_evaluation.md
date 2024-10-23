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

## Loading Data



``` r
data <- read_csv(here("Data/Raw/phydap_v2_flow_allWSC.csv"))

head(data)
```

```
## # A tibble: 6 × 3
##   Date              FLOW FLOW.OBSERVED
##   <chr>            <dbl>         <dbl>
## 1 1998-11-01 0:00      0             0
## 2 1998-11-01 3:00      0             0
## 3 1998-11-01 6:00      0             0
## 4 1998-11-01 9:00      0             0
## 5 1998-11-01 12:00     0             0
## 6 1998-11-01 15:00     0             0
```

``` r
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

## Cleaning Data


``` r
data$Date <- ymd_hm(data$Date)

data <- as_tbl_time(data, index = Date) %>% 
  filter(year(Date) >= 2003)
```

## Filtering Data

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

## Calculating Performance Metrics


``` r
model_summary <- function(phydap_data){
  results <- list(pct_bias = pbias(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED),
  nse = NSE(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED),
  rmse = rmse(sim = phydap_data$FLOW, obs = phydap_data$FLOW.OBSERVED),
  mean_val = mean(phydap_data$FLOW.OBSERVED))
  
  return(results)
  }

wet_smy <- model_summary(wet_yy_data)
dry_smy <- model_summary(dry_yy_data)

spring_smy <- model_summary(spring_data)
summer_smy <- model_summary(summer_data)
fall_smy <- model_summary(fall_data)
```
### Performance Metrics (% Bias, NSE, RMSE, Mean):

Wet Years: -19.3, 0.35036, 2.9974162, 0.8788341

Dry Years: 18.9, -1.2863867, 1.3937077, 0.2938949

Spring: -5.7, 0.2889986, 4.0273582, 1.6794824

Summer: -94, 0.0021544, 0.9067793, 0.249761

Fall: -99.7, -0.0385895, 0.1329109, 0.0259566
