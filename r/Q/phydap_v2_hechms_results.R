getwd()

data <- read.csv("Data/Raw/phydap_v2_flow_allWSC.csv")

head(data)

# install.packages('tidyverse')
# install.packages('tibbletime')
# install.packages('lubridate')
# install.packages('reshape2')
# install.packages('hydroGOF')
# install.packages('glue')
# install.packages('scales')
library(tidyverse)
library(tibbletime)
library(lubridate)
library(ggplot2)
library(reshape2)
library(hydroGOF)
library(glue)
library(scales)

# convert Date column into date-time class (POSIXct)
data$Date <- ymd_hm(data$Date)

str(data)

# convert dataframe to tbl_time object
data <- as_tbl_time(data, index = Date) %>% 
  filter(year(Date) >= 2003)

# filter data by date-time
#test <- filter_time(data, time_formula = '2003-02-26' ~ '2003-02-28')
#print(test, n = 25)

# calculate performance metrics

pbias_alldata <- pbias(sim = data$FLOW, obs = data$FLOW.OBSERVED)
NSE_alldata <- round(NSE(sim = data$FLOW, obs = data$FLOW.OBSERVED), digits = 4)
rmse_alldata <- round(rmse(sim = data$FLOW, obs = data$FLOW.OBSERVED), digits = 4)

# plot flow values

data_lf <- melt(data, id.vars = "Date")
head(data_lf)

ggplot(data_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Date", y="Flow")+
  scale_x_datetime(name = "Date", date_breaks = "1 year", labels = date_format("%Y"))+
  annotate(geom = "text", x = as.POSIXct("2015-05-01"), y = 55, label = glue("% Bias = {pbias_alldata}"))+
  annotate(geom = "text", x = as.POSIXct("2015-05-01"), y = 50, label = glue("NSE = {NSE_alldata}"))+
  annotate(geom = "text", x = as.POSIXct("2015-05-01"), y = 45, label = glue("RMSE = {RMSE_alldata}"))

# group by year
agg_tbl_year <- data %>%
  group_by(year = lubridate::year(Date)) %>%
  summarize(FLOW = sum(FLOW), FLOW.OBSERVED = sum(FLOW.OBSERVED))

head(agg_tbl_year)

# convert tibble to dataframe
df_by_year <- agg_tbl_year %>% as.data.frame()
df_by_year

# plot flow values by year
df_by_year_lf <- melt(df_by_year, id.vars = "year")
head(df_by_year_lf)

ggplot(df_by_year_lf, aes(x=year, y=value, col = variable))+
  geom_line()+
  geom_point()+
  scale_x_continuous(name = "Year", breaks = waiver(), n.breaks = 19)+
  labs(x="Year", y="Flow")

# split into highest 50% and lowest 50%
top_half_obs <- df_by_year %>%
  top_n(7, FLOW.OBSERVED)

bottom_half_obs <- df_by_year %>%
  top_n(-8, FLOW.OBSERVED)

### TS Proposed Corrections ----
top_yy <- unique(top_half_obs$year)
btm_yy <- unique(bottom_half_obs$year)

wet_yy_data <- data %>% 
  filter(year(Date) %in% top_yy)

dry_yy_data <- data %>% 
  filter(year(Date) %in% btm_yy) 

### 
# note: we're interested in calculating %bias and NSE in the _original_ data from those years, 
# not in the summary values you calculated to sort the years out 
# (insufficient data there, and not comparable to the original performance metrics we calculated.
# Note also: I'm working with the data from 2003 onward (slight adjustment to your code which can be commented out) 
###

pbias_wet_yy <- pbias(sim = wet_yy_data$FLOW, obs = wet_yy_data$FLOW.OBSERVED)
pbias_dry_yy <- pbias(sim = dry_yy_data$FLOW, obs = dry_yy_data$FLOW.OBSERVED)

###
# The % bias didn't actually differ from the one you calculated. This is likely because there is
# a roughly equal amount of observations for each year, so averaging across all observations is the same
# as averaging across all years. 
###

NSE_wet_yy <-  round(NSE(sim = wet_yy_data$FLOW, obs = wet_yy_data$FLOW.OBSERVED), digits = 4)
NSE_dry_yy <- round(NSE(sim = dry_yy_data$FLOW, obs = dry_yy_data$FLOW.OBSERVED), digits = 4)

###
# The new results here are interesting. We get a NSE of 0.350 for wet years (which is actually not too bad)
# On the other hand, NSE for dry years is even worse than what you calculated: -1.29 (Not great...)
# So we might want to avoid relying on PHyDAP for drought scenarios for example.
###

rmse_wet_yy <- round(rmse(sim = wet_yy_data$FLOW, obs = wet_yy_data$FLOW.OBSERVED), digits = 4)
rmse_dry_yy <- round(rmse(sim = dry_yy_data$FLOW, obs = dry_yy_data$FLOW.OBSERVED), digits = 4)
mean_wet_yy <- mean(wet_yy_data$FLOW.OBSERVED)
mean_dr_yy <- mean(dry_yy_data$FLOW.OBSERVED)

### 
# The RMSE in dry years is actually lower than wet years, so the absolute error from the model is actually lower.
# In either case, the error on any one observation is at least 3X more than the mean observed value, 
# so we know PHyDAP is way off on individual observations
###


###
# Let's do something similar with the seasons, but instead of "spring_2006" for example, use the filter function as shown below.
###
spring_data <- data %>% 
  filter(month(Date) > 3 & month(Date) < 7)

summer_data <- data %>% 
  filter(month(Date) > 6 & month(Date) < 10)

fall_data <- data %>% 
  filter(month(Date) > 9)

pbias_spring <- pbias(sim = spring_data$FLOW, obs = spring_data$FLOW.OBSERVED)
pbias_summer <- pbias(sim = summer_data$FLOW, obs = summer_data$FLOW.OBSERVED)
pbias_fall <- pbias(sim = fall_data$FLOW, obs = fall_data$FLOW.OBSERVED)

NSE_spring <-  round(NSE(sim = spring_data$FLOW, obs = spring_data$FLOW.OBSERVED), digits = 4)
NSE_summer <- round(NSE(sim = summer_data$FLOW, obs = summer_data$FLOW.OBSERVED), digits = 4)
NSE_fall <- round(NSE(sim = fall_data$FLOW, obs = fall_data$FLOW.OBSERVED), digits = 4)

rmse_spring <- round(rmse(sim = spring_data$FLOW, obs = spring_data$FLOW.OBSERVED), digits = 4)
rmse_summer <- round(rmse(sim = summer_data$FLOW, obs = summer_data$FLOW.OBSERVED), digits = 4)
rmse_fall <- round(rmse(sim = fall_data$FLOW, obs = fall_data$FLOW.OBSERVED), digits = 4)

mean_spring <- round(mean(spring_data$FLOW.OBSERVED), digits = 4)
mean_summer <- round(mean(summer_data$FLOW.OBSERVED), digits = 4)
mean_fall <- round(mean(fall_data$FLOW.OBSERVED), digits = 4)

# We can also create a function to more quickly & succinctly reapply the same calculations to different datasets
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

# The results confirm that model performance is better in the spring (NSE = 0.289) than in the summer or fall

# displaying results as table
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
