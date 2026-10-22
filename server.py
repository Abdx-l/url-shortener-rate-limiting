"""SQLite-backed base62 shortener with transactional token buckets."""
from __future__ import annotations

import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlparse


ALPHABET="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SCHEMA="""
CREATE TABLE IF NOT EXISTS links(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS buckets(client TEXT PRIMARY KEY, tokens REAL NOT NULL, updated REAL NOT NULL);
"""


def encode(number: int) -> str:
    if number < 0: raise ValueError("ID must be nonnegative")
    if number == 0: return ALPHABET[0]
    digits=""
    while number:
        number,remainder=divmod(number,62)
        digits=ALPHABET[remainder]+digits
    return digits


def decode(code: str) -> int:
    if not code or any(c not in ALPHABET for c in code): raise ValueError("Invalid code")
    number=0
    for c in code: number=number*62+ALPHABET.index(c)
    if encode(number)!=code: raise ValueError("Noncanonical code")
    return number


def validate_url(url: str) -> str:
    if not isinstance(url,str) or len(url)>2048:
        raise ValueError("Invalid URL")
    parsed=urlparse(url)
    if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only http(s) URLs without credentials are supported")
    return url


class Store:
    def __init__(self,path: Path,capacity: float = 10,refill: float = 1):
        if capacity <= 0 or refill <= 0: raise ValueError("Invalid rate limit")
        self.path=Path(path)
        self.capacity,self.refill=capacity,refill
        self.lock=threading.RLock()
        self.cache={}
        with closing(sqlite3.connect(self.path)) as db: db.executescript(SCHEMA)

    def create(self,url: str) -> str:
        validate_url(url)
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            with db: number=db.execute("INSERT INTO links(url) VALUES(?)",(url,)).lastrowid
        return encode(number)

    def lookup(self,code: str,now: float | None = None) -> str | None:
        number=decode(code)
        now=time.time() if now is None else now
        with self.lock:
            entry=self.cache.get(number)
            if entry and entry[1]>now: return entry[0]
            with closing(sqlite3.connect(self.path)) as db:
                row=db.execute("SELECT url FROM links WHERE id=?",(number,)).fetchone()
            if row: self.cache[number]=(row[0],now+3600)
            return row[0] if row else None

    def allow(self,client: str,now: float | None = None,cost: float = 1) -> tuple[bool,int]:
        now=time.time() if now is None else now
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT tokens,updated FROM buckets WHERE client=?",(client,)).fetchone()
            tokens=min(self.capacity,(row[0] + max(0,now-row[1])*self.refill) if row else self.capacity)
            allowed=tokens >= cost
            if allowed: tokens-=cost
            db.execute("INSERT INTO buckets(client,tokens,updated) VALUES(?,?,?) ON CONFLICT(client) DO UPDATE SET tokens=excluded.tokens,updated=excluded.updated",(client,tokens,now))
            db.commit()
        return allowed,0 if allowed else max(1,int((cost-tokens)/self.refill + .999999))


def handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status: int,body: bytes = b"",headers: dict | None = None):
            self.send_response(status)
            for key,value in (headers or {}).items(): self.send_header(key,str(value))
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            if body: self.wfile.write(body)

        def limited(self):
            allowed,wait=store.allow(self.client_address[0])
            if not allowed: self.respond(429,b"Rate limit exceeded",{"Retry-After":wait})
            return not allowed

        def do_POST(self):
            if self.limited(): return
            if self.path!="/links": self.respond(404); return
            try:
                length=int(self.headers.get("Content-Length","0"))
                if length<1 or length>4096: raise ValueError("Invalid body size")
                body=json.loads(self.rfile.read(length))
                code=store.create(body["url"])
            except (ValueError,KeyError,TypeError,json.JSONDecodeError):
                self.respond(400,b"Invalid URL or JSON"); return
            result=json.dumps({"code":code,"path":"/"+code}).encode()
            self.respond(201,result,{"Content-Type":"application/json"})

        def do_GET(self):
            if self.limited(): return
            try: url=store.lookup(self.path.lstrip("/"))
            except ValueError: self.respond(404); return
            if url is None: self.respond(404); return
            self.respond(301,headers={"Location":url,"Cache-Control":"public, max-age=3600"})
    return Handler


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,default=Path("links.db"))
    parser.add_argument("--port",type=int,default=8080)
    parser.add_argument("--capacity",type=float,default=10)
    parser.add_argument("--refill",type=float,default=1)
    args=parser.parse_args()
    store=Store(args.database,args.capacity,args.refill)
    with ThreadingHTTPServer(("127.0.0.1",args.port),handler(store)) as server:
        print(f"Listening on http://127.0.0.1:{server.server_port}")
        server.serve_forever()

