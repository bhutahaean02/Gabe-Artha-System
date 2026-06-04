from flask import Flask
import os
from decimal import Decimal
from datetime import date, datetime

# Import Blueprint yang sudah dibuat dari file lain
from routes_pages import pages_bp
from api_anggota import api_anggota_bp
from api_transaksi import api_transaksi_bp
from api_akuntansi_laporan import api_akuntansi_laporan_bp
from api_migrasi import api_migrasi_bp
from config import SECRET_KEY
from db import close_db_connection, init_db

app = Flask(__name__)

# === GLOBAL JSON SERIALIZER FIX ===
# Menangani konversi tipe Decimal dan Date secara otomatis untuk seluruh aplikasi (jsonify)
try:
    # Untuk Flask versi modern (2.2 ke atas)
    from flask.json.provider import DefaultJSONProvider
    class CustomJSONProvider(DefaultJSONProvider):
        def default(self, obj):
            if isinstance(obj, Decimal): return float(obj)
            if isinstance(obj, (date, datetime)): return obj.isoformat()
            return super().default(obj)
    app.json = CustomJSONProvider(app)
except ImportError:
    # Untuk fallback jika menggunakan Flask versi lama
    import json
    class CustomJSONEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal): return float(obj)
            if isinstance(obj, (date, datetime)): return obj.isoformat()
            return super().default(obj)
    app.json_encoder = CustomJSONEncoder
# ==================================

# Konfigurasi Secret Key untuk sesi login dan keamanan Flask
app.config['SECRET_KEY'] = SECRET_KEY

# Memastikan folder penyimpanan gambar/logo dan upload berkas tersedia
os.makedirs(os.path.join(os.getcwd(), 'static', 'img'), exist_ok=True)
os.makedirs(os.path.join(os.getcwd(), 'uploads', 'berkas_anggota'), exist_ok=True)

# Daftarkan (Register) Blueprint ke dalam aplikasi Flask
app.register_blueprint(pages_bp)
app.register_blueprint(api_anggota_bp)
app.register_blueprint(api_transaksi_bp)
app.register_blueprint(api_akuntansi_laporan_bp)
app.register_blueprint(api_migrasi_bp)

# Daftarkan fungsi teardown untuk menutup DB otomatis setelah request selesai (menghindari memory leak)
app.teardown_appcontext(close_db_connection)

# Inisialisasi database satu kali saat aplikasi berjalan (menghapus beban DDL di API backend)
init_db(app)

if __name__ == '__main__':
    # Tambahkan host='0.0.0.0' agar server listen ke semua IP (bukan hanya localhost)
    # Port 5000 ditambahkan secara eksplisit sebagai standar Flask
    app.run(host='0.0.0.0', port=5000, debug=True)