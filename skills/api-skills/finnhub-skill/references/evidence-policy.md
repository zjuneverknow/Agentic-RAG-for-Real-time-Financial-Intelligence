# Finnhub Evidence Policy

## Evidence Shape

Scripts return:

```json
{
  "ok": true,
  "route": {},
  "evidence": {
    "content": "...",
    "metadata": {}
  },
  "errors": []
}
```

The retrieval node should pass `evidence.content` and `evidence.metadata` to the
evidence ledger as one evidence item.

## Citation Requirements

Include these metadata fields whenever present:

- `source_name`: usually `Finnhub API`
- `source_type`: `finnhub`
- `endpoint`
- `tool_name`
- `symbol`
- `timestamp`

The answer contract should cite the endpoint/tool, not only "Finnhub".

## Failure Handling

If a script returns `ok=false`:

- Keep the script error in `retrieval_failures`.
- Do not fabricate values from the question.
- If symbol was missing, run `symbols.py search` before retrying.
- If endpoint returned empty data, either try the declared fallback script or report that Finnhub did not provide the data.

## Freshness

Finnhub data is live vendor data at call time. The timestamp in metadata is the
retrieval timestamp, not necessarily the market-data timestamp. For "latest" or
"current" questions, always expose the retrieval timestamp in the final source
list when possible.
