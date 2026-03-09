from dotenv import load_dotenv
import os
import finnhub

load_dotenv()

key = os.getenv("FINN_HUB_API") or os.getenv("FINNHUB_API_KEY")
print("key repr:", repr(key), "len:", 0 if key is None else len(key))

client = finnhub.Client(api_key=key)
print(client.quote("AAPL"))
print(client.company_profile2(symbol="AAPL"))