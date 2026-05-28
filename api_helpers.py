from datetime import datetime
import calendar
from flask import session

# === FUNGSI BANTUAN UNTUK MENAMBAH BULAN ===
def tambah_bulan(tanggal_awal, tambah_bulan):
    bulan = tanggal_awal.month - 1 + tambah_bulan
    tahun = int(tanggal_awal.year + bulan / 12)
    bulan = bulan % 12 + 1
    hari = min(tanggal_awal.day, calendar.monthrange(tahun, bulan)[1])
    return tanggal_awal.replace(year=tahun, month=bulan, day=hari)

# === FUNGSI BANTUAN UNTUK VALIDASI INPUT ANGKA ===
def parse_float(value, field_name):
    if not value:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Input pada '{field_name}' harus berupa angka yang valid.")

def parse_int(value, field_name):
    if not value:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Input pada '{field_name}' harus berupa angka bulat (tanpa koma) yang valid.")

# === FUNGSI BANTUAN UNTUK OTOMATISASI JURNAL UMUM ===
def catat_jurnal(cursor, tanggal, account_code, keterangan, debit, kredit):
    if debit == 0 and kredit == 0:
        return
    try:
        cabang = session.get('cabang', 'GAS') if session else 'GAS'
    except Exception:
        cabang = 'GAS'
        
    cursor.execute("SELECT id FROM coa WHERE account_code = %s", (account_code,))
    coa = cursor.fetchone()
    if coa:
        coa_id = coa['id'] if isinstance(coa, dict) else coa[0]
        try:
            cursor.execute("""
                INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (tanggal, coa_id, keterangan, debit, kredit, cabang))
        except Exception:
            try: cursor.execute("ALTER TABLE jurnal_umum ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            except: pass
            try: cursor.execute("INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang) VALUES (%s, %s, %s, %s, %s, %s)", (tanggal, coa_id, keterangan, debit, kredit, cabang))
            except: cursor.execute("INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit) VALUES (%s, %s, %s, %s, %s)", (tanggal, coa_id, keterangan, debit, kredit))

# === FUNGSI BANTUAN UNTUK GENERATE NOMOR ANGGOTA ===
def generate_nomor_anggota_logic(cursor, cabang):
    tanggal_str = datetime.now().strftime("%d%m%Y")
    prefix = f"{cabang}-{tanggal_str}-"
    query = "SELECT no_anggota FROM identitas WHERE no_anggota LIKE %s ORDER BY no_anggota DESC LIMIT 1"
    cursor.execute(query, (prefix + '%',))
    last_record = cursor.fetchone()
    
    if last_record and last_record.get('no_anggota'):
        last_number = int(last_record['no_anggota'].split('-')[-1])
        new_number = last_number + 1
    else:
        new_number = 1
        
    return f"{prefix}{new_number:03d}"

# === FUNGSI BANTUAN UNTUK MENGUBAH ANGKA MENJADI TERBILANG ===
def terbilang(n):
    n = int(n)
    if n == 0: return "Nol"
    def bilang(x):
        angka = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]
        if x == 0: return ""
        elif x < 12: return angka[x]
        elif x < 20: return bilang(x - 10) + " Belas"
        elif x < 100: return (bilang(x // 10) + " Puluh " + bilang(x % 10)).strip()
        elif x < 200: return ("Seratus " + bilang(x - 100)).strip()
        elif x < 1000: return (bilang(x // 100) + " Ratus " + bilang(x % 100)).strip()
        elif x < 2000: return ("Seribu " + bilang(x - 1000)).strip()
        elif x < 1000000: return (bilang(x // 1000) + " Ribu " + bilang(x % 1000)).strip()
        elif x < 1000000000: return (bilang(x // 1000000) + " Juta " + bilang(x % 1000000)).strip()
        elif x < 1000000000000: return (bilang(x // 1000000000) + " Miliar " + bilang(x % 1000000000)).strip()
        else: return str(x)
    return bilang(n)