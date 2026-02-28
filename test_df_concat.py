import pandas as pd
import pandas_ta as ta

df = pd.DataFrame({'Close': range(100), 'High': range(100), 'Low': range(100)})

# What happens if calculate_indicators receives raw_data with duplicated columns?
df['K'] = 1
df = pd.concat([df, df['K']], axis=1) # force duplicated
try:
    df = df.loc[:, ~df.columns.duplicated()]
    print(df.columns)
except Exception as e:
    print(e)
