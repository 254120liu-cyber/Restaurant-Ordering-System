-- 仅供课程演示，四个账号初始密码均为 Demo@12345。正式使用请修改密码。
INSERT INTO employee(username,password,name,role) VALUES('admin','scrypt$16384$8$1$+I8j9FKfbZNluKJ92dr/Tw==$wUFG6F7hk7uqFNK8F2eXe5E+rxi33HJalpTYXsw3T7w=','系统管理员','管理员');
INSERT INTO employee(username,password,name,role) VALUES('waiter','scrypt$16384$8$1$UGpertywQhPydHKAxsvj2w==$5+7Oi9jQIg3qclDcducB2t4+YQFOCzBckvgbiKvrpLM=','服务员小王','服务员');
INSERT INTO employee(username,password,name,role) VALUES('kitchen','scrypt$16384$8$1$PTp3aSUoNL1L+KEaj3Oebg==$wgBryqSPSyZs3fQDpcMD36REycl6rTW0hJ8XoIZgIms=','后厨小李','后厨');
INSERT INTO employee(username,password,name,role) VALUES('cashier','scrypt$16384$8$1$WY4r5LPu4nQPdKy7UJCGhg==$wpAuKac0m63DQzyIzFdgd/Jz1xaPRWlECjlWby+R+Dc=','收银员小张','收银员');
INSERT INTO dish_category(category_id,category_name) VALUES(1,'热菜'),(2,'凉菜'),(3,'主食'),(4,'饮品');
INSERT INTO dish(dish_id,category_id,dish_name,price,description) VALUES (1,1,'宫保鸡丁',28.00,'微辣，可备注少辣'),(2,1,'鱼香肉丝',26.00,'经典下饭菜'),(3,1,'番茄炒蛋',18.00,'家常菜'),(4,2,'凉拌黄瓜',12.00,'清爽开胃'),(5,3,'米饭',3.00,'每碗'),(6,4,'酸梅汤',8.00,'每杯');
INSERT INTO dining_table(table_no,seats) VALUES ('A01',4),('A02',4),('A03',4),('A04',6),('A05',6),('A06',8),('B01',2),('B02',2),('B03',4),('B04',4),('B05',6),('B06',8);
