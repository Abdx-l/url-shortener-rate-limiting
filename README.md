# URL Shortener with Rate Limiting

A local HTTP shortener that derives collision-free base62 codes from SQLite row IDs and serves permanent redirects. A transactional token bucket limits requests per client key and returns `429` with `Retry-After` when exhausted. Frequently used redirects are cached in memory for one hour.

```sh
python server.py --database links.db --port 8080
python -m unittest discover -s tests -v
```

Create a link with `POST /links` and JSON such as `{"url":"https://example.com"}`. The response includes a short path like `/1`. Open that path to receive a `301` redirect. The bundled `redis_bucket.lua` is an atomic Redis implementation of the same limiter contract for deployments using Redis.

