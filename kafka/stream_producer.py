from kafka import KafkaProducer
import pandas as pd
import json
import time

KAFKA_BROKER = 'localhost:9092'
TOPIC_NAME = "network-log"

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

df = pd.read_csv("../data/UNSW_NB15_training-set.csv")

for _, row in df.iterrows():
    message = row.to_dict()
    producer.send(TOPIC_NAME, value=message)
    print(f"Sent message: {message}")
    time.sleep(1.0)