from flask import Flask, jsonify, request, session, redirect, flash
import os, re
from decimal import Decimal
from datetime import date, datetime

# Import Blueprint yang sudah dibuat dari file lain
from routes_pages import pages_bp
from api_anggota import api_anggota_bp
from api_transaksi import api_transaksi_bp
from api_migrasi import api_migrasi_bp

# Import Blueprint Baru Hasil Pemecahan
from api_akuntansi import api_akuntansi_bp
from api_laporan import api_laporan_bp
from api_cetak import api_cetak_bp
from config import SECRET_KEY
from db import close_db_connection, init_db
import traceback
from werkzeug.exceptions import HTTPException

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
app.register_blueprint(api_migrasi_bp)

# Daftarkan Blueprint Baru
app.register_blueprint(api_akuntansi_bp)
app.register_blueprint(api_laporan_bp)
app.register_blueprint(api_cetak_bp)

# Daftarkan fungsi teardown untuk menutup DB otomatis setelah request selesai (menghindari memory leak)
app.teardown_appcontext(close_db_connection)

# Inisialisasi database satu kali saat aplikasi berjalan (menghapus beban DDL di API backend)
init_db(app)

# === GLOBAL AUTHENTICATION & AUTHORIZATION CHECK ===
# Fungsi ini sekarang akan berjalan sebelum SETIAP request ke server.
@app.before_request
def check_auth():
    # Route yang dikecualikan dari wajib login HANYA halaman Login dan file statis
    if request.path == '/login' or request.path.startswith('/static'):
        return
        
    # Cek apakah user sudah punya sesi login
    if 'user_id' not in session:
        # Jika request mengarah ke API, berikan response JSON Unauthorized (HTTP 401)
        if request.path.startswith('/api/'):
            return jsonify({"status": "error", "message": "Unauthorized: Anda harus login."}), 401
        return redirect('/login')
        
    # Pembatasan Akses Berdasarkan Role (Hak Akses)
    role = session.get('role')
    path = request.path
    
    # === PENCEGAHAN CROSSED-SESSION & AKSES ILEGAL ===
    if role == 'Anggota':
        allowed_api = ['/api/anggota/me/detail', '/api/update_jmo', '/api/download_berkas/']
        if path != '/dashboard_anggota' and path != '/logout':
            if path.startswith('/api/'):
                if not any(path.startswith(api) for api in allowed_api):
                    return jsonify({"status": "error", "message": "Akses ditolak. Sesi Anda telah berubah menjadi Anggota."}), 403
            else:
                return """
                <div style="text-align:center; margin-top:100px; font-family:sans-serif;">
                    <h1 style="color:red;">Akses Ditolak (Sesi Menyilang)</h1>
                    <p>Browser mendeteksi ada login <b>Anggota</b> yang sedang aktif (mungkin di Tab lain).</p>
                    <p>Sistem mencegah Anda membuka menu Admin demi keamanan data.</p>
                    <br>
                    <a href='/dashboard_anggota' style="padding:10px 20px; background:#0d6efd; color:white; text-decoration:none; border-radius:5px;">Ke Dashboard Anggota</a>
                    <br><br><br>
                    <a href='/logout' style="color:red; text-decoration:underline;">Logout untuk mereset sesi</a>
                </div>
                """, 403
    else:
        # Jika Admin/Manager mencoba masuk ke halaman anggota
        if path == '/dashboard_anggota':
            flash('Anda sedang login sebagai Admin. Tidak bisa mengakses halaman anggota.', 'info')
            return redirect('/')

# === GLOBAL ERROR HANDLER ===
# Memastikan semua unhandled exception (termasuk di API blueprints) mengembalikan format yang benar
@app.errorhandler(Exception)
def handle_all_exceptions(e):
    # Biarkan error HTTP standar (seperti 404, 405) ditangani secara default oleh Flask
    if isinstance(e, HTTPException):
        return e
        
    error_msg = str(e)
    trace = traceback.format_exc()
    
    # Jika error terjadi saat memanggil API di latar belakang (fetch), kembalikan JSON
    if request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': error_msg, 'trace': trace}), 500
        
    # Jika error terjadi saat memuat Halaman HTML, tampilkan Layar Error Beranimasi
    html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Terjadi Kesalahan Sistem</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body {{ background-color: #F5F7FA; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
            .error-card {{ background: white; border-radius: 16px; box-shadow: 0 15px 35px rgba(220, 53, 69, 0.15); max-width: 800px; width: 90%; padding: 40px; animation: slideUp 0.5s ease; border-top: 5px solid #dc3545; }}
            @keyframes slideUp {{ from {{ opacity: 0; transform: translateY(30px); }} to {{ opacity: 1; transform: translateY(0); }} }}
            .icon-container {{ font-size: 5rem; color: #dc3545; margin-bottom: 20px; animation: pulse 2s infinite; }}
            @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.05); }} 100% {{ transform: scale(1); }} }}
            .traceback-box {{ background: #212529; color: #00ff00; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85rem; max-height: 300px; overflow-y: auto; text-align: left; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="error-card text-center">
            <div class="icon-container"><i class="fa-solid fa-triangle-exclamation"></i></div>
            <h2 class="fw-bold text-dark">Oops! Terjadi Kesalahan Sistem</h2>
            <p class="text-muted">Sistem mendeteksi adanya bug atau error pada server saat memuat halaman ini.</p>
            <div class="alert alert-danger fw-bold">{error_msg}</div>
            <button class="btn btn-outline-danger mt-3 shadow-sm" type="button" data-bs-toggle="collapse" data-bs-target="#tracebackCollapse"><i class="fa-solid fa-bug me-1"></i> Lihat Detail Bug (Untuk Tim IT)</button>
            <a href="/" class="btn btn-primary mt-3 ms-2 shadow-sm"><i class="fa-solid fa-home me-1"></i> Kembali ke Beranda</a>
            <div class="collapse mt-3" id="tracebackCollapse">
                <div class="traceback-box">{trace}</div>
            </div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return html_content, 500

if __name__ == '__main__':
    # Tambahkan host='0.0.0.0' agar server listen ke semua IP (bukan hanya localhost)
    # Port 5000 ditambahkan secara eksplisit sebagai standar Flask
    # PERHATIAN: debug=True tidak boleh digunakan di lingkungan produksi karena alasan keamanan.
    app.run(host='0.0.0.0', port=5000, debug=True)