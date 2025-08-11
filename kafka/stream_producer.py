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

df = pd.read_csv("../data/UNSW_NB15_training-set.csv")[47850:]
'''
changed_ids= [47912, 62209, 62220, 62225, 62230, 62233, 62238, 62243, 62249, 62255, 62362, 62366, 62375, 62378, 62381, 62386,
'''
#47912일때와 0일때의 data regime이 완전히 다름

for _, row in df.iterrows():
    message = row.to_dict()
    producer.send(TOPIC_NAME, value=message)
    print(f"Sent message: {message}")
    time.sleep(1.0)

