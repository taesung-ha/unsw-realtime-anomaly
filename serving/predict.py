from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import pickle
import pandas as pd
import numpy as np
import joblib


with open("model/model.pkl", "rb") as f:
    model = pickle.load(f)

clamp_thresholds = joblib.load("model/clamp_thresholds.pkl")
log_thresholds = joblib.load("model/log_thresholds.pkl")
cat_thresholds = joblib.load("model/cat_thresholds.pkl")

ct_loaded = joblib.load("model/one_hot_encoder.pkl")
sc_loaded = joblib.load("model/standard_scaler.pkl")

def preprocess_input(df_row: pd.DataFrame):
    # Remove unnecessary columns
    list_drop = ['id', 'attack_cat']
    df_row = df_row.drop(list_drop, axis=1)
    
    # Clamping Extreme Values
    df_numeric = df_row.select_dtypes(include=[np.number])
    for feature in df_numeric.columns:
        if clamp_thresholds[feature]['max'] > 10 * clamp_thresholds[feature]['median'] and clamp_thresholds[feature]['max'] > 10:
            df_row[feature] = np.where(df_row[feature] < clamp_thresholds[feature]['95th'], df_row[feature], clamp_thresholds[feature]['95th'])
    
    # Apply log function to nearly all numeric, since they are all mostly skewed to the right
    df_numeric = df_row.select_dtypes(include=[np.number])
    for feature in df_numeric.columns:
        if log_thresholds[feature]['nunique'] > 50:
            if log_thresholds[feature]['min'] == 0:
                df_row[feature] = np.log(df_row[feature] + 1)
            else:
                df_row[feature] = np.log(df_row[feature])
    
    # Reduce the labels in categorical columns
    df_cat = df_row.select_dtypes(exclude=[np.number])
    for feature in df_cat.columns:
        if cat_thresholds[feature]['nunique'] > 6:
            df_row[feature] = np.where(df_row[feature].isin(cat_thresholds[feature]['top_values']), df_row[feature], '-')
    
    X = df_row.iloc[:, :-1]
    y = df_row.iloc[:, -1]
    
    # One-hot encode categorical features
    X = np.array(ct_loaded.transform(X))
    
    # Standardize continuous features
    X[:, 18:] = sc_loaded.transform(X[:, 18:])

    return X, y
    
def predict_instance(df: pd.DataFrame):
    X, y = preprocess_input(df)
    pred = model.predict(X)
    score = float(model.predict_proba(X)[0][1])
    return pred, score