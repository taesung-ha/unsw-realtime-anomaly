import pandas as pd
import psycopg2
import pickle
from serving.predict import preprocess_input 
from db.db_config import DB_CONFIG

with open("../model/model.pkl", "rb") as f:
    model = pickle.load(f)

df = pd.read_csv("../data/UNSW_NB15_training-set.csv")
X = preprocess_input(df)

scores = model.decision_function(X)

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

for i, score in enumerate(scores):
    cur.execute(
        "INSERT INTO anomaly_scores (source, score) VALUES (%s, %s)",
        ('UNSW', float(score))
    )
conn.commit()
cur.close()
conn.close()