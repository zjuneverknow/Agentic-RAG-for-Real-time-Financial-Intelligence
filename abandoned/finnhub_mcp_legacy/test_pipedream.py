from dotenv import load_dotenv
load_dotenv()

from nodes.retrieval.finnhub_pipedream import call_pipedream_finnhub

doc = call_pipedream_finnhub("What is Apple's latest stock price?", "AAPL")
print("doc exists:", doc is not None)
if doc:
    print("metadata:", doc.metadata)
    print("content:", doc.page_content[:1000])

