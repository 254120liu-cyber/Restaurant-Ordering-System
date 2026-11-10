"""集成测试使用专用测试库，清理仅限本次创建的 restaurant_test_* 数据库。"""

import json
import os
from pathlib import Path
import uuid

import pymysql
import pytest

from restaurant.bootstrap import DemoEnvironment, initialize_schema, _run_sql, resources
from restaurant.database import DatabaseHelper
from restaurant.router import RequestRouter


@pytest.fixture(scope="session")
def mysql_environment():
    if not os.environ.get("RESTAURANT_TEST_HOME"):
        pytest.skip("设置 RESTAURANT_TEST_HOME 后运行真实 MySQL 集成测试")
    environment = DemoEnvironment(os.environ["RESTAURANT_TEST_HOME"])
    config = environment.start()
    credentials = json.loads((environment.home / "credentials.json").read_text(encoding="utf-8"))
    root = pymysql.connect(host="127.0.0.1", port=13306, user="root", password=credentials["root_password"], charset="utf8mb4")
    name = "restaurant_test_" + uuid.uuid4().hex[:10]
    try:
        with root.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
            cursor.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{name}`.* TO 'restaurant_app'@'localhost'")
            cursor.execute(f"USE `{name}`")
        initialize_schema(root)
        yield {**config, "db_name": name, "port": 0}, root
    finally:
        with root.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
        root.close()
        environment.close()


@pytest.fixture
def system(mysql_environment):
    config, root = mysql_environment
    with root.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for name in ("bill", "order_item", "orders", "dining_table", "dish", "dish_category", "employee"):
            cursor.execute(f"TRUNCATE TABLE `{name}`")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        _run_sql(cursor, resources() / "sql" / "seed.sql")
    root.commit()
    db = DatabaseHelper(config)
    router = RequestRouter(db)
    sessions = {}
    for username in ("waiter", "kitchen", "cashier", "admin"):
        session = {}
        response = router.dispatch(session, {"type": "login", "request_id": "login-" + username,
                                            "data": {"username": username, "password": "Demo@12345"}})
        assert response["code"] == 0
        sessions[username] = session
    def call(role, action, data=None, code=0):
        response = router.dispatch(sessions.get(role, {}), {"type": action, "request_id": uuid.uuid4().hex, "data": data or {}})
        assert response["code"] == code, response
        return response["data"]
    yield call, db, router, sessions
    db.close()


def submit_order(call, items=None, table_id=1):
    call("waiter", "open_table", {"table_id": table_id})
    return call("waiter", "submit_order", {"table_id": table_id, "items": items or [{"dish_id": 1, "quantity": 2}, {"dish_id": 5, "quantity": 2}]})


def serve_order(call, order):
    oid = order["order_id"]
    call("kitchen", "accept_order", {"order_id": oid})
    for item in order["order_items"]:
        data = {"order_id": oid, "item_id": item["item_id"]}
        call("kitchen", "start_item", data)
        call("kitchen", "mark_served", data)
    return call("cashier", "preview_bill", {"order_id": oid})
