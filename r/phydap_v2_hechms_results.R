getwd()

data <- read.csv("Data/Raw/phydap_v2_flow.csv")

head(data)

install.packages('tidyverse')
install.packages('tibbletime')
install.packages('lubridate')
install.packages('reshape2')
install.packages('hydroGOF')
install.packages('glue')
install.packages('scales')
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

# filter data to spring 2003
spring_2003 <- filter_time(data, time_formula = '2003-03-01' ~ '2003-05-31')
View(spring_2003)

# calculate percent bias
pbias(sim = data$FLOW, obs = data$FLOW.OBSERVED)
pbias_2006 <- pbias(sim = spring_2006$FLOW, obs = spring_2006$FLOW.OBSERVED)
pbias_2003 <- pbias(sim = spring_2003$FLOW, obs = spring_2003$FLOW.OBSERVED)


# calculate NSE
NSE(sim = data$FLOW, obs = data$FLOW.OBSERVED)
NSE_2006 <- round(NSE(sim = spring_2006$FLOW, obs = spring_2006$FLOW.OBSERVED), digits = 4)
NSE_2003 <- round(NSE(sim = spring_2003$FLOW, obs = spring_2003$FLOW.OBSERVED), digits = 4)


# plot flow values for spring 2003 with performance metrics
spring_2003_lf <- melt(spring_2003, id.vars = "Date")
head(spring_2003_lf)

ggplot(spring_2003_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Date", y="Flow")+
  scale_x_datetime(name = "2003", date_breaks = waiver(), labels = date_format("%b-%d"))+
  annotate(geom = "text", x = as.POSIXct("2003-05-25"), y = 7.9, label = glue("% Bias = {pbias_2003}"))+
  annotate(geom = "text", x = as.POSIXct("2003-05-25"), y = 7.4, label = glue("NSE = {NSE_2003}"))


# plot flow values for spring 2006 with performance metrics
spring_2006_lf <- melt(spring_2006, id.vars = "Date")
head(spring_2006_lf)

ggplot(spring_2006_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Date", y="Flow")+
  scale_x_datetime(name = "2006", date_breaks = waiver(), labels = date_format("%b-%d"))+
  annotate(geom = "text", x = as.POSIXct("2006-05-25"), y = 55, label = glue("% Bias = {pbias_2006}"))+
  annotate(geom = "text", x = as.POSIXct("2006-05-25"), y = 50, label = glue("NSE = {NSE_2006}"))


