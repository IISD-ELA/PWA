import pandas as pd

def feature_checks(feature_df):
    '''
    Summarizes the feature dataframe (column names, start and end time, dataframe shape)
    Prameters
    ---------
    feature_df : DataFrame
        DataFrame containing features
    
    Returns
    -------
    feature_df.notna().sum() : Series
        Count of non-null values by column
    '''


    print('columns %s' % feature_df.columns)
    print('start time %s' % feature_df.index[1])
    print('end time %s' % feature_df.index[-1])
    print('number of rows %s and columns %f' % feature_df.shape)
    print('Count of non-null values by column')
    
    return (feature_df.notna().sum())

def filter_for_param_site(df, param: str, site: str):
    '''
    Filter full AquaHive dataset for parameter param and site site

    Parameters
    ----------
    df : DataFrame
        AquaHive dataset
    param: str
        The parameter to filter for (e.g., 'tn' for total nitrogen)
    site: str
        The AquahHive site to filter for (e.g., 'pnwa' for Pinawa)

    Returns
    -------
    df_out: DataFrame
        Input AquaHive Dataset filtered for param and site
    '''
    df_out = df.copy()
    
    
    df_out = df_out[
                (df_out['parameter'] == param) &
                (df_out['site'] == site)
                ]
    
    
    return df_out

def convert_timestamps(df):
    '''
    Return df with new column containing timestamps converted to Canada/Central,
    taking DST into account
    Parameters
    ----------
    df : DataFrame
            AquaHive Dataset
    Returns
    -------
    df_out: DataFrame
        df with additional converted timestamp column
    '''
    
    df_out = df.copy()
    
    
    df_out['timestamp_ccentral'] = \
        pd.to_datetime(df_out['timestamp']).dt.tz_convert('Canada/Central')
    
    
    return df_out

    
                                     
def calc_param_site_features_hrs_ago(df, param: str, site: str, hours_ago_start: int, hours_ago_end: int):
    '''
    Return datasets containing calculated features for parameter param and 
    site site records in df for the specified hours_ago_start-hours_ago_end time lag bucket

    Parameters
    ----------
    df : DataFrame
        AquaHive dataset
    param : str
        The parameter to filter for (e.g., 'tn' for total nitrogen)
    site : str
        The site to filter for (e.g., 'pnwa' for Pinawa)
    hours_ago_start: int
        The start of time bucket (e.g., 4 for 4-6h ago time bucket)
    hours_ago_end: int
        The end of time bucket (e.g., 6 for 4-6h ago time bucket)

    Returns
    -------
    final_df_conc, final_df_load: Tuple of two DataFrames
        First dataframe is feature table for nutrient concentration
        Second dataframe is feature table for nutrient load

    '''
    # Make copy of original dataset to avoid modifying it
    data_out = df.copy()
    
    
    # Filter for parameter and site and create datetime type timestamp column 
        # (Canada Central)
    data_out = convert_timestamps(calc_nutrient_load(
            filter_for_param_site(data_out, param, site), param))
    
    
    # Sort timestamps in ascending order
    data_out = data_out.sort_values('timestamp_ccentral', ascending=True)
    
    
    # Calculate number of records in hours-ago range
    hours_offset = (hours_ago_end - hours_ago_start) + 1
    
    
    # Create rolling windows for hours_offset bucket
    rolling_window = data_out[['value', 'load', 'timestamp_ccentral']].rolling(
                     window=str(hours_offset)+'h', 
                     on='timestamp_ccentral',
                     min_periods= hours_offset, 
                     closed = 'left')
    
    # Calculate the number of positions to shift depending on hours-ago range
    shift_scalar = hours_ago_start//hours_offset
    shift_num = shift_scalar*hours_offset
    
    
    # Calculate mean, max, min, and max-min range for param concentration
        # Not calculating variance since windows are too small
    mean = rolling_window['value'].mean().shift(shift_num)
    # min_ = rolling_window['value'].min().shift(shift_num)
    # max_ = rolling_window['value'].max().shift(shift_num)
    # max_min = abs(max_ - min_)
    
    
    # Calculate mean, max, min, and max-min range for param load
        # Not calculating variance since windows are too small
    mean_load = rolling_window['load'].mean().shift(shift_num)
    # min_load = rolling_window['load'].min().shift(shift_num)
    # max_load = rolling_window['load'].max().shift(shift_num)
    # max_min_load = abs(max_load - min_load)
    
    
    #  Add new columns with calculated features for concentration and load
    final_df_conc = pd.concat([mean], #min_, max_, max_min],
                              axis=1)
    final_df_load = pd.concat([mean_load], #min_load, max_load, max_min_load],
                              axis=1)
    cols_conc = [
            x+'_'+str(hours_ago_start)+'_'+str(hours_ago_end)
            for x in [param+'_'+site+'_mean']
                    #   param+'_'+site+'_min', 
                    #   param+'_'+site+'_max', 
                    #   param+'_'+site+'_max_min']
                ]
    
    cols_load = [
            x+'_'+str(hours_ago_start)+'_'+str(hours_ago_end)
            for x in [param+'_'+site+'_mean_load']
                    #   param+'_'+site+'_min_load', 
                    #   param+'_'+site+'_max_load', 
                    #   param+'_'+site+'_max_min_load']
                ]
            
    final_df_conc.columns = cols_conc
    final_df_load.columns = cols_load
    
    
    # Add timestamp column
    final_df_conc.loc[:, 'timestamp_ccentral'] = data_out['timestamp_ccentral']
    final_df_load.loc[:, 'timestamp_ccentral'] = data_out['timestamp_ccentral']
    
    
    # return a tuple of two separate dataframes, one concentration one load
    return (final_df_conc, final_df_load)


