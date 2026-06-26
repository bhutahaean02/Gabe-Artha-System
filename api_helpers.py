from datetime import datetime
import calendar
from flask import session
import requests
import re
from bs4 import BeautifulSoup

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
        if isinstance(value, str):
            # If a comma is present, it's the decimal separator. '.' are thousand separators. (e.g., "1.500,50")
            if ',' in value:
                value = value.replace('.', '').replace(',', '.')
            # If no comma, but multiple dots, they are all thousand separators. (e.g., "1.500.000")
            elif value.count('.') > 1:
                value = value.replace('.', '')
            # If no comma and only one dot, it's ambiguous. "1.000" vs "2.5".
            # Heuristic: if there are 3 digits after the dot, it's a thousand separator.
            elif value.count('.') == 1:
                if len(value.split('.')[1]) == 3:
                    value = value.replace('.', '')
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
def catat_jurnal(cursor, tanggal, account_code, keterangan, debit, kredit, cabang_override=None):
    if debit == 0 and kredit == 0:
        return
        
    cabang = cabang_override
    if not cabang:
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

# === FUNGSI BANTUAN UNTUK KALKULASI DENDA KETERLAMBATAN ===
def hitung_denda_keterlambatan(jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, tagihan_denda_db, angsuran_denda, denda_aktif=True, jenis_pinjaman='Multiguna', tgl_referensi=None):
    if not jatuh_tempo or not denda_aktif:
        return 0.0, 0
        
    ref_date = tgl_referensi if tgl_referensi else datetime.now().date()
    
    # Konversi string ke date
    try:
        if isinstance(jatuh_tempo, str): jatuh_tempo = datetime.strptime(jatuh_tempo[:10], '%Y-%m-%d').date()
        elif hasattr(jatuh_tempo, 'date'): jatuh_tempo = jatuh_tempo.date()
        if isinstance(tgl_bayar, str) and tgl_bayar: tgl_bayar = datetime.strptime(tgl_bayar[:10], '%Y-%m-%d').date()
        elif hasattr(tgl_bayar, 'date'): tgl_bayar = tgl_bayar.date()
    except (ValueError, TypeError):
        return 0.0, 0 # Return 0 if dates are invalid
        
    base_date = jatuh_tempo
    if tgl_bayar and tgl_bayar > jatuh_tempo: base_date = tgl_bayar
        
    od_hari = max((ref_date - base_date).days, 0)
    
    sisa_p = float(tagihan_pokok or 0) - float(angsuran_pokok or 0)
    sisa_m = float(tagihan_margin or 0) - float(angsuran_margin or 0)
    
    d_kalk = float(tagihan_denda_db or 0) - float(angsuran_denda or 0)
    
    if sisa_p > 0.01 or sisa_m > 0.01:
        jp_lower = str(jenis_pinjaman).lower()
        rate = 0.007 if jp_lower == 'tempo' or 'urgent' in jp_lower else 0.005
        d_kalk += (sisa_p + sisa_m) * rate * od_hari
        
    return max(0, d_kalk), od_hari

