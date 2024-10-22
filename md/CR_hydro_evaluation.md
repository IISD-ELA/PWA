---
title: "Cypress River Hydrology Model Evaluation"
author: "Thomas Saleh"
date: "10/22/2024"
output: 
  html_document:
    keep_md: true
---



# Cypress River Hydrology Model Evaluation

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
