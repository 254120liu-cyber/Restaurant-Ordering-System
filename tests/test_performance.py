"""可选的60秒真实 TLS 混合负载，运行结果保存到 reports/performance.json。"""

import json
import math
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import submit_order, serve_order
from restaurant.client import TcpClient
from restaurant.server import RestaurantServer


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RESTAURANT_RUN_PERFORMANCE") != "1", reason="设置 RESTAURANT_RUN_PERFORMANCE=1 运行60秒性能测试")
def test_ten_clients_ten_requests_per_second(system, mysql_environment):
    call, _, router, _ = system
    config = dict(mysql_environment[0])
    server = RestaurantServer(config, router)
    config["port"] = server.address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = []
    samples, errors, counts = [], [], {}
    reference = submit_order(call, table_id=2)
    serve_order(call, reference)
    try:
        for username in ["waiter"] * 3 + ["kitchen"] * 3 + ["cashier"] * 4:
            client = TcpClient(config)
            client.request("login", {"username": username, "password": "Demo@12345"})
            clients.append(client)
        current = quote = None
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=10) as pool:
            for second in range(60):
                delay = start + second - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                phase = second % 3
                if phase == 0:
                    if current:
                        call("waiter", "clear_table", {"table_id": 1})
                    call("waiter", "open_table", {"table_id": 1})
                elif phase == 1:
                    quote = serve_order(call, current)
                jobs = [("list_dishes", {})] * 3 + [("list_kitchen_orders", {"page_size": 10})] * 3 + [
                    ("get_order_status", {"order_id": reference["order_id"]})] * 4
                if phase == 0:
                    jobs[0] = ("submit_order", {"table_id": 1, "items": [{"dish_id": 1, "quantity": 1}]})
                if phase == 2:
                    jobs[6] = ("settle_bill", {"order_id": current["order_id"], "quote_version": quote["quote_version"],
                                               "paid_amount": "28.00", "pay_method": "扫码"})
                def invoke(index):
                    action, data = jobs[index]
                    before = time.perf_counter()
                    try:
                        result = clients[index].request(action, data)
                        return action, (time.perf_counter() - before) * 1000, result, None
                    except Exception as exc:
                        return action, (time.perf_counter() - before) * 1000, None, str(exc)
                results = list(pool.map(invoke, range(10)))
                for action, latency, result, error in results:
                    samples.append(latency)
                    counts[action] = counts.get(action, 0) + 1
                    if error:
                        errors.append(error)
                    if action == "submit_order" and result:
                        current = result
            delay = start + 60 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        elapsed = time.monotonic() - start
        ordered = sorted(samples)
        report = {"clients": 10, "duration_seconds": round(elapsed, 3), "requests": len(samples),
                  "throughput_rps": round(len(samples) / elapsed, 3), "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 3),
                  "maximum_ms": round(max(samples), 3), "error_count": len(errors), "operations": counts,
                  "scope": "Windows本机回环网络，MySQL8.0，登录和测试数据准备不计入600次请求"}
        Path("reports").mkdir(exist_ok=True)
        Path("reports/performance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert not errors, errors
        assert max(samples) <= 1000, report
    finally:
        for client in clients:
            client.close()
        server.close()
        thread.join(timeout=2)
