-- MySQL 8.0.16+，请先选择一个新建的空数据库。数据库时区为 +08:00。
CREATE TABLE employee (
 employee_id INT PRIMARY KEY AUTO_INCREMENT,
 username VARCHAR(20) NOT NULL UNIQUE,
 password VARCHAR(128) NOT NULL,
 name VARCHAR(20) NOT NULL,
 role VARCHAR(10) NOT NULL,
 phone VARCHAR(20),
 create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 CHECK (role IN ('服务员','后厨','收银员','管理员'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dish_category (
 category_id INT PRIMARY KEY AUTO_INCREMENT,
 category_name VARCHAR(20) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dish (
 dish_id INT PRIMARY KEY AUTO_INCREMENT,
 category_id INT NOT NULL,
 dish_name VARCHAR(50) NOT NULL,
 price DECIMAL(8,2) NOT NULL,
 status VARCHAR(10) NOT NULL DEFAULT '在售',
 description VARCHAR(200),
 FOREIGN KEY (category_id) REFERENCES dish_category(category_id),
 INDEX idx_dish_category_status(category_id,status),
 CHECK (price >= 0),
 CHECK (status IN ('在售','下架'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE dining_table (
 table_id INT PRIMARY KEY AUTO_INCREMENT,
 table_no VARCHAR(10) NOT NULL UNIQUE,
 seats INT,
 status VARCHAR(10) NOT NULL DEFAULT '空闲',
 current_order_id INT UNIQUE,
 CHECK (status IN ('空闲','占用')),
 CHECK (seats IS NULL OR seats > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE orders (
 order_id INT PRIMARY KEY AUTO_INCREMENT,
 table_id INT NOT NULL,
 waiter_id INT NOT NULL,
 order_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 status VARCHAR(10) NOT NULL DEFAULT '已提交',
 total_price DECIMAL(8,2) NOT NULL,
 version INT NOT NULL DEFAULT 1,
 FOREIGN KEY (table_id) REFERENCES dining_table(table_id),
 FOREIGN KEY (waiter_id) REFERENCES employee(employee_id),
 INDEX idx_order_status_time(status,order_time),
 CHECK (status IN ('已提交','已接单','已结账')),
 CHECK (total_price >= 0),
 CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE dining_table ADD CONSTRAINT fk_table_current_order
 FOREIGN KEY (current_order_id) REFERENCES orders(order_id);
CREATE TABLE order_item (
 item_id INT PRIMARY KEY AUTO_INCREMENT,
 order_id INT NOT NULL,
 dish_id INT NOT NULL,
 quantity INT NOT NULL,
 price DECIMAL(8,2) NOT NULL,
 status VARCHAR(10) NOT NULL DEFAULT '待制作',
 FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
 FOREIGN KEY (dish_id) REFERENCES dish(dish_id),
 CHECK (quantity > 0), CHECK (price >= 0),
 CHECK (status IN ('待制作','制作中','已出菜'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE bill (
 bill_id INT PRIMARY KEY AUTO_INCREMENT,
 order_id INT NOT NULL UNIQUE,
 cashier_id INT NOT NULL,
 total_amount DECIMAL(8,2) NOT NULL,
 paid_amount DECIMAL(8,2) NOT NULL,
 pay_method VARCHAR(10) NOT NULL,
 pay_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
 FOREIGN KEY (cashier_id) REFERENCES employee(employee_id),
 CHECK (total_amount >= 0), CHECK (paid_amount >= total_amount),
 CHECK (pay_method IN ('现金','扫码','刷卡')),
 CHECK (pay_method='现金' OR paid_amount=total_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
