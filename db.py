import mysql.connector
from flask import g
from config import DB_CONFIG

def get_db_connection():
    """Mengambil koneksi database yang unik untuk setiap request (disimpan di objek g Flask)."""
    if 'db' not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db

def close_db_connection(e=None):
    """Menutup koneksi database secara otomatis di akhir request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()