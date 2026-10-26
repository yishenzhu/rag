"""Redis token-bucket rate limiting."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])

local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]) or burst
local ts = tonumber(data[2]) or now

local delta = math.max(0, now - ts) / 1000
tokens = math.min(burst, tokens + delta * rate)

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
local ttl = math.max(1000, math.ceil((burst / rate) * 1000) + 1000)
redis.call('PEXPIRE', key, ttl)
return {allowed, math.floor(tokens)}
"""


class RateLimiter:
    def __init__(self, redis: Redis, rate: int, burst: int) -> None:
        self.redis = redis
        self.rate = max(1, rate)
        self.burst = max(1, burst)

    async def allow(
        self, identity: str, cost: int = 1
    ) -> tuple[bool, int]:
        try:
            result = await self.redis.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                f"rl:{identity}",
                self.rate,
                self.burst,
                cost,
            )
        except RedisError:
            return True, self.burst
        return bool(result[0]), int(result[1])