def calc_discharge_site_features_hrs_ago(df, site: str, hours_ago_start: int,
                                         hours_ago_end: int):
    '''
    Return dataset containing calculated discharge features for site site
    records in df for hours_ago_start-hours_ago_end hours ago bucket

    Parameters
    ----------
    df : DataFrame
        AquaHive Dataset
    site : str
        The site to filter for (e.f., 'pnwa' for Pinawa)
    hours_ago_start : int
        The start of time bucket (e.g., 4 for 4-6h ago time bucket)
    hours_ago_end : int
        The end of time bucket (e.g., 6 for 4-6h ago time bucket)

    Returns
    -------
    final_df: Dataframe
        Dataset containing desired features

    '''
    # Make copy of original dataset to avoid modifying it
    data_out = df.copy()
    
    
    # Filter for site and create converted timestamp column
    data_out = convert_timestamps(data_out[data_out['site'] == site])
    
    
    # Drop duplicate timestamps
    data_out = data_out.drop_duplicates(subset=['timestamp_ccentral'])
    
    
    # Sort timestamps in ascending order
    data_out = data_out.sort_values('timestamp_ccentral', ascending=True)
    
    
    # Calculate number of records in hours-ago range
    hours_offset = (hours_ago_end - hours_ago_start) + 1
    
    
    # Create rolling windows for hours_offset bucket
    rolling_window = data_out[['discharge', 'timestamp_ccentral']].rolling(
                     window=str(hours_offset)+'h', 
                     on='timestamp_ccentral',
                     min_periods=hours_offset, 
                     closed='left')
    
    
    # Calculate the number of positions to shift depending on hours-ago range
    shift_scalar = hours_ago_start//hours_offset
    shift_num = shift_scalar*hours_offset
    
    
    # Calculate mean, max, min, and max-min range for discharge
        # Not calculating variance since windows are too small
    mean = rolling_window['discharge'].mean().shift(shift_num)
    # min_ = rolling_window['discharge'].min().shift(shift_num)
    # max_ = rolling_window['discharge'].max().shift(shift_num)
    # max_min = abs(max_ - min_)
    
    
    #  Add new columns with calculated features
    final_df = pd.concat([mean], #min_, max_, max_min],
                          axis=1)
    
    cols = [
            x+'_'+str(hours_ago_start)+'_'+str(hours_ago_end)
            for x in ['dschrg_'+site+'_mean']
                    #   'dschrg_'+site+'_min', 
                    #   'dschrg'+site+'_max', 
                    #   'dschrg'+site+'_max_min']
           ]
    
    final_df.columns = cols
    final_df.loc[:, 'timestamp_ccentral'] = data_out['timestamp_ccentral']
    
    return final_df
    
def calc_nutrient_load(df, param: str):
    '''
    Return df with new column containing calculated nutrient load values

    Parameters
    ----------
    df : DataFrame
        AquaHive Dataset
    param: str
        The parameter that df contains (df must only contain data for a single
                                        parameter for unit consistency)
    Returns
    -------
    df_out : DataFrame
        df with additional nutrient load column

    '''
    df_out = df.copy()
    
    # Unit conversions for parameters not listed in mg/L units
    if param == 'turbidity':
        # Convert turbidity units from NTU to mg/L
        df_out['value_converted'] = df_out['value']/3.
        df_out['load'] = df_out['value_converted']*df_out['discharge']
        df_out.drop(columns=['value_converted'], inplace=True)  
    # if param == 'total_dissolved_solids':
        # Convert total dissolved solids units from ppt to mg/L
        # ... Add some code here and uncomment when we need tds eventually...
    else: 
        # This calculation assumes that parameter units are mg/L
        df_out['load'] = df_out['value']*df_out['discharge']
    
    
    return df_out

#Read and combine CSV files, grouping by 'timestamp_ccentral', df short for dataframe
def read_and_merge_csv(files, folder):
    data_paths = [folder + f for f in files]
    merged_df = pd.read_csv(data_paths[0])
    for file in data_paths[1:]:
        df = pd.read_csv(file)
        merged_df = pd.merge(merged_df, df, on='timestamp_ccentral', how='outer')
    return merged_df
