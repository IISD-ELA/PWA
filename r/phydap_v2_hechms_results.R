getwd()

data <- read.csv("Data/Raw/phydap_v2_flow.csv")

head(data)

install.packages('tidyverse')
install.packages('tibbletime')
install.packages('lubridate')
library(tidyverse)
library(tibbletime)
library(lubridate)

# convert Date column into date-time class (POSIXct)
data$Date <- ymd_hm(data$Date)

str(data)

# convert dataframe to tbl_time object
data <- as_tbl_time(data, index = Date)
# filter data by date-time
test <- filter_time(data, time_formula = '2003-02-26' ~ '2003-02-28')
print(test, n = 25)

# group by year
agg_tbl_year <- data %>%
  group_by(year = lubridate::year(Date)) %>%
  summarize(FLOW = sum(FLOW), FLOW.OBSERVED = sum(FLOW.OBSERVED))

head(agg_tbl_year)

# convert tibble to dataframe
df_by_year <- agg_tbl_year %>% as.data.frame()
df_by_year
