# For RF:
    # remove with low variance
    # select K-best: 
        # r_regression, f_regression, mutual_info_regression
    # IV(?)
    # Sequential feature selection

# For LR
from sklearn.feature_selection import VarianceThreshold, SelectKBest, mutual_info_regression, RFECV
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor


def get_rf_feature_selection_pipeline():
    """
    Returns a list of tuples representing the pipeline for feature selection using
    Random Forest Regressor.
    
    Pipeline Steps:
    1. VarianceThreshold
    2. SelectKBest with mutual_info_regression as the score function
    
    Returns:
    List of tuples representing the pipeline for feature selection using Random Forest Regressor.
    """
    return [
        ('variance_threshold', VarianceThreshold()),
        ('select_k_best', SelectKBest(mutual_info_regression)),
        # ('model_based_feature_selection', RFECV(RandomForestRegressor(), step=5, cv=5))
    ]

def get_rf_feature_selection_grid():
    """
    Returns a dictionary of hyperparameters for Random Forest feature selection using GridSearchCV.
    
    The hyperparameters include:
    - variance_threshold: a VarianceThreshold object or 'passthrough'
    - variance_threshold__threshold: a float between 0 and 1
    - select_k_best: a SelectKBest object with mutual_info_regression score function or 'passthrough'
    - select_k_best__k: an integer
    - model_based_feature_selection__step: an integer
    
    Returns:
    A dictionary of hyperparameters for Random Forest feature selection using GridSearchCV.
    """
    return {
        # 'variance_threshold': [VarianceThreshold(), 'passthrough'],
        # 'variance_threshold__threshold': [0, 0.2],
        'select_k_best': [SelectKBest(mutual_info_regression)],
        'select_k_best__k': [30, 50],
        # 'model_based_feature_selection__step': [1, 5, 10],
    }
