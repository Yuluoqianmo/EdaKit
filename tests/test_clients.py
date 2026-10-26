import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
import pytest
from edakit.services.clients import ClientPool, ServiceClosing
from edakit.services.network import request_json, BudgetExpired
from edakit.errors import UpstreamChangedError


class Client:
    def __init__(self): self.closed=False
    def close(self): self.closed=True


def test_pool_reuse_concurrency_and_shutdown():
    pool=ClientPool(Client)
    with pool.lease() as first: pass
    with pool.lease() as second: assert first is second
    barrier=threading.Barrier(2);clients=[]
    def worker():
        with pool.lease() as client:
            clients.append(client);barrier.wait(timeout=5)
    threads=[threading.Thread(target=worker) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(timeout=6)
    assert len(clients)==2 and clients[0] is not clients[1]
    with pool.lease() as active:
        pool.close()
        assert not active.closed
    assert active.closed
    with pytest.raises(ServiceClosing):
        with pool.lease(): pass
    assert all(c.closed for c in clients)


def test_pool_factory_failure_and_bad_client():
    fail=True
    def factory():
        if fail: raise ValueError('factory')
        return Client()
    pool=ClientPool(factory)
    with pytest.raises(ValueError):
        with pool.lease():pass
    fail=False
    with pytest.raises(requests.ConnectionError):
        with pool.lease() as client: raise requests.ConnectionError('broken')
    assert client.closed
    with pool.lease() as replacement: assert replacement is not client
    pool.close()


@pytest.fixture
def local_http():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            try:
                if self.path=='/headers':time.sleep(.4)
                if self.path=='/403':
                    self.send_response(403);self.end_headers();return
                self.send_response(200);self.end_headers()
                if self.path=='/big':self.wfile.write(b'x'*2_000_001)
                elif self.path=='/blocks':
                    for _ in range(12):self.wfile.write(b' '*4096);self.wfile.flush();time.sleep(.08)
                elif self.path=='/trickle':
                    for _ in range(10):self.wfile.write(b' ');self.wfile.flush();time.sleep(.05)
                else:self.wfile.write(b'{"value":1}')
            except (OSError,ConnectionError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield 'http://127.0.0.1:%s'%server.server_port
    server.shutdown();server.server_close();thread.join(timeout=2)


def test_budget_blocks_and_size(local_http):
    with requests.Session() as session:
        with pytest.raises(BudgetExpired):request_json(session,'get',local_http+'/blocks',budget=.25,retries=3)
        with pytest.raises(UpstreamChangedError,match='2 MB'):request_json(session,'get',local_http+'/big',budget=2,retries=1)
        assert request_json(session,'get',local_http, budget=2,retries=1)=={'value':1}


def test_trickle_and_header_overrun_is_not_hard_deadline(local_http):
    with requests.Session() as session:
        start=time.monotonic()
        with pytest.raises(BudgetExpired):request_json(session,'get',local_http+'/trickle',budget=.1,retries=1)
        assert time.monotonic()-start>.3
        with pytest.raises(BudgetExpired):request_json(session,'get',local_http+'/headers',budget=.1,retries=1)


def test_403_attempt_limit_and_response_closed():
    class Response:
        status_code=403
        closed=False
        def close(self): self.closed=True
    class Session:
        def __init__(self):self.responses=[]
        def get(self,*args,**kwargs):r=Response();self.responses.append(r);return r
    session=Session()
    with pytest.raises(UpstreamChangedError,match='403'):request_json(session,'get','unused',budget=10,retries=4)
    assert len(session.responses)==2 and all(r.closed for r in session.responses)
