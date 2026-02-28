import pandas as pd
import pandas_ta as ta

df = pd.DataFrame({'Close': range(100), 'High': range(100), 'Low': range(100)})
kdj = df.ta.kdj(length=9, signal=3)

# If we run calculate_indicators twice on the same DF (or a copy where ta is somehow cached)
df2 = df.copy()
kdj2 = df2.ta.kdj(length=9, signal=3)
if kdj2 is not None:
    print(kdj2.columns)
