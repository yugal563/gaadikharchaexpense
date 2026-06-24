import pymysql

def get_connection():
    return pymysql.connect(
        host="localhost",
        port=3307,
        user="root",
        password="1234",
        database="expenses",
        cursorclass=pymysql.cursors.DictCursor
    )