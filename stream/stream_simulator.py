from fastapi import FastAPI
import pandas as pd
import time
import uvicorn
import pickle

def stream_simulator(filepath="data/UNSW_NB15_testing-set.csv"):
    for chunk in pd.read_csv(filepath, chunksize=1):
        yield chunk