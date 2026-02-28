import pandas as pd
import pandas_ta as ta

df = pd.DataFrame({'Close': range(100), 'High': range(100), 'Low': range(100)})

try:
    df.ta.macd(append=True)
    print("MACD appended:", [c for c in df.columns])
    df.ta.macd(append=True)
    print("MACD appended again:", [c for c in df.columns])
except Exception as e:
    print(e)
