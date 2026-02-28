import pandas as pd
import pandas_ta as ta

df = pd.DataFrame({'Close': range(100), 'High': range(100), 'Low': range(100)})

# Does pandas_ta append true mean it adds it directly to the df? Yes, by default.
# But in our code, we do df.ta.macd(append=False) because we don't specify append. Default is False.
# wait, macd = df.ta.macd()
# then we do df = pd.concat([df, macd])
# If macd is returned, we concat it. This means df has unique columns initially, then we concat, then we deduplicate.
