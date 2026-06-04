from flask import Blueprint, request, jsonify, send_file, session
import mysql.connector
from datetime import datetime, timedelta, date
import calendar # Tambahkan ini untuk kalkulasi bulan
from db import get_db_connection
import os
import tempfile
import json
from werkzeug.security import generate_password_hash

# Membuat Blueprint khusus untuk API Backend
api_bp = Blueprint('api', __name__)

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
    cursor.execute("SELECT id FROM coa WHERE account_code = %s", (account_code,))
    coa = cursor.fetchone()
    if coa:
        coa_id = coa['id'] if isinstance(coa, dict) else coa[0]
        cursor.execute("""
            INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit)
            VALUES (%s, %s, %s, %s, %s)
        """, (tanggal, coa_id, keterangan, debit, kredit))

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

# === API: MENGAMBIL DAFTAR ANGGOTA UNTUK DROPDOWN ===
@api_bp.route('/api/anggota_list', methods=['GET'])
def get_anggota_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT no_anggota, nama_anggota FROM identitas ORDER BY nama_anggota ASC")
        data = cursor.fetchall()
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()

# === API: ALL DATA PIVOT (DASHBOARD & EXCEL) ===
@api_bp.route('/api/alldata', methods=['GET'])
def get_alldata_pivot():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    
    try:
        # Ambil Data Anggota & Simpanan
        query_id = "SELECT i.*, s.simpanan_pokok, s.simpanan_wajib FROM identitas i LEFT JOIN simpanan s ON i.no_anggota = s.nomor_anggota"
        if role != 'Super Admin':
            query_id += f" WHERE i.cabang = '{cabang}'"
        cursor.execute(query_id)
        members = cursor.fetchall()
        member_dict = {m['no_anggota']: m for m in members}
        
        # Ambil Data Angsuran Multiguna & Tempo
        cursor.execute("SELECT id, no_anggota, jenis_pinjaman as kategori_pinjaman, jatuh_tempo, tgl_pencairan, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, tunggakan_denda, od_hari FROM angsuran_multiguna_tempo")
        amts = cursor.fetchall()

        # Ambil Data Angsuran Dana Urgent
        cursor.execute("SELECT id, no_anggota, jenis_dana_urgent as kategori_pinjaman, tanggal_jatuh_tempo as jatuh_tempo, tgl_pencairan, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, tunggakan_denda, od_hari FROM angsuran_dana_urgent")
        adus = cursor.fetchall()

        all_trans = amts + adus
        
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        today = datetime.now().date()
        result = []

        for t in all_trans:
            no_anggota = t['no_anggota']
            if no_anggota not in member_dict:
                continue
                
            m = member_dict[no_anggota]
            row = {k: v for k, v in m.items()}
            
            row['no_transaksi'] = f"{str(t['kategori_pinjaman'])[:3].upper()}-{t['id']}"
            row['kategori_pinjaman'] = t['kategori_pinjaman']
            
            jt = t['jatuh_tempo']
            if hasattr(jt, 'isoformat') and jt: jt = jt.strftime('%Y-%m-%d')
            row['jatuh_tempo'] = jt
            
            tc = t['tgl_pencairan']
            if hasattr(tc, 'isoformat') and tc: tc = tc.strftime('%Y-%m-%d')
            row['tgl_pencairan'] = tc
            
            for date_field in ['tgl_lahir', 'awal_bekerja', 'akhir_bekerja']:
                if row.get(date_field) and hasattr(row[date_field], 'isoformat'):
                    row[date_field] = row[date_field].strftime('%Y-%m-%d')
                    
            tag_p = float(t['tagihan_pokok'] or 0)
            tag_m = float(t['tagihan_margin'] or 0)
            ang_p = float(t['angsuran_pokok'] or 0)
            ang_m = float(t['angsuran_margin'] or 0)
            ang_d = float(t['angsuran_denda'] or 0)
            tag_d_db = float(t['tagihan_denda'] or 0)
            
            sisa_p = max(0, tag_p - ang_p)
            sisa_m = max(0, tag_m - ang_m)
            denda_berjalan = tag_d_db - ang_d
            
            if t['status'] == 'BELUM BAYAR':
                jt_date = t['jatuh_tempo']
                if isinstance(jt_date, str):
                    try: jt_date = datetime.strptime(jt_date[:10], '%Y-%m-%d').date()
                    except: jt_date = None
                if jt_date:
                    od_hari = max((today - jt_date).days, 0)
                    if (sisa_p > 0.01 or sisa_m > 0.01) and denda_aktif:
                        if t['kategori_pinjaman'] in ['Tempo', 'Gaji', 'THR']: denda_berjalan += (sisa_p * sisa_m) * 0.007 * od_hari
                        else: denda_berjalan += (sisa_p + sisa_m) * 0.005 * od_hari

            denda_berjalan = max(0, denda_berjalan)

            for prefix in ['MG', 'TM', 'GJ', 'THR']:
                row[f'{prefix}_Status'] = None
                row[f'{prefix}_Tagihan_Pokok'] = 0; row[f'{prefix}_Tagihan_Margin'] = 0; row[f'{prefix}_Denda_Berjalan'] = 0
                row[f'{prefix}_Angsuran_Pokok'] = 0; row[f'{prefix}_Angsuran_Margin'] = 0; row[f'{prefix}_Angsuran_Denda'] = 0
                row[f'{prefix}_Tunggakan_Pokok'] = 0; row[f'{prefix}_Tunggakan_Margin'] = 0

            kat = t['kategori_pinjaman']
            px = 'MG' if kat == 'Multiguna' else ('TM' if kat == 'Tempo' else ('GJ' if kat == 'Gaji' else ('THR' if kat == 'THR' else None)))

            if px:
                row[f'{px}_Status'] = t['status']
                row[f'{px}_Tagihan_Pokok'] = tag_p; row[f'{px}_Tagihan_Margin'] = tag_m; row[f'{px}_Denda_Berjalan'] = denda_berjalan
                row[f'{px}_Angsuran_Pokok'] = ang_p; row[f'{px}_Angsuran_Margin'] = ang_m; row[f'{px}_Angsuran_Denda'] = ang_d
                row[f'{px}_Tunggakan_Pokok'] = sisa_p if t['status'] == 'BELUM BAYAR' else 0
                row[f'{px}_Tunggakan_Margin'] = sisa_m if t['status'] == 'BELUM BAYAR' else 0

            result.append(row)

        return jsonify({'status': 'success', 'data': result}), 200

    except Exception as e:
        import traceback
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500
    finally:
        cursor.close()
        conn.close()
        conn.close()

