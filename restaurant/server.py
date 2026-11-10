"""最多16个同时连接的 TLS 服务器，连接拥有独立登录会话。"""

import logging
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor

from restaurant.domain import BusinessError
from restaurant.protocol import read_frame, decode_frame, encode_frame

logger = logging.getLogger(__name__)


class ClientHandler:
    def __init__(self, connection, router):
        self.socket = connection
        self.session = {}
        self.router = router

    def serve(self):
        with self.socket, self.socket.makefile("rb") as stream:
            try:
                while True:
                    frame = read_frame(stream)
                    if frame is None:
                        break
                    try:
                        response = self.router.dispatch(self.session, decode_frame(frame))
                    except BusinessError as exc:
                        response = {"request_id": None, "code": exc.code, "msg": str(exc), "data": {}}
                    try:
                        encoded = encode_frame(response)
                    except BusinessError as exc:
                        encoded = encode_frame({"request_id": response.get("request_id"), "code": exc.code,
                                                "msg": str(exc), "data": {}})
                    self.socket.sendall(encoded)
            except BusinessError as exc:
                self.socket.sendall(encode_frame({"request_id": None, "code": exc.code, "msg": str(exc), "data": {}}))
            except (OSError, ssl.SSLError):
                logger.info("connection_closed employee_id=%s", self.session.get("employee_id"))
            finally:
                self.session.clear()


class RestaurantServer:
    def __init__(self, config, router):
        self.router = router
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(config["cert_file"], config["key_file"])
        self.listener = socket.socket()
        self.listener.bind((config["host"], config["port"]))
        self.listener.listen(16)
        self.listener.settimeout(0.5)
        self.address = self.listener.getsockname()
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(16)
        self._executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="client")
        self._connections = set()
        self._lock = threading.Lock()

    def _serve_connection(self, raw):
        connection = raw
        try:
            raw.settimeout(10)
            connection = self.context.wrap_socket(raw, server_side=True)
            connection.settimeout(300)
            with self._lock:
                self._connections.discard(raw)
                self._connections.add(connection)
            ClientHandler(connection, self.router).serve()
        except (OSError, ssl.SSLError):
            logger.info("TLS连接已结束")
        finally:
            with self._lock:
                self._connections.discard(raw)
                self._connections.discard(connection)
            connection.close()
            self._slots.release()

    def serve_forever(self):
        while not self._stop.is_set():
            try:
                raw, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._slots.acquire(blocking=False):
                raw.close()
                continue
            with self._lock:
                self._connections.add(raw)
            self._executor.submit(self._serve_connection, raw)

    def close(self):
        self._stop.set()
        self.listener.close()
        with self._lock:
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self._executor.shutdown(wait=True)
