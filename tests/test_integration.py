"""真实 MySQL 事务、角色接口、并发结账与 TLS 协议集成测试。"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import socket
import ssl
import threading
import time

import pytest
import pymysql

from conftest import submit_order, serve_order
from restaurant.client import TcpClient
from restaurant.server import RestaurantServer
from restaurant.protocol import encode_frame, decode_frame, read_frame, MAX_FRAME

pytestmark = pytest.mark.integration


def test_complete_order_workflow(system):
    call, db, _, _ = system
    assert len(call("waiter", "list_tables")["tables"]) == 12
    order = submit_order(call)
    assert system[0]("kitchen", "list_kitchen_orders")["total"] == 1
    oid = order["order_id"]
    assert order["total_price"] == Decimal("62.00")
    call("waiter", "clear_table", {"table_id": 1}, code=409)
    call("cashier", "settle_bill", {"order_id": oid, "quote_version": 1, "paid_amount": "100.00", "pay_method": "现金"}, code=409)
    quote = serve_order(call, order)
    bill = call("cashier", "settle_bill", {"order_id": oid, "quote_version": quote["quote_version"], "paid_amount": "100.00", "pay_method": "现金"})
    assert bill["change_amount"] == Decimal("38.00")
    assert call("cashier", "get_order_status", {"order_id": oid})["bill"]["bill_id"] == bill["bill_id"]
    assert "bill" not in call("waiter", "get_order_status", {"order_id": oid})
    call("waiter", "add_item", {"order_id": oid, "dish_id": 2, "quantity": 1}, code=409)
    call("waiter", "remove_item", {"order_id": oid, "item_id": order["order_items"][0]["item_id"], "reason": "退菜"}, code=409)
    call("cashier", "preview_bill", {"order_id": oid}, code=409)
    table = call("waiter", "clear_table", {"table_id": 1})
    assert table["current_order_id"] is None
    assert call("cashier", "get_order_status", {"order_id": oid})["status"] == "已结账"


def test_failed_bill_write_rolls_back_order_and_bill(system, monkeypatch):
    call, db, _, _ = system
    order = submit_order(call)
    quote = serve_order(call, order)
    execute = db.execute
    def injected_failure(sql, args=()):
        if "SET status='已结账'" in sql:
            raise pymysql.OperationalError(1213, "injected deadlock after bill insert")
        return execute(sql, args)
    monkeypatch.setattr(db, "execute", injected_failure)
    call("cashier", "settle_bill", {"order_id": order["order_id"], "quote_version": quote["quote_version"],
                                    "paid_amount": "62.00", "pay_method": "现金"}, code=503)
    current = call("cashier", "get_order_status", {"order_id": order["order_id"]})
    assert current["bill"] is None and current["status"] == "已接单"
    assert current["version"] == quote["quote_version"]


def test_snapshot_price_add_remove_and_versions(system):
    call, _, _, _ = system
    order = submit_order(call)
    oid = order["order_id"]
    call("admin", "manage_dish", {"action": "update", "dish_id": 1, "fields": {"price": "30.00"}})
    added = call("waiter", "add_item", {"order_id": oid, "dish_id": 1, "quantity": 1})
    assert added["total_price"] == Decimal("92.00")
    assert added["order_items"][0]["price"] == Decimal("28.00")
    assert added["order_items"][-1]["price"] == Decimal("30.00")
    removed = call("waiter", "remove_item", {"order_id": oid, "item_id": added["order_items"][-1]["item_id"], "reason": "顾客调整数量"})
    assert removed["total_price"] == Decimal("62.00")
    assert removed["version"] == order["version"] + 2
    call("waiter", "remove_item", {"order_id": oid, "item_id": 9999, "reason": "测试"}, code=404)


def test_cannot_remove_last_or_started_item(system):
    call, _, _, _ = system
    order = submit_order(call, [{"dish_id": 1, "quantity": 1}])
    data = {"order_id": order["order_id"], "item_id": order["order_items"][0]["item_id"]}
    call("waiter", "remove_item", {**data, "reason": "最后一道"}, code=409)
    call("kitchen", "start_item", data, code=409)
    call("kitchen", "accept_order", {"order_id": order["order_id"]})
    call("kitchen", "mark_served", data, code=409)
    call("kitchen", "start_item", data)
    call("waiter", "remove_item", {**data, "reason": "已开做"}, code=409)
    call("kitchen", "start_item", data, code=409)
    call("kitchen", "mark_served", {**data, "item_id": 99999}, code=404)


def test_invalid_submit_rolls_back(system):
    call, db, _, _ = system
    call("waiter", "open_table", {"table_id": 1})
    call("waiter", "submit_order", {"table_id": 1, "items": [{"dish_id": 1, "quantity": 1}, {"dish_id": 9999, "quantity": 1}]}, code=404)
    assert db.transaction(lambda c: db.query("SELECT COUNT(*) n FROM orders", one=True))["n"] == 0
    assert call("waiter", "list_tables")["tables"][0]["current_order_id"] is None


def test_overflow_add_rolls_back(system):
    call, db, _, _ = system
    order = submit_order(call)
    call("waiter", "add_item", {"order_id": order["order_id"], "dish_id": 1, "quantity": 100000}, code=400)
    current = call("waiter", "get_order_status", {"order_id": order["order_id"]})
    assert current["version"] == order["version"] and len(current["items"]) == 2


def test_stale_quote_and_payment_validation(system):
    call, _, _, _ = system
    order = submit_order(call)
    old = call("cashier", "preview_bill", {"order_id": order["order_id"]})
    quote = serve_order(call, order)
    data = {"order_id": order["order_id"], "quote_version": old["quote_version"], "paid_amount": "62.00", "pay_method": "扫码"}
    call("cashier", "settle_bill", data, code=409)
    data["quote_version"] = quote["quote_version"]
    call("cashier", "settle_bill", {**data, "paid_amount": "1.00"}, code=400)
    call("cashier", "settle_bill", {**data, "paid_amount": "100.00"}, code=400)
    call("cashier", "settle_bill", {**data, "pay_method": "其他"}, code=400)
    call("cashier", "settle_bill", data)
    call("cashier", "settle_bill", data, code=409)


def test_concurrent_settlement_only_one_bill(system):
    call, db, router, sessions = system
    order = submit_order(call)
    quote = serve_order(call, order)
    barrier = threading.Barrier(2)
    def settle(index):
        barrier.wait()
        return router.dispatch(dict(sessions["cashier"]), {"type": "settle_bill", "request_id": f"race-{index}",
            "data": {"order_id": order["order_id"], "quote_version": quote["quote_version"], "paid_amount": "62.00", "pay_method": "刷卡"}})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(settle, range(2)))
    assert sorted(r["code"] for r in results) == [0, 409]
    assert db.transaction(lambda c: db.query("SELECT COUNT(*) n FROM bill WHERE order_id=%s", (order["order_id"],), one=True))["n"] == 1


def test_concurrent_first_submit_only_one_order(system):
    call, db, router, sessions = system
    call("waiter", "open_table", {"table_id": 1})
    barrier = threading.Barrier(2)
    def submit(index):
        barrier.wait()
        return router.dispatch(dict(sessions["waiter"]), {"type": "submit_order", "request_id": f"submit-{index}",
            "data": {"table_id": 1, "items": [{"dish_id": 1, "quantity": 1}]}})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    assert sorted(r["code"] for r in results) == [0, 409]


@pytest.mark.parametrize("role,action,data,code", [
    ("anonymous", "list_tables", {}, 401), ("waiter", "manage_employee", {"action": "list"}, 403),
    ("admin", "settle_bill", {}, 403), ("cashier", "open_table", {"table_id": 1}, 403),
    ("kitchen", "get_order_status", {"order_id": 1}, 403), ("waiter", "unknown", {}, 400),
    ("waiter", "open_table", {"table_id": True}, 400), ("waiter", "open_table", {"table_id": 9999}, 404),
    ("waiter", "create_order", {"table_id": 1}, 409), ("waiter", "clear_table", {"table_id": 1}, 409),
    ("waiter", "get_order_status", {"order_id": 9999}, 404),
])
def test_permissions_and_invalid_states(system, role, action, data, code):
    system[0](role, action, data, code=code)


def test_menu_and_category_crud(system):
    call, _, _, _ = system
    assert call("waiter", "list_dishes", {"keyword": "米饭", "category_id": 3})["total"] == 1
    assert call("waiter", "list_dishes", {"page": 2, "page_size": 100})["items"] == []
    category = call("admin", "manage_category", {"action": "create", "fields": {"category_name": "甜品"}})
    cid = category["category_id"]
    dish = call("admin", "manage_dish", {"action": "create", "fields": {"dish_name": "布丁", "price": "12.00", "category_id": cid, "description": "新品"}})
    call("admin", "manage_category", {"action": "delete", "category_id": cid}, code=409)
    call("admin", "manage_category", {"action": "update", "category_id": cid, "fields": {"category_name": "甜点"}})
    call("admin", "manage_dish", {"action": "update", "dish_id": dish["dish_id"], "fields": {"status": "下架"}})
    call("waiter", "open_table", {"table_id": 1})
    call("waiter", "submit_order", {"table_id": 1, "items": [{"dish_id": dish["dish_id"], "quantity": 1}]}, code=409)
    call("admin", "manage_dish", {"action": "delete", "dish_id": dish["dish_id"]})
    call("admin", "manage_category", {"action": "delete", "category_id": cid})
    assert call("admin", "manage_category", {"action": "list"})["total"] == 4
    assert call("admin", "manage_dish", {"action": "list"})["total"] == 6


def test_employee_crud_disable_and_password_reset(system):
    call, _, router, sessions = system
    created = call("admin", "manage_employee", {"action": "create", "fields": {"username": "new", "password": "Original123", "name": "新员工", "role": "服务员", "phone": "123456", "enabled": True}})
    eid = created["employee_id"]
    assert "password" not in created
    assert all("password" not in e for e in call("admin", "manage_employee", {"action": "list"})["items"])
    session = {}
    assert router.dispatch(session, {"type": "login", "request_id": "new", "data": {"username": "new", "password": "Original123"}})["code"] == 0
    call("admin", "manage_employee", {"action": "update", "employee_id": eid, "fields": {"enabled": False, "password": "Changed123"}})
    assert router.dispatch(session, {"type": "list_tables", "request_id": "disabled", "data": {}})["code"] == 401
    call("admin", "manage_employee", {"action": "update", "employee_id": eid, "fields": {"enabled": True}})
    assert router.dispatch(session, {"type": "login", "request_id": "old", "data": {"username": "new", "password": "Original123"}})["code"] == 401
    assert router.dispatch(session, {"type": "login", "request_id": "new", "data": {"username": "new", "password": "Changed123"}})["code"] == 0
    call("admin", "manage_employee", {"action": "delete", "employee_id": eid})
    call("admin", "manage_employee", {"action": "delete", "employee_id": sessions["admin"]["employee_id"]}, code=409)
    call("admin", "logout")
    call("admin", "manage_employee", {"action": "list"}, code=401)


@pytest.mark.parametrize("payload", [None, [], {}, {"request_id": "x\ny"}, {"request_id": "a", "type": [], "data": {}},
                                    {"request_id": "a", "type": "list_tables", "data": []}])
def test_bad_request_envelopes(system, payload):
    assert system[2].dispatch({}, payload)["code"] == 400


@pytest.mark.parametrize("entity,fields", [("dish", {"price": "-1.00"}), ("dish", {"status": "坏"}),
     ("dish", {"evil": 1}), ("category", {"category_name": ""}), ("employee", {"password": "123"}),
     ("employee", {"role": "超级管理员"}), ("employee", {"enabled": 1})])
def test_admin_validation(system, entity, fields):
    system[0]("admin", "manage_" + entity, {"action": "create", "fields": fields}, code=400)


def test_failure_rollback_and_error_mapping(system, monkeypatch):
    call, db, router, _ = system
    def fail(*args, **kwargs):
        raise pymysql.OperationalError(1213, "deadlock")
    monkeypatch.setattr(db, "transaction", fail)
    call("waiter", "list_tables", code=503)
    def unknown(*args, **kwargs):
        raise RuntimeError("internal secret")
    monkeypatch.setattr(db, "transaction", unknown)
    response = router.dispatch({}, {"type": "list_tables", "request_id": "failed", "data": {}})
    assert response["code"] == 500 and "internal secret" not in response["msg"]


def test_real_tls_fragmented_coalesced_and_reconnect(system, mysql_environment):
    _, _, router, _ = system
    config = dict(mysql_environment[0])
    server = RestaurantServer(config, router)
    config["port"] = server.address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = TcpClient(config)
    try:
        assert client.request("login", {"username": "waiter", "password": "Demo@12345"})["role"] == "服务员"
        assert len(client.request("list_tables", {})["tables"]) == 12
        client.close()
        with pytest.raises(Exception) as error:
            client.request("list_tables", {})
        assert error.value.code == 401
        client.close()
        context = ssl.create_default_context(cafile=config["cert_file"])
        with context.wrap_socket(socket.create_connection(server.address), server_hostname="localhost") as sock:
            stream = sock.makefile("rb")
            login = encode_frame({"type": "login", "request_id": "l", "data": {"username": "waiter", "password": "Demo@12345"}})
            query = encode_frame({"type": "list_tables", "request_id": "q", "data": {}})
            sock.sendall(login[:7])
            sock.sendall(login[7:] + query)
            assert decode_frame(read_frame(stream))["code"] == 0
            assert decode_frame(read_frame(stream))["request_id"] == "q"
            sock.sendall(b"bad\n")
            assert decode_frame(read_frame(stream))["code"] == 400
            sock.sendall(b"x" * (MAX_FRAME + 1))
            assert decode_frame(read_frame(stream))["code"] == 400
            stream.close()
        wrong = {**config, "server_hostname": "wrong-host.invalid"}
        with pytest.raises(ssl.SSLCertVerificationError):
            TcpClient(wrong).connect()
    finally:
        client.close()
        server.close()
        thread.join(timeout=2)
