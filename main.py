#%%
from stream.stream_simulator import stream_simulator
from serving.predict import predict_instance
from serving.notify import alert
import time

if __name__ == "__main__":
    for row in stream_simulator():
        pred = predict_instance(row)
        alert(pred, row)
        time.sleep(0.3)