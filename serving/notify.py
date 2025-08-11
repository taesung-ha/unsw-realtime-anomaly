def alert(prediction, row):
    if prediction != 'normal':
        print(f"🚨 ALERT: {prediction} detected!")
        print(f"Details: {row.to_dict()}")