"""scrypt 密码散列，记录算法参数、随机盐和派生结果。"""

import base64
import hashlib
import hmac
import secrets


class PasswordHasher:
    def hash(self, password):
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
        return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()

    def verify(self, password, record):
        try:
            algorithm, n, r, p, salt, expected = record.split("$")
            if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
                return False
            digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                                    n=int(n), r=int(r), p=int(p), dklen=32)
            return hmac.compare_digest(digest, base64.b64decode(expected))
        except (ValueError, TypeError):
            return False
