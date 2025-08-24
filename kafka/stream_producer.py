from kafka import KafkaProducer
import pandas as pd
import json
import time

KAFKA_BROKER = 'localhost:9092'
TOPIC_NAME = "network-log"
TARGET_RPS = 1200
SLICE_MSGS = 500

def json_serializer(v):
    return json.dumps(v, separators=(',', ':')).encode('utf-8')


producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=json_serializer,
    acks=1,
    linger_ms=10,
    batch_size=128*1024,
    compression_type="lz4",
    max_in_flight_requests_per_connection=5,
    retries=3,
)

df = pd.read_csv("../data/UNSW_NB15_training-set.csv")
records = df.to_dict(orient='records')
'''
changed_ids= [47912, 62209, 62220, 62225, 62230, 62233, 62238, 62243, 62249, 62255, 62362, 62366, 62375, 62378, 62381, 62386,
'''
#47912일때와 0일때의 data regime이 완전히 다름
def send_at_fixed_rps(recs, target_rps=TARGET_RPS, slice_msgs=SLICE_MSGS, warmup_sec=0.5):
    time.sleep(warmup_sec)
    
    start = time.time()
    sent = 0
    i = 0
    
    while i < len(recs):
        batch = recs[i : min(i + slice_msgs, len(recs))]
        for r in batch:
            producer.send(TOPIC_NAME, value=r)
        producer.flush()

        sent += len(batch)
        i += len(batch)
        
        elapsed = time.time() - start
        target_elapsed = sent / float(target_rps)
        to_sleep = target_elapsed - elapsed
        if to_sleep > 0:
            time.sleep(to_sleep)
    
    total = time.time() - start
    tps = sent / total if total > 0 else float("inf")
    
    pretty = int(round(tps / 50.0)*50)
    print(f"Throughput: ~{pretty} events/sec | raw={tps:.1f} | sent={sent} | time={total:.2f}s")
    
if __name__ == "__main__":
    send_at_fixed_rps(records)

'''
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
# changed_ids= [47912, 62209, 62220, 62225, 62230, 62233, 62238, 62243, 62249, 62255, 62362, 62366, 62375, 62378, 62381, 62386,
#47912일때와 0일때의 data regime이 완전히 다름

for _, row in df.iterrows():
    message = row.to_dict()
    producer.send(TOPIC_NAME, value=message)
    print(f"Sent message: {message}")
    time.sleep(1.0)
'''