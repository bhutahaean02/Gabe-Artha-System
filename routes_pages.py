from flask import Blueprint, render_template, request, redirect, session, flash
from db import get_db_connection
import re

# BARIS INILAH YANG DICARI OLEH app.py (pages_bp)
pages_bp = Blueprint('pages', __name__)

@pages_bp.before_request
def check_auth():
    # Route yang dikecualikan dari wajib login HANYA halaman Login dan file statis
    if request.path == '/login' or request.path.startswith('/static'):
        return
        
    # Cek apakah user sudah punya sesi login
    if 'user_id' not in session:
        # Jika request mengarah ke API, berikan response JSON Unauthorized (HTTP 401)
        if request.path.startswith('/api/'):
            return {"status": "error", "message": "Unauthorized: Anda harus login untuk melakukan aksi ini."}, 401
        return redirect('/login')
        
    # Pembatasan Akses Berdasarkan Role (Hak Akses)
    role = session.get('role')
    path = request.path
    
    # Jika Anggota mencoba masuk ke menu Admin, paksa lempar ke dashboardnya sendiri
    if role == 'Anggota' and path != '/dashboard_anggota' and path != '/logout':
        return redirect('/dashboard_anggota')

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
            cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
            user = cursor.fetchone()
            if user:
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
                    # Timpa username di session dengan nama pendek agar UI langsung berubah
                    'username': nama_final, 
                    'nama': nama_final, 
                    'nama_lengkap': nama_final, 
                    'role': user['role'], 
                    'cabang': user.get('cabang', 'GAS')
                })
                return redirect('/')
                
            # Cek 2: Cari di tabel Nasabah (Anggota) menggunakan Nama dan No Anggota
            # Fleksibel: Username bisa diisi Nama dan Password diisi No Anggota, atau sebaliknya.
            cursor.execute("""
                SELECT no_anggota, nama_anggota, cabang FROM identitas 
                WHERE (nama_anggota = %s AND no_anggota = %s) OR (no_anggota = %s AND nama_anggota = %s)
            """, (username, password, username, password))
            anggota = cursor.fetchone()
            if anggota:
                session.update({
                    'user_id': anggota['no_anggota'], 
                    # Timpa juga untuk anggota agar konsisten
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