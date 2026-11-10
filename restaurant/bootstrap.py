"""独立本机 MySQL 实例、演示数据和 TLS 证书的首次启动准备。"""

import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pymysql
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from restaurant.security import PasswordHasher

DEMO_PASSWORD = "Demo@12345"


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def runtime_home():
    if os.environ.get("RESTAURANT_HOME"):
        return Path(os.environ["RESTAURANT_HOME"]).resolve()
    return (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent) / ".runtime" / "demo"


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("cert_file", "key_file", "log_file"):
        if key in config and not Path(config[key]).is_absolute():
            config[key] = str(path.parent / config[key])
    return config


def create_certificate(home):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = home / "server.crt", home / "server.key"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                           x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def mysql_executable():
    candidates = [os.environ.get("RESTAURANT_MYSQLD"), shutil.which("mysqld"),
                  r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("未找到 MySQL 8.0。请安装 MySQL Server，或设置 RESTAURANT_MYSQLD 为 mysqld.exe 路径。")


def _run_sql(cursor, path):
    source = "\n".join(line for line in Path(path).read_text(encoding="utf-8").splitlines()
                       if not line.lstrip().startswith("--"))
    for statement in source.split(";"):
        if statement.strip():
            cursor.execute(statement)


def initialize_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()")
        count = cursor.fetchone()[0]
        if count == 0:
            _run_sql(cursor, resources() / "sql" / "schema.sql")
        elif count != 7:
            raise RuntimeError("数据库初始化不完整。请保留现有目录，指定新的 RESTAURANT_HOME 重新初始化。")
        cursor.execute("SELECT COUNT(*) FROM employee")
        if cursor.fetchone()[0] == 0:
            _run_sql(cursor, resources() / "sql" / "seed.sql")
    connection.commit()


class DemoEnvironment:
    """只启动专用目录、专用端口的 MySQL，关闭时优雅停止本次启动的进程。"""

    def __init__(self, home=None):
        self.home = Path(home or runtime_home())
        self.process = None
        self.config = None

    def start(self):
        self.home.mkdir(parents=True, exist_ok=True)
        exe = mysql_executable()
        datadir = self.home / "mysql-data"
        secrets_path = self.home / "credentials.json"
        if secrets_path.exists():
            credentials = json.loads(secrets_path.read_text(encoding="utf-8"))
        else:
            credentials = {"root_password": secrets.token_urlsafe(24), "app_password": secrets.token_urlsafe(24)}
            secrets_path.write_text(json.dumps(credentials), encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if not (datadir / "mysql").exists():
            result = subprocess.run([exe, "--no-defaults", "--initialize-insecure", f"--datadir={datadir}"],
                                    capture_output=True, creationflags=flags)
            if result.returncode:
                raise RuntimeError("MySQL初始化失败\n" + result.stderr.decode("utf-8", errors="replace")[-1500:])
        config_path = self.home / "config.local.json"
        cert, key = create_certificate(self.home / "certs")
        self.config = {"host": "127.0.0.1", "port": 18765, "server_hostname": "localhost",
                       "db_host": "127.0.0.1", "db_port": 13306, "db_name": "restaurant",
                       "db_user": "restaurant_app", "db_password": credentials["app_password"],
                       "cert_file": str(cert), "key_file": str(key), "log_file": str(self.home / "server.log")}
        log = self.home / "mysql-error.log"
        args = [exe, "--no-defaults", f"--datadir={datadir}", "--port=13306", "--bind-address=127.0.0.1",
                "--mysqlx=OFF", "--max-connections=40", "--innodb-buffer-pool-size=67108864",
                f"--log-error={log}", "--default-time-zone=+08:00"]
        self.process = subprocess.Popen(args, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connection = None
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError("专用数据库启动失败，可能端口13306被占用。日志位于 " + str(log))
            for password in (credentials["root_password"], ""):
                try:
                    connection = pymysql.connect(host="127.0.0.1", port=13306, user="root", password=password,
                                                 charset="utf8mb4", connect_timeout=1)
                    break
                except pymysql.Error:
                    pass
            if connection:
                break
            time.sleep(0.2)
        if connection is None:
            self.close()
            raise RuntimeError("数据库启动超时，请查看 " + str(log))
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT @@datadir")
                actual_data = Path(cursor.fetchone()[0]).resolve()
                if self.process.poll() is not None or actual_data != datadir.resolve():
                    raise RuntimeError("端口13306正在被其他数据库使用，请关闭冲突实例后重试。")
                cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (credentials["root_password"],))
                cursor.execute("CREATE DATABASE IF NOT EXISTS restaurant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cursor.execute("CREATE USER IF NOT EXISTS 'restaurant_app'@'localhost' IDENTIFIED BY %s", (credentials["app_password"],))
                cursor.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON restaurant.* TO 'restaurant_app'@'localhost'")
                cursor.execute("USE restaurant")
            initialize_schema(connection)
            config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            self.close()
            raise
        finally:
            connection.close()
        return self.config

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                credentials = json.loads((self.home / "credentials.json").read_text(encoding="utf-8"))
                connection = pymysql.connect(host="127.0.0.1", port=13306, user="root", password=credentials["root_password"],
                                             connect_timeout=2)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT @@datadir")
                    if Path(cursor.fetchone()[0]).resolve() == (self.home / "mysql-data").resolve():
                        cursor.execute("SHUTDOWN")
                connection.close()
                self.process.wait(timeout=15)
            except (pymysql.Error, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=10)
        self.process = None
