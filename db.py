import mysql.connector
from config import DB_CONFIG

# Fungsi terpusat untuk memanggil koneksi database
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)