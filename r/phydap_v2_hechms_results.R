getwd()

data <- read.csv("Data/Raw/phydap_v2_flow.csv")

head(data)

install.packages('tidyverse')
install.packages('tibbletime')
install.packages('lubridate')
install.packages('reshape2')
install.packages('hydroGOF')
library(tidyverse)
library(tibbletime)
library(lubridate)
library(ggplot2)
library(reshape2)
library(hydroGOF)

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

# plot flow values by year
df_by_year_lf <- melt(df_by_year, id.vars = "year")
head(df_by_year_lf)

ggplot(df_by_year_lf, aes(x=year, y=value, col = variable))+
  geom_line()+
  geom_point()+
  scale_x_continuous(name = "Year", breaks = waiver(), n.breaks = 13)+
  labs(x="Year", y="Flow")

# filter data to spring 2006
spring_2006 <- filter_time(data, time_formula = '2006-03-01' ~ '2006-05-31')
View(spring_2006)

# calculate percent bias
pbias(sim = data$FLOW, obs = data$FLOW.OBSERVED)
pbias(sim = spring_2006$FLOW, obs = spring_2006$FLOW.OBSERVED)

# calculate NSE
NSE(sim = data$FLOW, obs = data$FLOW.OBSERVED)
NSE(sim = spring_2006$FLOW, obs = spring_2006$FLOW.OBSERVED)
