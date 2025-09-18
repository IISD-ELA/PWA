# Take user input for model name and set up paths
# model_str_in = input("Enter the model name (e.g., 'manning'): ")
model_str_in = "Cypress_New"
if model_str_in[-1] == '/': 
    model_str = model_str_in
else :
    model_str = model_str_in + '/'

DATA_RAW = r"../Data/Raw/" + model_str
DATA_INTERIM = r"../Data/Interim/" + model_str
DATA_PROCESSED = r"../Data/Processed/" + model_str
DATA_CAL= r"../Data/Calibration/" + model_str