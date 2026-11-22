"""HTTP application used by the isolated Redis Sentinel failover test."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from redis.exceptions import RedisError
from redis.sentinel import Sentinel

sentinels = [
    (host, int(os.environ["REDIS_SENTINEL_PORT"]))
    for host in os.environ["REDIS_SENTINEL_HOSTS"].split(",")
]
sentinel = Sentinel(
    sentinels, socket_timeout=1,
    sentinel_kwargs={"password": os.environ["REDIS_SENTINEL_PASSWORD"], "socket_timeout": 1},
)
redis = sentinel.master_for(os.environ["REDIS_SENTINEL_MASTER"], password=os.environ["REDIS_PASSWORD"],
                            socket_timeout=3, decode_responses=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path == "/seed":
                redis.set("session", "before")
                redis.set("cache", "before")
                redis.delete("queue")
                redis.rpush("queue", "before")
                result = redis.wait(2, 2000)
                if result != 2:
                    self.send_error(503)
                    return
            elif self.path == "/recover":
                result = [redis.get("session"), redis.get("cache"), redis.lpop("queue")]
                redis.set("session", "after")
                redis.set("cache", "after")
                redis.rpush("queue", "after")
                result.extend([redis.get("session"), redis.get("cache"), redis.lpop("queue")])
            else:
                self.send_error(404)
                return
        except RedisError:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_GET(self):
        try:
            redis.ping()
        except RedisError:
            self.send_error(503)
            return
        self.send_response(200)
        self.end_headers()


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
