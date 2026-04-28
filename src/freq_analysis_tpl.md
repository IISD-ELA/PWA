# Flood frequency analysis for the {watershed}

## Note on Methods

This data was automatically generated from either Water Survey of Canada gauge data or modeled flows for the watershed in question. The results of this analysis are intended for informational and exploratory research purposes only.

Peak daily flows were used to identify flood events in the watershed. Potentially Influential Low Floods (PILFs) were identified using the Multiple Grubbs-Beck Test (MGBT) as per the [USGS Guidelines for Determining Flow Frequency](https://pubs.usgs.gov/publication/tm4B5). However, these PILFs were removed from the analysis entirely. The distribution should not be considered to be representative of the observed conditions if a large portion of flood events are designated as PILFs (see [Diagnostic Information](#diagnostic-information)).

With PILFs removed, a frequency anaysis was conducted on the annual peak flows by assuming a Log-Pearson III distribution. A goodness of fit analysis was conducted on this analysis and is available under [Diagnostic Information](#diagnostic-information).

## Recurrence table

{event_returns}

## Plots

![Figure 1. Annual Flow Statistics](annual_stats.png)

![Figure 2. Daily Flows with flood years overlaid](overlay_years.png)


## Diagnostic information

Number of PILF events removed: {mgbt_removed}

PILF event discharge low threshold: {mgbt_threshold}

Goodness of fit of the probability distribution: {peak_flow_goodness_fit}

![Figure 3. Frequency Plot (goodness of fit)](frequency_plot.png)