# === FUNGSI BANTUAN BARU UNTUK EKSTRAKSI KOORDINAT GOOGLE MAPS ===
def extract_gmaps_coordinates(url):
    """
    Mengekstrak koordinat Latitude dan Longitude dari berbagai format URL Google Maps
    dengan mekanisme fallback untuk akurasi terbaik.

    Alur kerja:
    1. Resolve Redirect: Mengikuti short link (misal, goo.gl) ke URL panjangnya.
    2. Prioritas 1 (Pinpoint): Mencari parameter !3d (lat) dan !4d (lon) di URL.
    3. Prioritas 2 (Approximate): Mencari meta tag 'og:image' di HTML dan mengekstrak
       koordinat dari parameter 'center' di URL gambar statis.
    4. Prioritas 3 (Viewport): Mencari pola @lat,lng di URL sebagai fallback terakhir.

    :param url: String URL Google Maps (bisa pendek atau panjang).
    :return: Dictionary berisi status, lat, lng, dan tipe akurasi.
    """
    if not isinstance(url, str) or not ('http' in url or 'goo.gl' in url or 'maps.app' in url):
        return {'status': 'error', 'message': 'URL tidak valid.'}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # FASE 1: Resolve Redirect
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = response.url

        # FASE 2 (Prioritas 1): Cari parameter !3d dan !4d (akurasi tinggi)
        match_3d4d = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', final_url)
        if match_3d4d:
            return {'status': 'success', 'lat': float(match_3d4d.group(1)), 'lng': float(match_3d4d.group(2)), 'accuracy_type': 'pinpoint'}

        # FASE 3 (Prioritas 2): Fallback ke parsing HTML untuk meta tag og:image
        soup = BeautifulSoup(response.text, 'html.parser')
        meta_tag = soup.find('meta', property='og:image')
        if meta_tag and meta_tag.get('content'):
            image_url = meta_tag['content']
            match_center = re.search(r'center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)', image_url)
            if match_center:
                return {'status': 'success', 'lat': float(match_center.group(1)), 'lng': float(match_center.group(2)), 'accuracy_type': 'approximate'}

        # FASE 4 (Prioritas 3): Fallback terakhir, cari pola @lat,lng
        match_at = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
        if match_at:
            return {'status': 'success', 'lat': float(match_at.group(1)), 'lng': float(match_at.group(2)), 'accuracy_type': 'viewport'}

        return {'status': 'error', 'message': 'Tidak dapat menemukan format koordinat yang dikenali.'}

    except requests.RequestException as e:
        return {'status': 'error', 'message': f"Gagal mengakses URL: {e}"}
    except (ValueError, TypeError) as e:
        return {'status': 'error', 'message': f"Gagal memproses data: {e}"}

# === FUNGSI BANTUAN BARU UNTUK EKSTRAKSI KOORDINAT GOOGLE MAPS ===
def extract_gmaps_coordinates(url):
    """
    Mengekstrak koordinat Latitude dan Longitude dari berbagai format URL Google Maps
    dengan mekanisme fallback untuk akurasi terbaik.

    Alur kerja:
    1. Resolve Redirect: Mengikuti short link (misal, goo.gl) ke URL panjangnya.
    2. Prioritas 1 (Pinpoint): Mencari parameter !3d (lat) dan !4d (lon) di URL.
    3. Prioritas 2 (Approximate): Mencari meta tag 'og:image' di HTML dan mengekstrak
       koordinat dari parameter 'center' di URL gambar statis.
    4. Prioritas 3 (Viewport): Mencari pola @lat,lng di URL sebagai fallback terakhir.

    :param url: String URL Google Maps (bisa pendek atau panjang).
    :return: Dictionary berisi status, lat, lng, dan tipe akurasi.
    """
    if not isinstance(url, str) or not ('http' in url or 'goo.gl' in url or 'maps.app' in url):
        return {'status': 'error', 'message': 'URL tidak valid.'}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # FASE 1: Resolve Redirect
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = response.url

        # FASE 2 (Prioritas 1): Cari parameter !3d dan !4d (akurasi tinggi)
        match_3d4d = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', final_url)
        if match_3d4d:
            return {
                'status': 'success',
                'lat': float(match_3d4d.group(1)),
                'lng': float(match_3d4d.group(2)),
                'accuracy_type': 'pinpoint'
            }

        # FASE 3 (Prioritas 2): Fallback ke parsing HTML untuk meta tag og:image
        soup = BeautifulSoup(response.text, 'html.parser')
        meta_tag = soup.find('meta', property='og:image')
        if meta_tag and meta_tag.get('content'):
            image_url = meta_tag['content']
            # Mencari format center=lat%2Clng atau center=lat,lng
            match_center = re.search(r'center=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)', image_url)
            if match_center:
                return {'status': 'success', 'lat': float(match_center.group(1)), 'lng': float(match_center.group(2)), 'accuracy_type': 'approximate'}

        # FASE 4 (Prioritas 3): Fallback terakhir, cari pola @lat,lng
        match_at = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
        if match_at:
            return {'status': 'success', 'lat': float(match_at.group(1)), 'lng': float(match_at.group(2)), 'accuracy_type': 'viewport'}

        return {'status': 'error', 'message': 'Tidak dapat menemukan format koordinat yang dikenali.'}

    except requests.RequestException as e:
        return {'status': 'error', 'message': f"Gagal mengakses URL: {e}"}
    except (ValueError, TypeError) as e:
        return {'status': 'error', 'message': f"Gagal memproses data: {e}"}