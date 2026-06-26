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

def init_db(app):
    """
    Menjalankan migrasi skema tabel sederhana satu kali saat aplikasi dinyalakan.
    CATATAN: Untuk pengembangan jangka panjang, sangat disarankan menggunakan alat migrasi
    seperti Flask-Migrate (Alembic) untuk manajemen skema yang lebih andal.
    """
    with app.app_context():
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. Pastikan tabel-tabel support tersedia
            cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
            cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
            cursor.execute("CREATE TABLE IF NOT EXISTS penanganan_macet (no_anggota VARCHAR(50) PRIMARY KEY, progres_marketing TEXT, solusi TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
            cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(100), role VARCHAR(50), cabang VARCHAR(50), aksi VARCHAR(255), detail TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            
            # 2. Migrasi Kolom (Multi-Cabang & EDC)
            try: cursor.execute("ALTER TABLE jurnal_umum ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            except: pass
            try: cursor.execute("ALTER TABLE pengeluaran_operasional ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN berkas_pdf VARCHAR(255)")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN marketing VARCHAR(100)")
            except: pass
            try: cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN berkas_jaminan TEXT")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN status_pernikahan VARCHAR(50)")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN alamat_penanggung_jawab TEXT")
            except: pass
            try: cursor.execute("ALTER TABLE identitas ADD COLUMN link_gmaps TEXT")
            except: pass
            
            # Kolom EDC & Sisa Gaji pada Tagihan
            try:
                cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'edc'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN edc VARCHAR(50) DEFAULT '-'")
                cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'sisa_gaji'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN sisa_gaji DECIMAL(15,2) DEFAULT 0.00")
                cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'gaji_awal'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN gaji_awal DECIMAL(15,2) DEFAULT 0.00")
                cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'simpanan_wajib_bayar'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN simpanan_wajib_bayar DECIMAL(15,2) DEFAULT 0.00")
                
                cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'edc'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN edc VARCHAR(50) DEFAULT '-'")
                cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'sisa_gaji'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN sisa_gaji DECIMAL(15,2) DEFAULT 0.00")
                cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'gaji_awal'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN gaji_awal DECIMAL(15,2) DEFAULT 0.00")
                cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'simpanan_wajib_bayar'")
                if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN simpanan_wajib_bayar DECIMAL(15,2) DEFAULT 0.00")
            except: pass
            
            conn.commit()
            print("[INFO] Sinkronisasi & Migrasi Skema Database Berhasil.")
        except Exception as e:
            print(f"[ERROR] Inisialisasi DB Gagal: {e}")
        finally:
            cursor.close()