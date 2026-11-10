"""同步协议客户端，由界面后台工作线程调用。"""

import socket
import ssl
import uuid

from restaurant.domain import BusinessError
from restaurant.protocol import encode_frame, decode_frame, read_frame


class TcpClient:
    def __init__(self, config):
        self.config = config
        self.socket = None
        self.stream = None

    def connect(self):
        self.close()
        context = ssl.create_default_context(cafile=self.config["cert_file"])
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        raw = socket.create_connection((self.config["host"], self.config["port"]), timeout=5)
        try:
            self.socket = context.wrap_socket(raw, server_hostname=self.config["server_hostname"])
            self.socket.settimeout(10)
            self.stream = self.socket.makefile("rb")
        except Exception:
            raw.close()
            raise

    def request(self, type, data):
        request_id = uuid.uuid4().hex
        try:
            if self.socket is None:
                self.connect()
            self.socket.sendall(encode_frame({"type": type, "request_id": request_id, "data": data}))
            frame = read_frame(self.stream)
            if frame is None:
                raise ConnectionError("server closed")
            response = decode_frame(frame)
            if not isinstance(response, dict) or response.get("request_id") != request_id:
                raise ConnectionError("request mismatch")
        except (OSError, BusinessError):
            self.close()
            raise
        if response["code"]:
            raise BusinessError(response["code"], response["msg"])
        return response["data"]

    def close(self):
        if self.stream:
            self.stream.close()
        if self.socket:
            self.socket.close()
        self.stream = self.socket = None
