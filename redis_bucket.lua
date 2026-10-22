-- KEYS[1] = bucket key; ARGV = now_ms, capacity, refill_tokens_per_second, cost
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local previous = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens = tonumber(previous[1]) or capacity
local updated = tonumber(previous[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - updated) * refill / 1000)
local allowed = tokens >= cost
if allowed then tokens = tokens - cost end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'updated', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / refill * 1000) + 1000)
local wait_ms = allowed and 0 or math.ceil((cost - tokens) / refill * 1000)
return {allowed and 1 or 0, wait_ms}

