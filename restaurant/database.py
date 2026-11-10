"""有限连接池，线程独立事务上下文与参数化 SQL。"""

from contextlib import contextmanager
from queue import Queue, Empty, Full
from threading import BoundedSemaphore, local

import pymysql

from restaurant.domain import BusinessError


class DatabaseHelper:
    def __init__(self, config, pool_size=16):
        self.config = config
        self._pool = Queue(maxsize=pool_size)
        self._slots = BoundedSemaphore(pool_size)
        self._local = local()

    def _connect(self):
        c = self.config
        return pymysql.connect(host=c["db_host"], port=c["db_port"], user=c["db_user"],
                               password=c["db_password"], database=c["db_name"], charset="utf8mb4",
                               cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                               connect_timeout=3, read_timeout=10, write_timeout=10,
                               init_command="SET SESSION innodb_lock_wait_timeout=3, time_zone='+08:00'")

    @contextmanager
    def scope(self, readonly=False):
        """写事务 READ COMMITTED，预览用 REPEATABLE READ 一致快照。"""
        if not self._slots.acquire(timeout=3):
            raise BusinessError(503, "数据库繁忙，请稍后查询状态")
        connection = None
        healthy = True
        try:
            try:
                connection = self._pool.get_nowait()
                connection.ping(reconnect=True)
            except Empty:
                connection = self._connect()
            self._local.connection = connection
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL " +
                               ("REPEATABLE READ" if readonly else "READ COMMITTED"))
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" if readonly
                               else "START TRANSACTION")
            yield connection
            connection.commit()
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except pymysql.Error:
                    healthy = False
            raise
        finally:
            self._local.connection = None
            if connection is not None:
                if healthy:
                    try:
                        self._pool.put_nowait(connection)
                    except Full:
                        connection.close()
                else:
                    connection.close()
            self._slots.release()

    def transaction(self, work, readonly=False):
        with self.scope(readonly) as connection:
            return work(connection)

    def query(self, sql, args=(), one=False):
        with self._local.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchone() if one else list(cursor.fetchall())

    def execute(self, sql, args=()):
        with self._local.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.lastrowid

    def close(self):
        while not self._pool.empty():
            self._pool.get_nowait().close()
