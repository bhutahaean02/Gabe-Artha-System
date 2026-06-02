from flask import Blueprint, render_template, request, redirect, session, flash, jsonify
from db import get_db_connection
import re
from werkzeug.security import check_password_hash

# BARIS INILAH YANG DICARI OLEH app.py (pages_bp)
pages_bp = Blueprint('pages', __name__)

@pages_bp.after_app_request
def add_cache_control(response):
    # Mencegah browser menyimpan cache halaman HTML.
    # Ini sangat ampuh mencegah bug "Sesi Menyilang" akibat tombol 'Back' browser
    if 'text/html' in response.headers.get('Content-Type', ''):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@pages_bp.before_app_request
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
        allowed_api = ['/api/anggota/', '/api/update_jmo', '/api/download_berkas/']
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

@pages_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Jika sudah login, langsung skip ke halaman masing-masing
    if 'user_id' in session:
        return redirect('/') if session.get('role') != 'Anggota' else redirect('/dashboard_anggota')
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Cek 1: Cari di tabel Staff (Admin & Manager)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if user:
                # Catatan: Ini mengasumsikan password di tabel users sudah di-hash. 
                # Jika masih plain text (kondisi transisi), hapus baris pengecekan hash di bawah dan gunakan plain text sementara.
                if check_password_hash(user['password'], password) or user['password'] == password:
                    nama_user = user['nama_lengkap'] or user['username']
                
                    # 1. Hapus kata 'cabang'
                    nama_pendek = re.sub(r'(?i)\bcabang\b', '', nama_user)
                    # 2. Hapus teks di dalam kurung
                    nama_pendek = re.sub(r'\(.*?\)', '', nama_pendek)
                    # 3. Ubah simbol seperti strip (-) menjadi spasi agar pemisahan kata akurat
                    nama_pendek = re.sub(r'[^a-zA-Z0-9\s]', ' ', nama_pendek)
                    
                    # 4. Hilangkan kata terduplikasi
                    words = nama_pendek.split()
                    unique_words = []
                    for w in words:
                        if w.lower() not in [uw.lower() for uw in unique_words]:
                            unique_words.append(w)
                    # 5. Rapikan menjadi Huruf Kapital di awal (contoh: "Admin Cilegon")
                    nama_final = ' '.join(unique_words).title()

                    session.update({
                        'user_id': user['id'], 
                        'username': nama_final, 
                        'nama': nama_final, 
                        'nama_lengkap': nama_final, 
                        'role': user['role'], 
                        'cabang': user.get('cabang', 'GAS')
                    })
                    return redirect('/')
                
            # Cek 2: Cari di tabel Nasabah (Anggota) menggunakan No Anggota
            cursor.execute("""
                SELECT no_anggota, nama_anggota, password, cabang FROM identitas 
                WHERE no_anggota = %s OR email = %s
            """, (username, username))
            anggota = cursor.fetchone()
            if anggota:
                # Jika password ada dan berupa hash, kita cek. Bila menggunakan ID sementara saat pembuatan, bandingkan.
                is_valid = False
                if anggota['password'] and check_password_hash(anggota['password'], password):
                    is_valid = True
                elif password == anggota['no_anggota']:  # Fallback kalau belum pernah setup password
                    is_valid = True
                    
                if is_valid:
                    session.update({
                        'user_id': anggota['no_anggota'], 
                        'username': anggota['nama_anggota'], 
                        'nama': anggota['nama_anggota'],
                        'nama_lengkap': anggota['nama_anggota'],
                        'role': 'Anggota', 
                        'cabang': anggota.get('cabang', 'GAS')
                    })
                    return redirect('/dashboard_anggota')
                
            flash('Kredensial tidak valid! Periksa kembali Nama/Username dan Password/No Anggota Anda.', 'danger')
        finally: cursor.close(); conn.close()
    return render_template('login.html')

@pages_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@pages_bp.route('/')
def dashboard():
    return render_template('dashboard.html')

@pages_bp.route('/identitas')
def identitas():
    return render_template('identitas.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN MONITORING PINJAMAN
@pages_bp.route('/monitoring_pinjaman')
def monitoring_pinjaman():
    return render_template('monitoring_pinjaman.html')

# TAMBAHKAN KODE INI DI BAWAHNYA
@pages_bp.route('/pencairan')
def pencairan():
    return render_template('pencairan.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN DANA URGENT
@pages_bp.route('/pencairan_urgent')
def pencairan_urgent():
    return render_template('pencairan_urgent.html')
@pages_bp.route('/pembayaran')
def pembayaran():
    return render_template('pembayaran.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN SIMPANAN
@pages_bp.route('/simpanan')
def simpanan():
    return render_template('simpanan.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN PENGELUARAN OPERASIONAL
@pages_bp.route('/pengeluaran')
def pengeluaran():
    return render_template('pengeluaran.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN ASET OPERASIONAL
@pages_bp.route('/aset')
def aset():
    return render_template('aset.html')

@pages_bp.route('/buku_besar')
def buku_besar():
    return render_template('buku_besar.html')

@pages_bp.route('/laba_rugi')
def laba_rugi():
    return render_template('laba_rugi.html')

@pages_bp.route('/neraca')
def neraca():
    return render_template('neraca.html')

@pages_bp.route('/laporan_harian')
def laporan_harian():
    return render_template('laporan_harian.html')

@pages_bp.route('/arus_kas')
def arus_kas():
    return render_template('arus_kas.html')

@pages_bp.route('/realisasi_anggaran')
def realisasi_anggaran():
    return render_template('realisasi_anggaran.html')

@pages_bp.route('/cetak_berkas')
def cetak_berkas():
    return render_template('cetak_berkas.html')

@pages_bp.route('/approval')
def approval():
    return render_template('approval.html')

@pages_bp.route('/dashboard_anggota')
def dashboard_anggota():
    return render_template('dashboard_anggota.html')