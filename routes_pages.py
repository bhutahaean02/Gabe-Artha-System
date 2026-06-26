from flask import Blueprint, render_template, request, redirect, session, flash, jsonify, send_file, send_from_directory
from db import get_db_connection
import re
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import HTTPException
import os

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

@pages_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Jika sudah login, langsung skip ke halaman masing-masing
    if 'user_id' in session:
        return redirect('/') if session.get('role') != 'Anggota' else redirect('/dashboard_anggota')
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
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
                WHERE no_anggota = %s OR email = %s OR nama_anggota = %s
            """, (username, username, username))
            anggota = cursor.fetchone()
            if anggota:
                # Jika password ada dan berupa hash, kita cek. Bila menggunakan ID sementara saat pembuatan, bandingkan.
                # PERBAIKAN KEAMANAN: Menghapus fallback login menggunakan no_anggota sebagai password.
                # Anggota harus login menggunakan password yang sudah di-hash.
                if anggota['password'] and check_password_hash(anggota['password'], password):
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
            
        except Exception as e:
            flash(f"Terjadi Kesalahan Sistem (Bug/Error): {str(e)}", "danger")
        finally: 
            if 'cursor' in locals() and cursor: cursor.close()
            if 'conn' in locals() and conn: conn.close()
            
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

@pages_bp.route('/laporan_tunggakan_multiguna')
def laporan_tunggakan_multiguna():
    return render_template('laporan_tunggakan_multiguna.html')

@pages_bp.route('/laporan_tunggakan_urgent')
def laporan_tunggakan_urgent():
    return render_template('laporan_tunggakan_urgent.html')

# TAMBAHKAN KODE INI UNTUK HALAMAN MONITORING JMO/BPJS
@pages_bp.route('/monitoring_jmo')
def monitoring_jmo():
    return render_template('monitoring_jmo.html')

@pages_bp.route('/monitoring_lokasi')
def monitoring_lokasi():
    return render_template('monitoring_lokasi.html')

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

@pages_bp.route('/audit_logs')
def audit_logs():
    return render_template('audit_logs.html')

@pages_bp.route('/dashboard_anggota')
def dashboard_anggota():
    return render_template('dashboard_anggota.html')

@pages_bp.route('/alldata')
def alldata():
    return render_template('alldata.html')

@pages_bp.route('/anggota_lunas')
def anggota_lunas():
    return render_template('anggota_lunas.html')

@pages_bp.route('/panduan')
def panduan():
    return render_template('panduan.html')

@pages_bp.route('/convert_pdf')
def convert_pdf():
    return render_template('convert_pdf.html')

@pages_bp.route('/js/<path:filename>')
def serve_js_from_root(filename):
    """Menyajikan file JS dari direktori root proyek."""
    # Direktori root proyek adalah folder 'GAS', tempat file ini berada.
    project_root = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(project_root, filename)