# === API: GENERATE NOMOR ANGGOTA OTOMATIS (Tombol Tongkat Ajaib) ===
@api_bp.route('/api/generate_no_anggota', methods=['GET'])
def generate_no_anggota():
    cabang = request.args.get('cabang', 'GAS')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        no_anggota_final = generate_nomor_anggota_logic(cursor, cabang)
        return jsonify({'status': 'success', 'no_anggota': no_anggota_final}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: MENGAMBIL DATA AUDIT LOGS ===
@api_bp.route('/api/audit_logs', methods=['GET'])
def get_audit_logs():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role', 'System')
    
    try:
        # Memastikan tabel sudah dibuat (berjaga-jaga jika dipanggil sebelum ada pembatalan transaksi)
        cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(100), role VARCHAR(50), cabang VARCHAR(50), aksi VARCHAR(255), detail TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        
        # --- FITUR PENGHAPUSAN OTOMATIS: Hapus log yang usianya lebih dari 3 bulan ---
        cursor.execute("DELETE FROM audit_logs WHERE created_at < DATE_SUB(NOW(), INTERVAL 3 MONTH)")
        conn.commit()

        if role in ['Super Admin', 'Manager']:
            cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 1000")
        else:
            cursor.execute("SELECT * FROM audit_logs WHERE cabang = %s ORDER BY id DESC LIMIT 1000", (cabang,))
            
        data = cursor.fetchall()
        for row in data:
            if hasattr(row['created_at'], 'isoformat'): row['created_at'] = str(row['created_at'])
                
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: PROSES PENCAIRAN & AUTO-GENERATE JADWAL ANGSURAN ===
@api_bp.route('/api/pencairan_multiguna', methods=['POST'])
def proses_pencairan():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
            try:
                cursor.execute("SELECT cabang FROM approval_queue LIMIT 1")
                cursor.fetchall()
            except:
                cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Pencairan Multiguna', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Transaksi diajukan! Menunggu Approval dari Manager.'}), 201
        finally:
            cursor.close()
            conn.close()

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        conn.start_transaction()
        
        # Ekstrak Data Dasar
        no_anggota = data.get('no_anggota')
        nama_anggota = data.get('nama_anggota')
        jenis_pencairan = data.get('jenis_pencairan')
        tanggal_cair = data.get('tanggal_cair')
        tanggal_gajian = data.get('tanggal_gajian')
        besar_pinjaman = parse_float(data.get('besar_pinjaman'), 'Besar Pinjaman')
        tenor = parse_int(data.get('tenor'), 'Tenor')
        bunga_persen = parse_float(data.get('bunga_persen'), 'Bunga Persen')
        
        # Ekstrak Potongan
        potongan_angsuran = parse_float(data.get('potongan_angsuran'), 'Potongan Angsuran')
        potongan_dana_urgent = parse_float(data.get('potongan_dana_urgent'), 'Potongan Dana Urgent')
        biaya_jamsostek = parse_float(data.get('biaya_jamsostek'), 'Biaya Jamsostek')
        potongan_simpanan_pokok = parse_float(data.get('potongan_simpanan_pokok'), 'Potongan Simpanan Pokok')
        potongan_adm = parse_float(data.get('potongan_adm'), 'Potongan Administrasi')
        potongan_dana_kematian = parse_float(data.get('potongan_dana_kematian'), 'Potongan Dana Kematian')
        potongan_ppap = parse_float(data.get('potongan_ppap'), 'Potongan PPAP')
        terima_bersih = parse_float(data.get('terima_bersih'), 'Terima Bersih')
        
        # 2. SIMPAN KE TABEL PENCAIRAN_MULTIGUNA_TEMPO
        query_pencairan = """
            INSERT INTO pencairan_multiguna_tempo (
                no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, 
                besar_pinjaman, potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, 
                potongan_simpanan_pokok, potongan_adm, potongan_dana_kematian, potongan_ppap, 
                terima_bersih, tenor
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_pencairan, (
            no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, 
            besar_pinjaman, potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, 
            potongan_simpanan_pokok, potongan_adm, potongan_dana_kematian, potongan_ppap, 
            terima_bersih, tenor
        ))
        
        # 3. LOGIKA AUTO-GENERATE JADWAL ANGSURAN
        tagihan_pokok = besar_pinjaman / tenor if tenor > 0 else 0
        tagihan_margin = besar_pinjaman * (bunga_persen / 100)
        total_margin = tagihan_margin * tenor
        
        tgl_cair_obj = datetime.strptime(tanggal_cair, '%Y-%m-%d').date()
        
        query_angsuran = """
            INSERT INTO angsuran_multiguna_tempo (
                no_anggota, nama_anggota, jenis_pinjaman, tgl_pencairan, tgl_penggajian, jatuh_tempo, 
                terima_bersih, besar_pinjaman, tenor, bunga_persen, margin, total_margin, 
                sisa_pokok, sisa_margin, angsuran_ke, tagihan_pokok, tagihan_margin, tagihan_denda, 
                angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, 
                od_hari, tunggakan_denda, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        for i in range(1, tenor + 1):
            jatuh_tempo = tambah_bulan(tgl_cair_obj, i)
            sisa_pokok = besar_pinjaman - (tagihan_pokok * (i - 1))
            sisa_margin_berjalan = total_margin - (tagihan_margin * (i - 1))
            
            cursor.execute(query_angsuran, (
                no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, jatuh_tempo,
                terima_bersih, besar_pinjaman, tenor, bunga_persen, tagihan_margin, total_margin,
                sisa_pokok, sisa_margin_berjalan, i, tagihan_pokok, tagihan_margin, 0,
                0, 0, 0, 0, 0, 0, 0, 'BELUM BAYAR'
            ))

        # === 4. LOGIKA OTOMATIS: SIMPANAN POKOK DARI POTONGAN PENCAIRAN ===
        if potongan_simpanan_pokok > 0:
            cursor.execute("SELECT id FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
            simpanan_record = cursor.fetchone()
            if simpanan_record:
                # Jika anggota sudah punya buku simpanan, update saldonya
                cursor.execute("""
                    UPDATE simpanan 
                    SET simpanan_pokok = simpanan_pokok + %s, total_simpanan = total_simpanan + %s
                    WHERE nomor_anggota = %s
                """, (potongan_simpanan_pokok, potongan_simpanan_pokok, no_anggota))
            else:
                # Jika belum ada, buat baris buku simpanan baru
                cursor.execute("""
                    INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_pokok, simpanan_wajib, total_simpanan)
                    VALUES (%s, %s, %s, 0, %s)
                """, (no_anggota, nama_anggota, potongan_simpanan_pokok, potongan_simpanan_pokok))

        # === 5. JURNAL OTOMATIS: PENCAIRAN MULTIGUNA ===
        akun_piutang = '1201' if jenis_pencairan == 'Multiguna' else '1202'
        
        # 1. Debit: Piutang Bertambah (Sebesar Plafon Kotor)
        catat_jurnal(cursor, tanggal_cair, akun_piutang, f"Pencairan {jenis_pencairan} (Plafon) - {nama_anggota}", besar_pinjaman, 0)
        
        # 2. Kredit: Kas Keluar (Hanya sebesar Terima Bersih)
        if terima_bersih > 0:
            catat_jurnal(cursor, tanggal_cair, '1101', f"Pencairan {jenis_pencairan} (Terima Bersih) - {nama_anggota}", 0, terima_bersih)

        # 3. Kredit: Pendapatan Administrasi (Masuk Laba/Rugi)
        if potongan_adm > 0:
            catat_jurnal(cursor, tanggal_cair, '4105', f"Pendapatan Adm Pinjaman - {nama_anggota}", 0, potongan_adm)

        # 4. Kredit: Ekuitas Simpanan Pokok (Masuk Neraca)
        if potongan_simpanan_pokok > 0:
            catat_jurnal(cursor, tanggal_cair, '3101', f"Simpanan Pokok - {nama_anggota}", 0, potongan_simpanan_pokok)
            
        # 5. Kredit: Kewajiban/Titipan (Masuk Neraca)
        if potongan_dana_kematian > 0:
            catat_jurnal(cursor, tanggal_cair, '2101', f"Titipan Dana Kematian - {nama_anggota}", 0, potongan_dana_kematian)
        if biaya_jamsostek > 0:
            catat_jurnal(cursor, tanggal_cair, '2102', f"Titipan Jamsostek - {nama_anggota}", 0, biaya_jamsostek)
        if potongan_ppap > 0:
            catat_jurnal(cursor, tanggal_cair, '2103', f"Jaminan PPAP - {nama_anggota}", 0, potongan_ppap)

        # 6. Kredit: Pemotongan Top-Up (Mengurangi Piutang Lama)
        if potongan_angsuran > 0:
            # Ambil data sisa hutang lama (Pokok & Margin) untuk dipecah agar akurat ke Laba/Rugi
            cursor.execute("SELECT SUM(tagihan_pokok) as sisa_pokok, SUM(tagihan_margin) as sisa_margin FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            tagihan_lama = cursor.fetchone()
            sisa_pokok_lama = float(tagihan_lama[0] or 0) if tagihan_lama else 0.0
            sisa_margin_lama = float(tagihan_lama[1] or 0) if tagihan_lama else 0.0
            
            catat_jurnal(cursor, tanggal_cair, akun_piutang, f"Pelunasan Piutang Lama (Top-Up) - {nama_anggota}", 0, sisa_pokok_lama)
            if sisa_margin_lama > 0:
                akun_pendapatan = '4101' if jenis_pencairan == 'Multiguna' else '4102'
                catat_jurnal(cursor, tanggal_cair, akun_pendapatan, f"Pendapatan Margin Lama (Top-Up) - {nama_anggota}", 0, sisa_margin_lama)
            sisa_denda = potongan_angsuran - sisa_pokok_lama - sisa_margin_lama
            if sisa_denda > 0:
                catat_jurnal(cursor, tanggal_cair, '4106', f"Pendapatan Denda (Top-Up) - {nama_anggota}", 0, sisa_denda)
                
            cursor.execute("UPDATE angsuran_multiguna_tempo SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS TOP-UP', tgl_bayar = %s WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (tanggal_cair, no_anggota))

        if potongan_dana_urgent > 0:
            catat_jurnal(cursor, tanggal_cair, '1203', f"Potongan Pelunasan Dana Urgent - {nama_anggota}", 0, potongan_dana_urgent)
            cursor.execute("UPDATE angsuran_dana_urgent SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS TOP-UP', tgl_bayar = %s WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (tanggal_cair, no_anggota))

        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Berhasil dicairkan! {tenor} bulan jadwal angsuran telah otomatis dibuat.'}), 201

    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: PROSES PENCAIRAN DANA URGENT (1 BULAN) ===
@api_bp.route('/api/pencairan_urgent', methods=['POST'])
def proses_pencairan_urgent():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
            try:
                cursor.execute("SELECT cabang FROM approval_queue LIMIT 1")
                cursor.fetchall()
            except:
                cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Pencairan Dana Urgent', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Transaksi diajukan! Menunggu Approval dari Manager.'}), 201
        finally:
            cursor.close()
            conn.close()

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        conn.start_transaction()
        
        no_anggota = data.get('no_anggota')
        nama_anggota = data.get('nama_anggota')
        jenis_dana_urgent = data.get('jenis_dana_urgent')
        tgl_pencairan = data.get('tanggal_pencairan_dana_urgent')
        tgl_pembayaran = data.get('tanggal_pembayaran_dana_urgent')
        jumlah_dana_urgent = parse_float(data.get('jumlah_dana_urgent'), 'Jumlah Dana Urgent')
        # Margin otomatis 20% dari pokok pinjaman dana urgent
        margin_dana_urgent = jumlah_dana_urgent * 0.20
        
        query_pencairan = """
            INSERT INTO pencairan_dana_urgent (
                no_anggota, nama_anggota, jenis_dana_urgent, tanggal_pencairan_dana_urgent, 
                tanggal_pembayaran_dana_urgent, jumlah_dana_urgent, margin_dana_urgent
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_pencairan, (
            no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, 
            tgl_pembayaran, jumlah_dana_urgent, margin_dana_urgent
        ))
        
        query_angsuran = """
            INSERT INTO angsuran_dana_urgent (
                no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tanggal_jatuh_tempo, 
                margin, tagihan_pokok, tagihan_margin, tagihan_denda, 
                angsuran_pokok, angsuran_margin, angsuran_denda, 
                tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_angsuran, (
            no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tgl_pembayaran,
            margin_dana_urgent, jumlah_dana_urgent, margin_dana_urgent, 0,
            0, 0, 0, 0, 0, 0, 0, 'BELUM BAYAR'
        ))

        # === JURNAL OTOMATIS: PENCAIRAN URGENT ===
        akun_piutang = '1203' if jenis_dana_urgent == 'Gaji' else '1204'
        catat_jurnal(cursor, tgl_pencairan, akun_piutang, f"Pencairan Dana Urgent {jenis_dana_urgent} - {nama_anggota}", jumlah_dana_urgent, 0)
        catat_jurnal(cursor, tgl_pencairan, '1101', f"Pencairan Dana Urgent {jenis_dana_urgent} (Kas Keluar) - {nama_anggota}", 0, jumlah_dana_urgent)

        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pencairan Dana Urgent berhasil diproses! Tagihan untuk 1 bulan telah dibuat.'}), 201

    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: IDENTITAS (CRUD) ===
@api_bp.route('/api/identitas', methods=['GET', 'POST'])
def api_identitas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        if request.method == 'GET':
            cursor.execute("SELECT no_anggota, nama_anggota, pt_instansi, no_telp, kol FROM identitas ORDER BY no_anggota DESC")
            data = cursor.fetchall()
            return jsonify({'status': 'success', 'data': data}), 200

        elif request.method == 'POST':
            data = request.json
            no_anggota_final = data.get('no_anggota')
            
            # --- MULAI PERUBAHAN HASH PASSWORD ---
            password_plain = data.get('password')
            password_hashed = generate_password_hash(password_plain) if password_plain else None
            # --- AKHIR PERUBAHAN HASH PASSWORD ---

            if not no_anggota_final or no_anggota_final == "":
                cabang = data.get('cabang', 'GAS')
                no_anggota_final = generate_nomor_anggota_logic(cursor, cabang)

            query = """
                INSERT INTO identitas (
                    no_anggota, nama_anggota, tgl_lahir, no_telp, nik_ktp, nik_kk, 
                    alamat_ktp, alamat_tagih, status_tempat_tinggal, pt_instansi, 
                    status_karyawan, awal_bekerja, lama_kerja, akhir_bekerja, jabatan, 
                    no_jmo, status_jmo, email, password, no_rek, bank, 
                    nama_penanggung_jawab, no_telp_penanggung_jawab, no_rek_penanggung_jawab, 
                    bank_penanggung_jawab, kol, kriteria
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """
            values = (
                no_anggota_final, data.get('nama_anggota'), data.get('tgl_lahir') or None, 
                data.get('no_telp'), data.get('nik_ktp'), data.get('nik_kk'),
                data.get('alamat_ktp'), data.get('alamat_tagih'), data.get('status_tempat_tinggal'), 
                data.get('pt_instansi'), data.get('status_karyawan'), data.get('awal_bekerja') or None, 
                data.get('lama_kerja'), data.get('akhir_bekerja') or None, data.get('jabatan'),
                data.get('no_jmo'), data.get('status_jmo'), data.get('email'), 
                password_hashed, data.get('no_rek'), data.get('bank'),
                data.get('nama_penanggung_jawab'), data.get('no_telp_penanggung_jawab'), 
                data.get('no_rek_penanggung_jawab'), data.get('bank_penanggung_jawab'), 
                data.get('kol'), data.get('kriteria')
            )
            cursor.execute(query, values)
            conn.commit()
            return jsonify({'status': 'success', 'message': f"Data berhasil disimpan! No Anggota: {no_anggota_final}"}), 201

    except mysql.connector.Error as err:
        return jsonify({'status': 'error', 'message': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: MENGAMBIL DETAIL ANGGOTA LENGKAP ===
@api_bp.route('/api/anggota/<no_anggota>/detail', methods=['GET'])
def get_anggota_detail(no_anggota):
    # --- PROTEKSI PRIVASI: Anggota tidak boleh melihat data anggota lain ---
    if session.get('role') == 'Anggota':
        if no_anggota != session.get('user_id') and no_anggota != session.get('username'):
            return jsonify({'status': 'error', 'message': 'Akses ditolak. Anda tidak bisa melihat data anggota lain.'}), 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Identitas Dasar
        cursor.execute("SELECT * FROM identitas WHERE no_anggota = %s", (no_anggota,))
        identitas = cursor.fetchone()
        if not identitas:
            # Coba cari berdasarkan nama jika frontend salah mengirimkan nama anggota alih-alih nomor
            cursor.execute("SELECT * FROM identitas WHERE nama_anggota = %s", (no_anggota,))
            identitas = cursor.fetchone()
            
            if not identitas:
                return jsonify({'status': 'error', 'message': 'Anggota tidak ditemukan.'}), 404
                
            # Update variabel dengan nomor anggota yang sebenarnya
            no_anggota = identitas['no_anggota']

        for key, val in identitas.items():
            if hasattr(val, 'isoformat'): identitas[key] = str(val)
                
        # 2. Simpanan
        cursor.execute("SELECT simpanan_pokok, simpanan_wajib, total_simpanan FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
        simpanan = cursor.fetchone()
        
        # Jika anggota belum punya buku simpanan, berikan nilai 0 agar antarmuka web tidak error
        if not simpanan:
            simpanan = {'simpanan_pokok': 0, 'simpanan_wajib': 0, 'total_simpanan': 0}

        # 3. Lampiran Tagihan Multiguna / Tempo
        cursor.execute("""
            SELECT * 
            FROM angsuran_multiguna_tempo WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_utama = cursor.fetchall()
        for tag in tagihan_utama:
            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tgl_penggajian'), 'isoformat') and tag['tgl_penggajian']: tag['tgl_penggajian'] = str(tag['tgl_penggajian'])
            if hasattr(tag.get('jatuh_tempo'), 'isoformat') and tag['jatuh_tempo']: tag['jatuh_tempo'] = str(tag['jatuh_tempo'])
        
        # 4. Lampiran Tagihan Dana Urgent
        cursor.execute("""
            SELECT * 
            FROM angsuran_dana_urgent WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_urgent = cursor.fetchall()
        for tag in tagihan_urgent:
            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tanggal_jatuh_tempo'), 'isoformat') and tag['tanggal_jatuh_tempo']: tag['tanggal_jatuh_tempo'] = str(tag['tanggal_jatuh_tempo'])

        # 5. Histori Transaksi (Jurnal Umum)
        nama_anggota = identitas['nama_anggota']
        cursor.execute("""
            SELECT j.id, j.tanggal, c.account_name, j.keterangan, j.debit, j.kredit 
            FROM (
                SELECT id, tanggal, coa_id, keterangan, debit, kredit 
                FROM jurnal_umum 
                WHERE keterangan LIKE %s 
                ORDER BY id DESC LIMIT 50
            ) j
            JOIN coa c ON j.coa_id = c.id 
            ORDER BY j.id DESC
        """, ('%' + nama_anggota + '%',))
        histori_transaksi = cursor.fetchall()
        for h in histori_transaksi:
            if hasattr(h.get('tanggal'), 'isoformat'): h['tanggal'] = str(h['tanggal'])

        # 6. Histori Simpanan
        cursor.execute("""
            SELECT j.id, j.tanggal, c.account_name, j.keterangan, j.debit, j.kredit 
            FROM jurnal_umum j
            JOIN coa c ON j.coa_id = c.id 
            WHERE j.keterangan LIKE %s AND c.account_code IN ('3101', '3102')
            ORDER BY j.tanggal DESC, j.id DESC
        """, ('%' + nama_anggota + '%',))
        histori_simpanan = cursor.fetchall()
        for h in histori_simpanan:
            if hasattr(h.get('tanggal'), 'isoformat'): h['tanggal'] = str(h['tanggal'])

        return jsonify({'status': 'success', 'data': {
            'identitas': identitas, 'simpanan': simpanan, 'tagihan_utama': tagihan_utama,
            'tagihan_urgent': tagihan_urgent, 'histori_transaksi': histori_transaksi,
            'histori_simpanan': histori_simpanan
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: UPDATE STATUS JMO DARI MONITORING ===
@api_bp.route('/api/update_jmo', methods=['POST'])
def update_jmo():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE identitas SET status_jmo = %s WHERE no_anggota = %s", 
                       (data.get('status_jmo'), data.get('no_anggota')))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Status JMO berhasil diperbarui.'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: MONITORING PINJAMAN (JATUH TEMPO & OVERDUE) ===
@api_bp.route('/api/monitoring_pinjaman', methods=['GET'])
def monitoring_pinjaman_api():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT 
                i.no_anggota, i.nama_anggota, i.pt_instansi, i.status_karyawan, i.akhir_bekerja,
                i.email, i.password, i.no_jmo, i.no_telp, i.nik_ktp, i.status_jmo, i.kol,
                a.tgl_penggajian, a.jatuh_tempo, a.tgl_bayar, a.edc, a.jenis_pinjaman, a.tgl_pencairan, a.besar_pinjaman,
                a.tenor, a.bunga_persen, a.angsuran_ke, a.status as status_pembayaran,
                a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda,
                a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda,
                a.tunggakan_pokok, a.tunggakan_margin, a.od_hari, a.tunggakan_denda,
                s.simpanan_wajib
            FROM identitas i
            INNER JOIN (
                SELECT * FROM (
                    SELECT 
                        no_anggota, tgl_penggajian, jatuh_tempo, tgl_bayar, edc, jenis_pinjaman, tgl_pencairan,
                        besar_pinjaman, tenor, bunga_persen, angsuran_ke, status,
                        tagihan_pokok, tagihan_margin, tagihan_denda,
                        angsuran_pokok, angsuran_margin, angsuran_denda,
                        tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda,
                        ROW_NUMBER() OVER (PARTITION BY no_anggota ORDER BY jatuh_tempo ASC) as rn
                    FROM (
                        SELECT 
                            no_anggota, tgl_penggajian, jatuh_tempo, tgl_bayar, edc, jenis_pinjaman, tgl_pencairan,
                            besar_pinjaman, tenor, bunga_persen, angsuran_ke, status,
                            tagihan_pokok, tagihan_margin, tagihan_denda,
                            angsuran_pokok, angsuran_margin, angsuran_denda,
                            tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda
                        FROM angsuran_multiguna_tempo
                        WHERE status = 'BELUM BAYAR'
                        UNION ALL
                        SELECT 
                            no_anggota, NULL as tgl_penggajian, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, edc, jenis_dana_urgent as jenis_pinjaman, tgl_pencairan,
                            tagihan_pokok as besar_pinjaman, 1 as tenor, 0 as bunga_persen, 1 as angsuran_ke, status,
                            tagihan_pokok, tagihan_margin, tagihan_denda,
                            angsuran_pokok, angsuran_margin, angsuran_denda,
                            tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda
                        FROM angsuran_dana_urgent
                        WHERE status = 'BELUM BAYAR'
                    ) sub_union
                ) sub_rn WHERE rn = 1
            ) a ON i.no_anggota = a.no_anggota
            LEFT JOIN simpanan s ON i.no_anggota = s.nomor_anggota
            ORDER BY a.jatuh_tempo ASC
        """
        cursor.execute(query)
        data = cursor.fetchall()
        
        today = datetime.now().date()
        
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        cursor.execute("""
            SELECT a.no_anggota, a.jatuh_tempo, a.tgl_bayar, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda 
            FROM (
                SELECT no_anggota, jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT no_anggota, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
            ) a
        """)
        all_unpaid = cursor.fetchall()

        summary = {
            'hari_ini': {'anggota_set': set(), 'tagihan': 0},
            'tunggakan_bulan_ini': {'anggota_set': set(), 'tagihan': 0},
            'tunggakan_1_6_bulan': {'anggota_set': set(), 'tagihan': 0},
            'tunggakan_lebih_6_bulan': {'anggota_set': set(), 'tagihan': 0},
            'akumulasi_denda': 0
        }
        
        for u in all_unpaid:
            jt_date = u['jatuh_tempo']
            if not jt_date: continue
            if isinstance(jt_date, str):
                jt_date = datetime.strptime(jt_date[:10], '%Y-%m-%d').date()
            
            last_pay = u.get('tgl_bayar')
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt_date
            if last_pay and last_pay > jt_date: base_date = last_pay
            
            od_sisa = max((today - base_date).days, 0)
            od_hari = max((today - jt_date).days, 0)
            
            sisa_p = float(u['tagihan_pokok'] or 0) - float(u['angsuran_pokok'] or 0)
            sisa_m = float(u['tagihan_margin'] or 0) - float(u['angsuran_margin'] or 0)
            if sisa_p <= 0.01 and sisa_m <= 0.01:
                d_kalk = float(u.get('tagihan_denda') or 0) - float(u['angsuran_denda'] or 0)
            else:
                add_denda = (sisa_p + sisa_m) * 0.005 * od_sisa
                d_kalk = float(u.get('tagihan_denda') or 0) - float(u['angsuran_denda'] or 0) + add_denda
                
            tunggakan_denda = max(0, d_kalk) if denda_aktif else 0
            total_tagihan_row = sisa_p + sisa_m
            
            if jt_date == today:
                summary['hari_ini']['anggota_set'].add(u['no_anggota'])
                summary['hari_ini']['tagihan'] += total_tagihan_row
                
            if od_hari > 0:
                summary['akumulasi_denda'] += tunggakan_denda
                if od_hari <= 30:
                    summary['tunggakan_bulan_ini']['anggota_set'].add(u['no_anggota'])
                    summary['tunggakan_bulan_ini']['tagihan'] += total_tagihan_row
                elif 30 < od_hari <= 180:
                    summary['tunggakan_1_6_bulan']['anggota_set'].add(u['no_anggota'])
                    summary['tunggakan_1_6_bulan']['tagihan'] += total_tagihan_row
                else:
                    summary['tunggakan_lebih_6_bulan']['anggota_set'].add(u['no_anggota'])
                    summary['tunggakan_lebih_6_bulan']['tagihan'] += total_tagihan_row

        summary['hari_ini']['anggota'] = len(summary['hari_ini'].pop('anggota_set'))
        summary['tunggakan_bulan_ini']['anggota'] = len(summary['tunggakan_bulan_ini'].pop('anggota_set'))
        summary['tunggakan_1_6_bulan']['anggota'] = len(summary['tunggakan_1_6_bulan'].pop('anggota_set'))
        summary['tunggakan_lebih_6_bulan']['anggota'] = len(summary['tunggakan_lebih_6_bulan'].pop('anggota_set'))

        for d in data:
            if 'password' in d:
                d['password'] = '********'
                
            jt = d['jatuh_tempo']
            if jt and d.get('status_pembayaran') == 'BELUM BAYAR':
                jt_date = datetime.strptime(str(jt)[:10], '%Y-%m-%d').date() if isinstance(jt, str) else jt
                last_pay = d.get('tgl_bayar')
                if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(str(last_pay)[:10], '%Y-%m-%d').date()
                
                base_date = jt_date
                if last_pay and last_pay > jt_date: base_date = last_pay
                
                od_sisa = max((today - base_date).days, 0)
                d['od_hari'] = max((today - jt_date).days, 0)
                
                sisa_p = float(d['tagihan_pokok'] or 0) - float(d['angsuran_pokok'] or 0)
                sisa_m = float(d['tagihan_margin'] or 0) - float(d['angsuran_margin'] or 0)
                if sisa_p <= 0.01 and sisa_m <= 0.01:
                    d_kalk = float(d.get('tagihan_denda') or 0) - float(d['angsuran_denda'] or 0)
                else:
                    add_denda = (sisa_p + sisa_m) * 0.005 * od_sisa
                    d_kalk = float(d.get('tagihan_denda') or 0) - float(d['angsuran_denda'] or 0) + add_denda
                d['tunggakan_denda'] = max(0, d_kalk) if denda_aktif else 0
            else:
                d['od_hari'] = 0
                d['tunggakan_denda'] = 0
            
            for key, val in d.items():
                if hasattr(val, 'isoformat') and val is not None:
                    d[key] = str(val)
                    
        return jsonify({'status': 'success', 'data': data, 'summary': summary}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: UPDATE TANGGAL JATUH TEMPO ===
@api_bp.route('/api/update_jatuh_tempo', methods=['POST'])
def update_jatuh_tempo():
    data = request.json
    jenis = data.get('jenis_pinjaman')
    id_tagihan = data.get('id_tagihan')
    tanggal_baru = data.get('tanggal_baru')

    if not jenis or not id_tagihan or not tanggal_baru:
        return jsonify({'status': 'error', 'message': 'Data tidak lengkap.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if jenis == 'utama':
            cursor.execute("SELECT no_anggota, tgl_pencairan, jatuh_tempo, angsuran_ke FROM angsuran_multiguna_tempo WHERE id = %s", (id_tagihan,))
            tagihan = cursor.fetchone()
            if tagihan:
                old_date = tagihan['jatuh_tempo']
                if isinstance(old_date, str):
                    old_date = datetime.strptime(old_date[:10], '%Y-%m-%d').date()
                new_date = datetime.strptime(tanggal_baru[:10], '%Y-%m-%d').date()
                delta_days = (new_date - old_date).days
                
                cursor.execute("UPDATE angsuran_multiguna_tempo SET jatuh_tempo = %s WHERE id = %s", (tanggal_baru, id_tagihan))
                
                # Jika digeser, maka otomatis geser juga bulan-bulan berikutnya
                if delta_days != 0:
                    cursor.execute("""
                        UPDATE angsuran_multiguna_tempo 
                        SET jatuh_tempo = DATE_ADD(jatuh_tempo, INTERVAL %s DAY) 
                        WHERE no_anggota = %s AND tgl_pencairan = %s AND angsuran_ke > %s AND status = 'BELUM BAYAR'
                    """, (delta_days, tagihan['no_anggota'], tagihan['tgl_pencairan'], tagihan['angsuran_ke']))
        elif jenis == 'urgent':
            cursor.execute("UPDATE angsuran_dana_urgent SET tanggal_jatuh_tempo = %s WHERE id = %s", (tanggal_baru, id_tagihan))
        else:
            return jsonify({'status': 'error', 'message': 'Jenis pinjaman tidak valid.'}), 400

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Tanggal jatuh tempo berhasil diubah (bulan berikutnya otomatis menyesuaikan)!'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# =================================================================================
# === MODUL PEMBAYARAN ANGSURAN (LOGIKA BARU) =====================================
# =================================================================================

# === API: MENGAMBIL INFO TAGIHAN TERDEKAT BERDASARKAN ANGGOTA ===
@api_bp.route('/api/info_tagihan/<no_anggota>', methods=['GET'])
def get_info_tagihan(no_anggota):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Cari 1 tagihan Multiguna/Tempo terdekat yang belum lunas (urut dari angsuran terkecil)
        cursor.execute("""
            SELECT * FROM angsuran_multiguna_tempo 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR' 
            ORDER BY angsuran_ke ASC LIMIT 1
        """, (no_anggota,))
        tagihan_utama = cursor.fetchone()

        # Cari 1 tagihan Dana Urgent yang belum lunas
        cursor.execute("""
            SELECT * FROM angsuran_dana_urgent 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR' 
            ORDER BY tgl_pencairan ASC LIMIT 1
        """, (no_anggota,))
        tagihan_urgent = cursor.fetchone()

        tanggal_req = request.args.get('tanggal')
        if tanggal_req:
            try: today = datetime.strptime(tanggal_req[:10], '%Y-%m-%d').date()
            except: today = datetime.now().date()
        else:
            today = datetime.now().date()
        
        # Kalkulasi Denda Multiguna
        if tagihan_utama:
            jatuh_tempo = tagihan_utama.get('jatuh_tempo')
            if jatuh_tempo:
                if isinstance(jatuh_tempo, str):
                    jatuh_tempo = datetime.strptime(jatuh_tempo, '%Y-%m-%d').date()
                last_pay = tagihan_utama.get('tgl_bayar')
                if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
                base_date = jatuh_tempo
                if last_pay and last_pay > jatuh_tempo: base_date = last_pay
                
                od_hari_sisa = (today - base_date).days if today > base_date else 0
                
                sisa_p = float(tagihan_utama.get('tagihan_pokok') or 0) - float(tagihan_utama.get('angsuran_pokok') or 0)
                sisa_m = float(tagihan_utama.get('tagihan_margin') or 0) - float(tagihan_utama.get('angsuran_margin') or 0)
                if sisa_p <= 0.01 and sisa_m <= 0.01:
                    denda = float(tagihan_utama.get('tagihan_denda') or 0) - float(tagihan_utama.get('angsuran_denda') or 0)
                else:
                    add_denda = (sisa_p + sisa_m) * 0.005 * od_hari_sisa
                    denda = float(tagihan_utama.get('tagihan_denda') or 0) - float(tagihan_utama.get('angsuran_denda') or 0) + add_denda
                
                tagihan_utama['od_hari'] = (today - jatuh_tempo).days if today > jatuh_tempo else 0
                tagihan_utama['kalkulasi_denda'] = max(0, denda)
            else:
                tagihan_utama['od_hari'] = 0
                tagihan_utama['kalkulasi_denda'] = 0

        # Kalkulasi Denda Urgent
        if tagihan_urgent:
            jatuh_tempo_urg = tagihan_urgent.get('tanggal_jatuh_tempo')
            if jatuh_tempo_urg:
                if isinstance(jatuh_tempo_urg, str):
                    jatuh_tempo_urg = datetime.strptime(jatuh_tempo_urg, '%Y-%m-%d').date()
                last_pay_urg = tagihan_urgent.get('tgl_bayar')
                if isinstance(last_pay_urg, str) and last_pay_urg: last_pay_urg = datetime.strptime(last_pay_urg[:10], '%Y-%m-%d').date()
                base_date_urg = jatuh_tempo_urg
                if last_pay_urg and last_pay_urg > jatuh_tempo_urg: base_date_urg = last_pay_urg
                
                od_hari_urg_sisa = (today - base_date_urg).days if today > base_date_urg else 0
                
                sisa_p_urg = float(tagihan_urgent.get('tagihan_pokok') or 0) - float(tagihan_urgent.get('angsuran_pokok') or 0)
                sisa_m_urg = float(tagihan_urgent.get('tagihan_margin') or 0) - float(tagihan_urgent.get('angsuran_margin') or 0)
                if sisa_p_urg <= 0.01 and sisa_m_urg <= 0.01:
                    denda_urg = float(tagihan_urgent.get('tagihan_denda') or 0) - float(tagihan_urgent.get('angsuran_denda') or 0)
                else:
                    add_denda_urg = (sisa_p_urg + sisa_m_urg) * 0.005 * od_hari_urg_sisa
                    denda_urg = float(tagihan_urgent.get('tagihan_denda') or 0) - float(tagihan_urgent.get('angsuran_denda') or 0) + add_denda_urg
                    
                tagihan_urgent['od_hari'] = (today - jatuh_tempo_urg).days if today > jatuh_tempo_urg else 0
                tagihan_urgent['kalkulasi_denda'] = max(0, denda_urg)
            else:
                tagihan_urgent['od_hari'] = 0
                tagihan_urgent['kalkulasi_denda'] = 0

        return jsonify({
            'status': 'success', 
            'data_utama': tagihan_utama,
            'data_urgent': tagihan_urgent
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# === API: PROSES PEMBAYARAN FINAL ===
@api_bp.route('/api/bayar_angsuran', methods=['POST'])
def bayar_angsuran():
    conn = None
    cursor = None
    try:
        data = request.get_json(silent=True) or {}

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # === Auto-Migrate Kolom EDC dan Sisa Gaji Jika Belum Ada ===
        try:
            cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'edc'")
            if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN edc VARCHAR(50) DEFAULT '-'")
            cursor.execute("SHOW COLUMNS FROM angsuran_multiguna_tempo LIKE 'sisa_gaji'")
            if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_multiguna_tempo ADD COLUMN sisa_gaji DECIMAL(15,2) DEFAULT 0")
            cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'edc'")
            if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN edc VARCHAR(50) DEFAULT '-'")
            cursor.execute("SHOW COLUMNS FROM angsuran_dana_urgent LIKE 'sisa_gaji'")
            if not cursor.fetchall(): cursor.execute("ALTER TABLE angsuran_dana_urgent ADD COLUMN sisa_gaji DECIMAL(15,2) DEFAULT 0")
        except Exception: pass
        
        # Kita gunakan transaction agar uang aman (jika gagal satu, gagal semua)
        conn.start_transaction()
        tanggal_bayar = data.get('tanggal_bayar') or datetime.now().strftime('%Y-%m-%d')
        nama_anggota = data.get('nama_anggota', 'Anggota')
        
        # 1. Update Tabel Multiguna/Tempo (Jika ada tagihan utama)
        if data.get('bayar_utama') and data.get('id_utama'):
            pokok_utama = parse_float(data.get('nominal_pokok_utama'), 'Nominal Pokok Utama')
            margin_utama = parse_float(data.get('nominal_margin_utama'), 'Nominal Margin Utama')
            denda_utama = parse_float(data.get('nominal_denda_utama'), 'Nominal Denda Utama')
            edc_utama = data.get('edc_utama', '0')
            edc_val = parse_float(edc_utama, 'Biaya EDC Utama')
            sisa_gaji = parse_float(data.get('sisa_gaji_utama'), 'Sisa Gaji Utama')
            angsuran_ke_utama = data.get('angsuran_ke_utama')
            
            cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, tagihan_pokok, tagihan_margin, tagihan_denda, jatuh_tempo, tgl_bayar FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
            row_u = cursor.fetchone()
            if isinstance(row_u, dict):
                prev_p = float(row_u.get('angsuran_pokok') or 0); prev_m = float(row_u.get('angsuran_margin') or 0); prev_d = float(row_u.get('angsuran_denda') or 0)
                tag_p = float(row_u.get('tagihan_pokok') or 0); tag_m = float(row_u.get('tagihan_margin') or 0); tag_d_db = float(row_u.get('tagihan_denda') or 0)
                jt = row_u.get('jatuh_tempo')
                last_pay = row_u.get('tgl_bayar')
            elif row_u:
                prev_p = float(row_u[0] or 0); prev_m = float(row_u[1] or 0); prev_d = float(row_u[2] or 0)
                tag_p = float(row_u[3] or 0); tag_m = float(row_u[4] or 0); tag_d_db = float(row_u[5] or 0)
                jt = row_u[6]
                last_pay = row_u[7]
            else:
                prev_p, prev_m, prev_d, tag_p, tag_m, tag_d_db, jt, last_pay = 0, 0, 0, 0, 0, 0, None, None

            new_p = prev_p + pokok_utama
            new_m = prev_m + margin_utama
            new_d = prev_d + denda_utama
            
            today_d = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_h_sisa = max((today_d - base_date).days, 0) if base_date else 0

            sisa_p_before = max(0, tag_p - prev_p)
            sisa_m_before = max(0, tag_m - prev_m)

            curr_tag_d = tag_d_db
            if sisa_p_before > 0.01 or sisa_m_before > 0.01:
                cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
                cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
                p_row = cursor.fetchone()
                denda_aktif = (p_row['nilai'] == '1') if isinstance(p_row, dict) else (p_row[0] == '1') if p_row else True
                if denda_aktif:
                    curr_tag_d = tag_d_db + ((sisa_p_before + sisa_m_before) * 0.005 * od_h_sisa)
            
            sisa_p_baru = tag_p - new_p
            sisa_m_baru = tag_m - new_m
            sisa_d_baru = curr_tag_d - new_d
            status_baru = 'LUNAS' if sisa_p_baru <= 0.01 and sisa_m_baru <= 0.01 and sisa_d_baru <= 0.01 else 'BELUM BAYAR'

            if angsuran_ke_utama is not None and str(angsuran_ke_utama).strip() != "":
                cursor.execute("""
                    UPDATE angsuran_multiguna_tempo 
                    SET angsuran_pokok = %s, angsuran_margin = %s, angsuran_denda = %s, tagihan_denda = %s, status = %s, tgl_bayar = %s, edc = %s, sisa_gaji = %s, angsuran_ke = %s
                    WHERE id = %s
                """, (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_utama, sisa_gaji, angsuran_ke_utama, data['id_utama']))
            else:
                # Menandai kolom angsuran_pokok & margin sebagai terbayar penuh, lalu status diganti LUNAS
                cursor.execute("""
                    UPDATE angsuran_multiguna_tempo 
                    SET angsuran_pokok = %s, angsuran_margin = %s, angsuran_denda = %s, tagihan_denda = %s, status = %s, tgl_bayar = %s, edc = %s, sisa_gaji = %s
                    WHERE id = %s
                """, (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_utama, sisa_gaji, data['id_utama']))
            
            # === JURNAL OTOMATIS: ANGSURAN UTAMA ===
            cursor.execute("SELECT jenis_pinjaman FROM angsuran_multiguna_tempo WHERE id = %s", (data['id_utama'],))
            row_utama = cursor.fetchone()
            j_pinjaman = row_utama[0] if isinstance(row_utama, tuple) else row_utama['jenis_pinjaman'] if row_utama else 'Multiguna'
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            akun_pendapatan = '4101' if j_pinjaman == 'Multiguna' else '4102'
            
            catat_jurnal(cursor, tanggal_bayar, '1101', f"Terima Angsuran {j_pinjaman} - {nama_anggota}", (pokok_utama + margin_utama + denda_utama), 0)
            if edc_val > 0:
                catat_jurnal(cursor, tanggal_bayar, '1101', f"Terima EDC/Admin {j_pinjaman} - {nama_anggota}", edc_val, 0)
            catat_jurnal(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok {j_pinjaman} - {nama_anggota}", 0, pokok_utama)
            catat_jurnal(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin {j_pinjaman} - {nama_anggota}", 0, margin_utama)
            if denda_utama > 0:
                catat_jurnal(cursor, tanggal_bayar, '4106', f"Pendapatan Denda {j_pinjaman} - {nama_anggota}", 0, denda_utama)
            if edc_val > 0:
                catat_jurnal(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin {j_pinjaman} - {nama_anggota}", 0, edc_val)

            # === LOGIKA OTOMATIS: SIMPANAN WAJIB SAAT BAYAR ANGSURAN ===
            simpanan_wajib = parse_float(data.get('nominal_simpanan_wajib'), 'Titipan Simpanan Wajib')
            if simpanan_wajib > 0:
                no_anggota = data.get('no_anggota')
                nama_anggota = data.get('nama_anggota')
                if not no_anggota:
                    cursor.execute("SELECT no_anggota FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
                    row_no = cursor.fetchone()
                    if row_no:
                        no_anggota = row_no[0] if isinstance(row_no, tuple) else row_no['no_anggota']
                
                if no_anggota:
                    cursor.execute("SELECT id FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE simpanan 
                            SET simpanan_wajib = simpanan_wajib + %s, total_simpanan = total_simpanan + %s
                            WHERE nomor_anggota = %s
                        """, (simpanan_wajib, simpanan_wajib, no_anggota))
                    else:
                        cursor.execute("""
                            INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_wajib, simpanan_pokok, total_simpanan)
                            VALUES (%s, %s, %s, 0, %s)
                        """, (no_anggota, nama_anggota, simpanan_wajib, simpanan_wajib))
                
                # Jurnal untuk Titipan Simpanan Wajib
                catat_jurnal(cursor, tanggal_bayar, '1101', f"Terima Simpanan Wajib - {nama_anggota}", simpanan_wajib, 0)
                catat_jurnal(cursor, tanggal_bayar, '3102', f"Simpanan Wajib - {nama_anggota}", 0, simpanan_wajib)

        # 2. Update Tabel Dana Urgent (Jika centang urgent dipilih)
        if data.get('bayar_urgent') and data.get('id_urgent'):
            pokok_urgent = parse_float(data.get('nominal_pokok_urgent'), 'Nominal Pokok Urgent')
            margin_urgent = parse_float(data.get('nominal_margin_urgent'), 'Nominal Margin Urgent')
            denda_urgent = parse_float(data.get('nominal_denda_urgent'), 'Nominal Denda Urgent')
            edc_urgent = data.get('edc_urgent', '0')
            edc_urg_val = parse_float(edc_urgent, 'Biaya EDC Urgent')
            sisa_gaji = parse_float(data.get('sisa_gaji_urgent'), 'Sisa Gaji Urgent')
            
            cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, tagihan_pokok, tagihan_margin, tagihan_denda, tanggal_jatuh_tempo, tgl_bayar FROM angsuran_dana_urgent WHERE id=%s", (data['id_urgent'],))
            row_u = cursor.fetchone()
            if isinstance(row_u, dict):
                prev_p = float(row_u.get('angsuran_pokok') or 0); prev_m = float(row_u.get('angsuran_margin') or 0); prev_d = float(row_u.get('angsuran_denda') or 0)
                tag_p = float(row_u.get('tagihan_pokok') or 0); tag_m = float(row_u.get('tagihan_margin') or 0); tag_d_db = float(row_u.get('tagihan_denda') or 0)
                jt = row_u.get('tanggal_jatuh_tempo')
                last_pay = row_u.get('tgl_bayar')
            elif row_u:
                prev_p = float(row_u[0] or 0); prev_m = float(row_u[1] or 0); prev_d = float(row_u[2] or 0)
                tag_p = float(row_u[3] or 0); tag_m = float(row_u[4] or 0); tag_d_db = float(row_u[5] or 0)
                jt = row_u[6]
                last_pay = row_u[7]
            else:
                prev_p, prev_m, prev_d, tag_p, tag_m, tag_d_db, jt, last_pay = 0, 0, 0, 0, 0, 0, None, None

            new_p = prev_p + pokok_urgent
            new_m = prev_m + margin_urgent
            new_d = prev_d + denda_urgent
            
            today_d = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_h_sisa = max((today_d - base_date).days, 0) if base_date else 0

            sisa_p_before = max(0, tag_p - prev_p)
            sisa_m_before = max(0, tag_m - prev_m)

            curr_tag_d = tag_d_db
            if sisa_p_before > 0.01 or sisa_m_before > 0.01:
                cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
                cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
                p_row = cursor.fetchone()
                denda_aktif = (p_row['nilai'] == '1') if isinstance(p_row, dict) else (p_row[0] == '1') if p_row else True
                if denda_aktif:
                    curr_tag_d = tag_d_db + ((sisa_p_before + sisa_m_before) * 0.005 * od_h_sisa)
            
            sisa_p_baru = tag_p - new_p
            sisa_m_baru = tag_m - new_m
            sisa_d_baru = curr_tag_d - new_d
            status_baru = 'LUNAS' if sisa_p_baru <= 0.01 and sisa_m_baru <= 0.01 and sisa_d_baru <= 0.01 else 'BELUM BAYAR'

            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok = %s, angsuran_margin = %s, angsuran_denda = %s, tagihan_denda = %s, status = %s, tgl_bayar = %s, edc = %s, sisa_gaji = %s
                WHERE id = %s
            """, (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_urgent, sisa_gaji, data['id_urgent']))

            # === JURNAL OTOMATIS: ANGSURAN URGENT ===
            cursor.execute("SELECT jenis_dana_urgent FROM angsuran_dana_urgent WHERE id = %s", (data['id_urgent'],))
            row_urg = cursor.fetchone()
            j_urgent = row_urg[0] if isinstance(row_urg, tuple) else row_urg['jenis_dana_urgent'] if row_urg else 'Gaji'
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            akun_pendapatan = '4103' if j_urgent == 'Gaji' else '4104'
            
            catat_jurnal(cursor, tanggal_bayar, '1101', f"Terima Angsuran Urgent {j_urgent} - {nama_anggota}", (pokok_urgent + margin_urgent + denda_urgent), 0)
            if edc_urg_val > 0:
                catat_jurnal(cursor, tanggal_bayar, '1101', f"Terima EDC/Admin Urgent {j_urgent} - {nama_anggota}", edc_urg_val, 0)
            catat_jurnal(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok Urgent {j_urgent} - {nama_anggota}", 0, pokok_urgent)
            catat_jurnal(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin Urgent {j_urgent} - {nama_anggota}", 0, margin_urgent)
            if denda_urgent > 0:
                catat_jurnal(cursor, tanggal_bayar, '4107', f"Pendapatan Denda Urgent {j_urgent} - {nama_anggota}", 0, denda_urgent)
            if edc_urg_val > 0:
                catat_jurnal(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin Urgent {j_urgent} - {nama_anggota}", 0, edc_urg_val)

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pembayaran berhasil diproses dan status telah menjadi bayar angsuran!', 'cetak_info': {'id_utama': data.get('id_utama'), 'id_urgent': data.get('id_urgent')}}), 200
        
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@api_bp.route('/api/jurnal', methods=['GET'])
def get_jurnal():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    account_code = request.args.get('account_code')
    filter_type = request.args.get('filter_type') # harian, bulanan, tahunan
    filter_value = request.args.get('filter_value') # contoh: 2026-05-23, 2026-05, 2026
    try:
        query = """
            SELECT j.tanggal, c.account_code, c.account_name, j.keterangan, j.debit, j.kredit
            FROM jurnal_umum j
            JOIN coa c ON j.coa_id = c.id
            WHERE 1=1
        """
        params = []
        
        if account_code:
            query += " AND c.account_code = %s"
            params.append(account_code)
            
        if filter_type and filter_value:
            if filter_type == 'harian':
                query += " AND DATE(j.tanggal) = %s"
                params.append(filter_value)
            elif filter_type == 'bulanan':
                query += " AND DATE_FORMAT(j.tanggal, '%Y-%m') = %s"
                params.append(filter_value)
            elif filter_type == 'tahunan':
                query += " AND YEAR(j.tanggal) = %s"
                params.append(filter_value)
        else:
            if start_date and end_date:
                query += " AND DATE(j.tanggal) BETWEEN %s AND %s"
                params.extend([start_date, end_date])
            elif start_date:
                query += " AND DATE(j.tanggal) >= %s"
                params.append(start_date)
            elif end_date:
                query += " AND DATE(j.tanggal) <= %s"
                params.append(end_date)
            
        query += " ORDER BY j.tanggal DESC, j.id DESC"
        
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()

        # Pastikan tipe data datetime/date dikonversi ke string agar valid menjadi JSON
        for row in data:
            if hasattr(row['tanggal'], 'isoformat'):
                row['tanggal'] = str(row['tanggal'])

        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_bp.route('/api/laba_rugi', methods=['GET'])
def get_laba_rugi():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Pendapatan: Saldo Normal Kredit (Kredit - Debit)
        cursor.execute("SELECT c.account_code, c.account_name, SUM(j.kredit - j.debit) as saldo FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'PENDAPATAN' GROUP BY c.id")
        pendapatan = cursor.fetchall()
        
        # Beban: Saldo Normal Debit (Debit - Kredit)
        cursor.execute("SELECT c.account_code, c.account_name, SUM(j.debit - j.kredit) as saldo FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'BEBAN' GROUP BY c.id")
        beban = cursor.fetchall()
        
        total_pendapatan = sum(item['saldo'] for item in pendapatan if item['saldo'])
        total_beban = sum(item['saldo'] for item in beban if item['saldo'])
        
        return jsonify({'status': 'success', 'data': {'pendapatan': pendapatan, 'beban': beban, 'total_pendapatan': float(total_pendapatan), 'total_beban': float(total_beban), 'laba_bersih': float(total_pendapatan - total_beban)}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: EVALUASI DASHBOARD (Harian, Mingguan, Bulanan) ===
@api_bp.route('/api/evaluasi_dashboard', methods=['GET'])
def evaluasi_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cabang = session.get('cabang', 'GAS')
        today = datetime.now().date()
        
        def get_totals(start, end):
            cursor.execute("""
                SELECT SUM(j.kredit - j.debit) as total
                FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id 
                WHERE c.kategori = 'PENDAPATAN' AND j.cabang = %s AND j.tanggal BETWEEN %s AND %s
            """, (cabang, start, end))
            p = cursor.fetchone()['total'] or 0
            
            cursor.execute("""
                SELECT SUM(j.debit - j.kredit) as total
                FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id 
                WHERE c.kategori = 'BEBAN' AND j.cabang = %s AND j.tanggal BETWEEN %s AND %s
            """, (cabang, start, end))
            b = cursor.fetchone()['total'] or 0
            return float(p), float(b)

        # 1. Harian (Hari ini vs Tanggal sama Bulan Lalu)
        try:
            bulan_lalu_hari_ini = today.replace(month=today.month - 1)
        except ValueError:
            bulan_lalu = today.month - 1 if today.month > 1 else 12
            tahun_lalu = today.year if today.month > 1 else today.year - 1
            last_day = calendar.monthrange(tahun_lalu, bulan_lalu)[1]
            bulan_lalu_hari_ini = today.replace(year=tahun_lalu, month=bulan_lalu, day=min(today.day, last_day))

        harian_now_p, harian_now_b = get_totals(today, today)
        harian_prev_p, harian_prev_b = get_totals(bulan_lalu_hari_ini, bulan_lalu_hari_ini)

        # 2. Mingguan (Minggu ini vs 4 Minggu Lalu)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        start_of_prev_week = start_of_week - timedelta(days=28)
        end_of_prev_week = end_of_week - timedelta(days=28)

        mingguan_now_p, mingguan_now_b = get_totals(start_of_week, end_of_week)
        mingguan_prev_p, mingguan_prev_b = get_totals(start_of_prev_week, end_of_prev_week)

        # 3. Bulanan (Januari s.d Bulan Berjalan)
        bulanan = []
        for month in range(1, today.month + 1):
            start_date = today.replace(month=month, day=1)
            last_day = calendar.monthrange(today.year, month)[1]
            end_date = today.replace(month=month, day=last_day)
            p, b = get_totals(start_date, end_date)
            bulanan.append({
                'bulan': start_date.strftime('%b'),
                'pendapatan': p,
                'beban': b
            })

        # --- TAMBAHAN METRIK UTAMA DASHBOARD ---
        cursor.execute("SELECT IFNULL(SUM(j.debit - j.kredit), 0) as total_kas FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'KAS' AND j.cabang = %s", (cabang,))
        total_kas = cursor.fetchone()['total_kas']

        cursor.execute("SELECT COUNT(no_anggota) as total_anggota FROM identitas WHERE cabang = %s", (cabang,))
        total_anggota = cursor.fetchone()['total_anggota']

        cursor.execute("""
            SELECT IFNULL(SUM(s.total_simpanan), 0) as total_simpanan 
            FROM simpanan s JOIN identitas i ON s.nomor_anggota = i.no_anggota WHERE i.cabang = %s
        """, (cabang,))
        total_simpanan = cursor.fetchone()['total_simpanan']

        cursor.execute("""
            SELECT IFNULL(SUM(a.tagihan_pokok - a.angsuran_pokok), 0) as sisa_piutang 
            FROM angsuran_multiguna_tempo a JOIN identitas i ON a.no_anggota = i.no_anggota 
            WHERE a.status = 'BELUM BAYAR' AND i.cabang = %s
        """, (cabang,))
        piutang_multi = cursor.fetchone()['sisa_piutang']
        
        cursor.execute("""
            SELECT IFNULL(SUM(a.tagihan_pokok - a.angsuran_pokok), 0) as sisa_piutang 
            FROM angsuran_dana_urgent a JOIN identitas i ON a.no_anggota = i.no_anggota 
            WHERE a.status = 'BELUM BAYAR' AND i.cabang = %s
        """, (cabang,))
        piutang_urgent = cursor.fetchone()['sisa_piutang']
        total_piutang = float(piutang_multi) + float(piutang_urgent)

        return jsonify({'status': 'success', 'data': {
            'harian': {'now': {'tanggal': str(today), 'pendapatan': harian_now_p, 'beban': harian_now_b}, 'prev': {'tanggal': str(bulan_lalu_hari_ini), 'pendapatan': harian_prev_p, 'beban': harian_prev_b}},
            'mingguan': {'now': {'start': str(start_of_week), 'end': str(end_of_week), 'pendapatan': mingguan_now_p, 'beban': mingguan_now_b}, 'prev': {'start': str(start_of_prev_week), 'end': str(end_of_prev_week), 'pendapatan': mingguan_prev_p, 'beban': mingguan_prev_b}},
            'bulanan': bulanan,
            'summary_cards': {'total_kas': float(total_kas), 'total_anggota': total_anggota, 'total_simpanan': float(total_simpanan), 'total_piutang': float(total_piutang)}
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# =================================================================================
# === MODUL AKUNTANSI & OPERASIONAL ===============================================
# =================================================================================
    
@api_bp.route('/api/coa/dropdown', methods=['GET'])
def get_coa_dropdown():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Mengambil Data Akun Sumber Dana (Kas/Bank)
        cursor.execute("SELECT id, account_code, account_name FROM coa WHERE kategori = 'KAS' ORDER BY account_code ASC")
        kas = cursor.fetchall()
        
        # Mengambil Data Akun Beban (Operasional, Gaji, THR, dll)
        cursor.execute("SELECT id, account_code, account_name FROM coa WHERE kategori = 'BEBAN' ORDER BY account_code ASC")
        beban = cursor.fetchall()
        
        return jsonify({'status': 'success', 'data': {'kas': kas, 'beban': beban}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_bp.route('/api/expenses', methods=['POST'])
def add_expense():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
            try:
                cursor.execute("SELECT cabang FROM approval_queue LIMIT 1")
                cursor.fetchall()
            except:
                cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Pengeluaran Operasional', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Pengeluaran diajukan! Menunggu Approval dari Manager.'}), 201
        finally:
            cursor.close()
            conn.close()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        tanggal = data.get('tanggal')
        sumber_dana = data.get('coa_sumber_dana_id')
        beban_id = data.get('coa_beban_id')
        nominal = parse_float(data.get('nominal'), 'Nominal Pengeluaran')
        keterangan = data.get('keterangan', '')
        
        # Simpan ke pencatatan pengeluaran operasional cabang
        query = """
            INSERT INTO pengeluaran_operasional (
                tanggal, coa_sumber_dana_id, coa_beban_id, nominal, keterangan
            ) VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (tanggal, sumber_dana, beban_id, nominal, keterangan))
        
        # === JURNAL OTOMATIS: PENGELUARAN KAS & BEBAN OPERASIONAL ===
        query_jurnal_beban = "INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit) VALUES (%s, %s, %s, %s, %s)"
        cursor.execute(query_jurnal_beban, (tanggal, beban_id, f"Beban Operasional: {keterangan}", nominal, 0)) # Debit Beban
        cursor.execute(query_jurnal_beban, (tanggal, sumber_dana, f"Kas Keluar Operasional: {keterangan}", 0, nominal)) # Kredit Kas
        
        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))
            
        conn.commit()
        
        return jsonify({'status': 'success', 'message': 'Jurnal Pengeluaran Operasional berhasil dicatat!'}), 201
        
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# =================================================================================
# === MODUL SIMPANAN ANGGOTA ======================================================
# =================================================================================

@api_bp.route('/api/simpanan', methods=['GET'])
def get_simpanan():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM simpanan ORDER BY total_simpanan DESC")
        data = cursor.fetchall()
        
        total_pokok = sum(float(row['simpanan_pokok']) for row in data)
        total_wajib = sum(float(row['simpanan_wajib']) for row in data)
        total_semua = sum(float(row['total_simpanan']) for row in data)
        
        return jsonify({'status': 'success', 'data': data, 'summary': {
            'total_pokok': total_pokok, 'total_wajib': total_wajib, 'total_semua': total_semua
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_bp.route('/api/penarikan_simpanan', methods=['POST'])
def penarikan_simpanan():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
            try:
                cursor.execute("SELECT cabang FROM approval_queue LIMIT 1")
                cursor.fetchall()
            except:
                cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Penarikan Simpanan', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Penarikan diajukan! Menunggu Approval dari Manager.'}), 200
        finally:
            cursor.close()
            conn.close()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        no_anggota = data.get('no_anggota')
        jenis_simpanan = data.get('jenis_simpanan')
        nominal = parse_float(data.get('nominal'), 'Nominal Penarikan')
        tanggal = datetime.now().strftime('%Y-%m-%d')
        
        if nominal <= 0: raise ValueError("Nominal penarikan harus lebih dari 0.")
            
        cursor.execute("SELECT simpanan_pokok, simpanan_wajib, nama_anggota FROM simpanan WHERE nomor_anggota = %s FOR UPDATE", (no_anggota,))
        simpanan = cursor.fetchone()
        if not simpanan: raise ValueError("Data simpanan anggota tidak ditemukan.")
            
        if jenis_simpanan == 'pokok':
            if nominal > float(simpanan['simpanan_pokok']): raise ValueError("Saldo Simpanan Pokok tidak mencukupi.")
            cursor.execute("UPDATE simpanan SET simpanan_pokok = simpanan_pokok - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (nominal, nominal, no_anggota))
            catat_jurnal(cursor, tanggal, '3101', f"Penarikan Simpanan Pokok - {simpanan['nama_anggota']}", nominal, 0)
        else:
            if nominal > float(simpanan['simpanan_wajib']): raise ValueError("Saldo Simpanan Wajib tidak mencukupi.")
            cursor.execute("UPDATE simpanan SET simpanan_wajib = simpanan_wajib - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (nominal, nominal, no_anggota))
            catat_jurnal(cursor, tanggal, '3102', f"Penarikan Simpanan Wajib - {simpanan['nama_anggota']}", nominal, 0)
            
        catat_jurnal(cursor, tanggal, '1101', f"Penarikan Simpanan (Kas Keluar) - {simpanan['nama_anggota']}", 0, nominal)
        
        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))
            
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Penarikan simpanan berhasil dan kas telah dicatat.'}), 200
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# =================================================================================
# === MODUL PENGELOLAAN ASET OPERASIONAL ==========================================
# =================================================================================

@api_bp.route('/api/aset', methods=['GET', 'POST', 'PUT'])
def kelola_aset():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'GET':
            cursor.execute("SELECT * FROM aset_operasional ORDER BY id DESC")
            data = cursor.fetchall()
            for d in data:
                if hasattr(d.get('tanggal_perolehan'), 'isoformat'):
                    d['tanggal_perolehan'] = str(d['tanggal_perolehan'])
            return jsonify({'status': 'success', 'data': data}), 200
            
        elif request.method == 'POST':
            data = request.json
            nama_aset = data.get('nama_aset')
            lokasi_cabang = data.get('lokasi_cabang')
            tanggal_perolehan = data.get('tanggal_perolehan')
            nilai_aset = parse_float(data.get('nilai_aset'), 'Nilai Aset')
            kondisi = data.get('kondisi')
            keterangan = data.get('keterangan', '')
            
            query = """
                INSERT INTO aset_operasional (
                    nama_aset, lokasi_cabang, tanggal_perolehan, nilai_aset, kondisi, keterangan
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (nama_aset, lokasi_cabang, tanggal_perolehan, nilai_aset, kondisi, keterangan))
            conn.commit()
            
            return jsonify({'status': 'success', 'message': 'Data inventaris aset berhasil dicatat!'}), 201
            
        elif request.method == 'PUT':
            data = request.json
            id_aset = data.get('id')
            kondisi = data.get('kondisi')
            keterangan = data.get('keterangan', '')
            
            if not id_aset or not kondisi:
                return jsonify({'status': 'error', 'message': 'ID Aset dan Kondisi harus diisi!'}), 400
                
            query = """
                UPDATE aset_operasional 
                SET kondisi = %s, keterangan = %s 
                WHERE id = %s
            """
            cursor.execute(query, (kondisi, keterangan, id_aset))
            conn.commit()
            
            return jsonify({'status': 'success', 'message': 'Kondisi aset berhasil diperbarui!'}), 200
            
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# =================================================================================
# === MODUL LAPORAN HARIAN ========================================================
# =================================================================================

@api_bp.route('/api/laporan_harian', methods=['GET'])
def get_laporan_harian():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    tanggal = request.args.get('tanggal', datetime.now().strftime('%Y-%m-%d'))
    try:
        # Pastikan tabel catatan penanganan macet tersedia di database
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS penanganan_macet (
                no_anggota VARCHAR(50) PRIMARY KEY,
                progres_marketing TEXT,
                solusi TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # 1. Tabel Pencairan
        cursor.execute("""
            SELECT 'Multiguna/Tempo' as jenis, no_anggota, nama_anggota, besar_pinjaman as nominal, terima_bersih
            FROM pencairan_multiguna_tempo WHERE DATE(tanggal_cair) = %s
            UNION ALL
            SELECT 'Dana Urgent' as jenis, no_anggota, nama_anggota, jumlah_dana_urgent as nominal, jumlah_dana_urgent as terima_bersih
            FROM pencairan_dana_urgent WHERE DATE(tanggal_pencairan_dana_urgent) = %s
        """, (tanggal, tanggal))
        pencairan = cursor.fetchall()

        # 2. Tabel Angsuran Jatuh Tempo Hari Ini
        cursor.execute("""
            SELECT 'Multiguna/Tempo' as jenis, no_anggota, nama_anggota, angsuran_ke,
                   (tagihan_pokok + tagihan_margin) as total_tagihan, status, tgl_bayar
            FROM angsuran_multiguna_tempo WHERE DATE(jatuh_tempo) = %s
            UNION ALL
            SELECT 'Dana Urgent' as jenis, no_anggota, nama_anggota, 1 as angsuran_ke,
                   (tagihan_pokok + tagihan_margin) as total_tagihan, status, tgl_bayar
            FROM angsuran_dana_urgent WHERE DATE(tanggal_jatuh_tempo) = %s
        """, (tanggal, tanggal))
        angsuran = cursor.fetchall()

        # 3. Tabel Arus Kas (Hanya Akun Kas)
        cursor.execute("""
            SELECT c.account_name, j.keterangan, j.debit as kas_masuk, j.kredit as kas_keluar
            FROM jurnal_umum j
            JOIN coa c ON j.coa_id = c.id
            WHERE DATE(j.tanggal) = %s AND (c.account_code LIKE '11%%' OR c.kategori = 'KAS')
        """, (tanggal,))
        cashflow = cursor.fetchall()

        # 4. Tabel Anggota Macet (1-6 bulan & >6 bulan)
        query_macet = """
            SELECT a.no_anggota, i.nama_anggota, a.jenis_pinjaman, a.jatuh_tempo, 
                   (a.tagihan_pokok + a.tagihan_margin - a.angsuran_pokok - a.angsuran_margin) as tagihan,
                   p.progres_marketing, p.solusi
            FROM (
                SELECT no_anggota, jenis_pinjaman, jatuh_tempo, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin
                FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT no_anggota, jenis_dana_urgent as jenis_pinjaman, tanggal_jatuh_tempo as jatuh_tempo, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin
                FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
            ) a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            LEFT JOIN penanganan_macet p ON a.no_anggota = p.no_anggota
            WHERE DATE(a.jatuh_tempo) < %s
        """
        cursor.execute(query_macet, (tanggal,))
        data_macet = cursor.fetchall()

        target_date = datetime.strptime(tanggal, '%Y-%m-%d').date()
        macet_dict = {}
        for row in data_macet:
            jt = row['jatuh_tempo']
            if isinstance(jt, str): jt = datetime.strptime(jt, '%Y-%m-%d').date()
            
            od_hari = (target_date - jt).days
            na = row['no_anggota']
            
            if na not in macet_dict:
                row['od_hari'] = od_hari
                row['jatuh_tempo'] = str(row['jatuh_tempo'])
                macet_dict[na] = row
            else:
                if od_hari > macet_dict[na]['od_hari']:
                    macet_dict[na]['od_hari'] = od_hari
                macet_dict[na]['tagihan'] += float(row['tagihan'] or 0)

        return jsonify({'status': 'success', 'data': {
            'pencairan': pencairan, 'angsuran': angsuran, 'cashflow': cashflow,
            'macet_1_6': sorted([v for v in macet_dict.values() if 1 <= v['od_hari'] <= 180], key=lambda x: x['od_hari'], reverse=True),
            'macet_lebih_6': sorted([v for v in macet_dict.values() if v['od_hari'] > 180], key=lambda x: x['od_hari'], reverse=True)
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_bp.route('/api/update_penanganan_macet', methods=['POST'])
def update_penanganan_macet():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = "INSERT INTO penanganan_macet (no_anggota, progres_marketing, solusi) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE progres_marketing = VALUES(progres_marketing), solusi = VALUES(solusi)"
        cursor.execute(query, (data.get('no_anggota'), data.get('progres_marketing'), data.get('solusi')))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Catatan penanganan berhasil disimpan!'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()