# 餐馆点菜系统

课程设计第六、七天实现，覆盖 FR-01～FR-14。采用 Python 3.10、PyQt5、TCP/TLS 和 MySQL 8.0，提供服务员、后厨、收银员和管理员四种界面。

## 单机演示

1. Windows 10/11 安装 MySQL Server 8.0.16 或以上的8.0版本。本机验证版本为8.0.31。
2. 双击交付包“可运行软件”中的 RestaurantOrdering.exe，保持其与 _internal 文件夹相邻。
3. 首次启动创建专用数据库，等待工作台入口出现。打开各角色窗口并登录。
4. 数据默认保存在程序目录下 .runtime/demo，程序放在E盘时数据也在E盘。默认数据库端口13306，业务端口18765。
5. 关闭启动器会停止本次服务，数据库内容保留。一个启动器可同时打开多个角色窗口。

MySQL安装位置不是 C:/Program Files/MySQL/MySQL Server 8.0/bin/mysqld.exe 时，设置环境变量 RESTAURANT_MYSQLD 指向实际 mysqld.exe。演示实例使用独立目录、随机数据库凭据和低权限应用账号。

| 角色 | 账号 | 初始演示密码 |
| --- | --- | --- |
| 服务员 | waiter | Demo@12345 |
| 后厨 | kitchen | Demo@12345 |
| 收银员 | cashier | Demo@12345 |
| 管理员 | admin | Demo@12345 |

账号仅供课程演示，密码以带随机盐的scrypt派生结果保存。扫码与刷卡由收银员登记现场收款结果。

## 五分钟演示流程

1. 服务员选择A01并开台，重新选择A01。选择宫保鸡丁、数量2，加入草稿并提交，记下订单号。
2. 后厨刷新订单，选择订单并接单。重新选择订单和菜品，开始制作，再选择并标记出菜。
3. 收银员输入订单号并预览，应收56.00元。选择现金、实收100.00元，确认后显示找零44.00元。
4. 查询订单与收款结果，确认账单号和已结账状态。
5. 服务员刷新桌台并清台，A01恢复空闲。
6. 管理员维护分类、菜品和员工。修改菜价后，已保存订单保留原单价。

## 源码启动

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe main.py demo
```

统一使用Python 3.10。requirements.txt固定运行依赖，requirements-dev.txt加入开发工具，requirements-lock.txt固定本次验证的完整开发依赖。

独立部署使用 main.py server --config config.local.json 和 main.py client --config client.local.json。客户端配置只需host、port、server_hostname、cert_file，路径可相对配置文件。手动部署时先在空数据库中执行sql/schema.sql和sql/seed.sql。单机演示模式自动完成初始化。

## 测试与打包

```powershell
.venv/Scripts/python.exe -m pytest tests/test_domain.py -q
$env:RESTAURANT_TEST_HOME="$PWD/.runtime/qa-mysql"
$env:QT_QPA_PLATFORM="offscreen"
$env:RESTAURANT_RUN_PERFORMANCE="1"
.venv/Scripts/python.exe -m pytest -q --cov=restaurant --cov-report=json:reports/coverage.json --junitxml=reports/test-results.xml
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

测试会创建并清理本次随机命名的restaurant_test_*测试库。测试使用13306端口，执行前关闭演示启动器。性能测试需设置RESTAURANT_RUN_PERFORMANCE=1，持续60秒。

## 项目结构

- restaurant/gui.py实现四角色界面，网络请求在后台QThread执行。
- client.py、protocol.py、server.py实现TLS连接、JSON行协议与连接会话。
- router.py负责授权、分发和异常返回，services.py与domain.py实现业务。
- database.py负责连接池、参数化SQL与事务，bootstrap.py负责单机初始化。
- sql/包含7张表与演示数据，tests/包含单元、数据库、网络、界面及性能测试。
- docs/包含开发文档、接口说明与协作安排，reports/保存实际测试数据。

## 协作记录

WangYu负责当前编码、集成和自动测试。其他四位成员按docs/协作与验收.md完成真实验收与修改，使用各自Git身份提交。合并后重新导出git-log.txt。

虚拟环境、数据库、私钥、私人配置和构建产物由.gitignore排除，可运行软件单独交付。
