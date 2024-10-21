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
pbias_alldata <- pbias(sim = data$FLOW, obs = data$FLOW.OBSERVED)
pbias_2006 <- pbias(sim = spring_2006$FLOW, obs = spring_2006$FLOW.OBSERVED)
pbias_2003 <- pbias(sim = spring_2003$FLOW, obs = spring_2003$FLOW.OBSERVED)


# calculate NSE
NSE_alldata <- round(NSE(sim = data$FLOW, obs = data$FLOW.OBSERVED), digits = 4)
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


# plot flow values for all data with performance metrics
data_lf <- melt(data, id.vars = "Date")
head(data_lf)

ggplot(data_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Date", y="Flow")+
  scale_x_datetime(name = "Date", date_breaks = "1 year", labels = date_format("%Y"))+
  annotate(geom = "text", x = as.POSIXct("2015-05-01"), y = 55, label = glue("% Bias = {pbias_alldata}"))+
  annotate(geom = "text", x = as.POSIXct("2015-05-01"), y = 50, label = glue("NSE = {NSE_alldata}"))


# filter seasonal data
spring_all <- data[months(data$Date) %in% month.name[3:5],]
View(spring_all)

summer_all <- data[months(data$Date) %in% month.name[6:8],]
View(summer_all)

fall_all <- data[months(data$Date) %in% month.name[9:11],]
View(fall_all)

winter_all <- data[months(data$Date) %in% month.name[c(1,2,12)],]
View(winter_all)

# calculate performance metrics for seasonal data
pbias_spring <- pbias(sim = spring_all$FLOW, obs = spring_all$FLOW.OBSERVED)
pbias_summer <- pbias(sim = summer_all$FLOW, obs = summer_all$FLOW.OBSERVED)
pbias_fall <- pbias(sim = fall_all$FLOW, obs = fall_all$FLOW.OBSERVED)
pbias_winter <- pbias(sim = winter_all$FLOW, obs = winter_all$FLOW.OBSERVED)

NSE_spring <- round(NSE(sim = spring_all$FLOW, obs = spring_all$FLOW.OBSERVED), digits = 4)
NSE_summer <- round(NSE(sim = summer_all$FLOW, obs = summer_all$FLOW.OBSERVED), digits = 4)
NSE_fall <- round(NSE(sim = fall_all$FLOW, obs = fall_all$FLOW.OBSERVED), digits = 4)
NSE_winter <- round(NSE(sim = winter_all$FLOW, obs = winter_all$FLOW.OBSERVED), digits = 4)

# plot spring data
spring_all_lf <- melt(spring_all, id.vars = "Date")
head(spring_all_lf)

ggplot(spring_all_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Spring", y="Flow")+
  scale_x_datetime(name = "Spring", date_breaks = "1 year", labels = date_format("%Y"))+
  annotate(geom = "text", x = as.POSIXct("2015-04-01"), y = 55, label = glue("% Bias = {pbias_spring}"))+
  annotate(geom = "text", x = as.POSIXct("2015-04-01"), y = 50, label = glue("NSE = {NSE_spring}"))

# plot summer data
summer_all_lf <- melt(summer_all, id.vars = "Date")
head(summer_all_lf)

ggplot(summer_all_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Summer", y="Flow")+
  scale_x_datetime(name = "Summer", date_breaks = "1 year", labels = date_format("%Y"))+
  annotate(geom = "text", x = as.POSIXct("2013-08-01"), y = 1.5, label = glue("% Bias = {pbias_summer}"))+
  annotate(geom = "text", x = as.POSIXct("2013-08-01"), y = 1.4, label = glue("NSE = {NSE_summer}"))

# plot fall data
fall_all_lf <- melt(fall_all, id.vars = "Date")
head(fall_all_lf)

ggplot(fall_all_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Fall", y="Flow")+
  scale_x_datetime(name = "Fall", date_breaks = "1 year", labels = date_format("%Y"))#+
  #annotate(geom = "text", x = as.POSIXct("2015-02-01"), y = 0.9, label = glue("% Bias = {pbias_winter}"))+
  #annotate(geom = "text", x = as.POSIXct("2015-02-01"), y = 0.85, label = glue("NSE = {NSE_winter}"))

# plot winter data
winter_all_lf <- melt(winter_all, id.vars = "Date")
head(winter_all_lf)

ggplot(winter_all_lf, aes(x=Date, y=value, col = variable))+
  geom_line()+
  labs(x="Winter", y="Flow")+
  scale_x_datetime(name = "Winter", date_breaks = "1 year", labels = date_format("%Y"))+
  annotate(geom = "text", x = as.POSIXct("2015-02-01"), y = 0.9, label = glue("% Bias = {pbias_winter}"))+
  annotate(geom = "text", x = as.POSIXct("2015-02-01"), y = 0.85, label = glue("NSE = {NSE_winter}"))

