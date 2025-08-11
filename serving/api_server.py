# serving/api_server.py
from fastapi import FastAPI
from kafka import KafkaConsumer
from threading import Thread
import json, pandas as pd
from serving.predict import predict_instance
from serving.slack_alert import send_slack_alert
from db.db_utils import save_to_db

app = FastAPI()

def consume_messages():
    consumer = KafkaConsumer(
        'network-log',
        bootstrap_servers='localhost:9092',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        group_id='fastapi-detector-group'
    )
    
    for msg in consumer:
        raw = msg.value
        row_df = pd.DataFrame([raw])
        prediction, score = predict_instance(row_df)
        print(f"[Kafka Consumer] Received data: {raw}")
        print(f"[Kafka Consumer] Prediction: {prediction[0]}")
        print(f"[Kafka Consumer] Score: {score}")
        
        if prediction[0] == 1:
            send_slack_alert(f" !!! Anomaly detected: Data: {raw}, Score: {score} !!!")
        save_to_db("UNSW", score, prediction[0], raw)
        print()

@app.on_event("startup")
def startup_event():
    t = Thread(target=consume_messages)
    t.daemon = True
    t.start()

@app.get("/")
def root():
    return {"message": "UNSW Realtime Anomaly Detection API"}

