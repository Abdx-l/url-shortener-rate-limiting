import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from server import Store, encode, decode, handler


class ShortenerTests(unittest.TestCase):
    def test_base62_and_bucket(self):
        for number in (1,61,62,3844,1000000): self.assertEqual(decode(encode(number)),number)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/"links.db",capacity=2,refill=1)
            a=store.create("https://example.com/a")
            b=store.create("https://example.com/b")
            self.assertNotEqual(a,b)
            self.assertEqual(store.lookup(a),"https://example.com/a")
            self.assertEqual(store.allow("client",now=10),(True,0))
            self.assertEqual(store.allow("client",now=10),(True,0))
            self.assertEqual(store.allow("client",now=10),(False,1))
            self.assertEqual(store.allow("client",now=11),(True,0))

    def test_http_redirect_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/"links.db",capacity=2,refill=.001)
            server=ThreadingHTTPServer(("127.0.0.1",0),handler(store))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                conn=http.client.HTTPConnection("127.0.0.1",server.server_port)
                conn.request("POST","/links",body=json.dumps({"url":"https://example.com"}),headers={"Content-Type":"application/json"})
                response=conn.getresponse(); self.assertEqual(response.status,201)
                path=json.loads(response.read())["path"]
                conn.request("GET",path)
                response=conn.getresponse(); self.assertEqual(response.status,301)
                self.assertEqual(response.getheader("Location"),"https://example.com"); response.read()
                conn.request("GET",path)
                response=conn.getresponse(); self.assertEqual(response.status,429)
                self.assertIsNotNone(response.getheader("Retry-After")); response.read(); conn.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__=="__main__": unittest.main()

