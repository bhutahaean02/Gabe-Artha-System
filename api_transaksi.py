from flask import Blueprint, request, jsonify, session
from datetime import datetime
import json
from db import get_db_connection
from api_helpers import tambah_bulan, parse_float, parse_int, catat_jurnal

api_transaksi_bp = Blueprint('api_transaksi', __name__)

# === FUNGSI BANTUAN UNTUK MENCATAT JURNAL DENGAN CABANG ===
def catat_jurnal_cabang(cursor, tanggal, account_code, keterangan, debit, kredit, cabang='GAS'):
    if debit == 0 and kredit == 0:
        return
    cursor.execute("SELECT id FROM coa WHERE account_code = %s", (account_code,))
    coa = cursor.fetchone()
    if coa:
        coa_id = coa[0] if isinstance(coa, tuple) else coa['id']
        try:
            cursor.execute("""
                INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (tanggal, coa_id, keterangan, debit, kredit, cabang))
        except Exception:
            try:
                cursor.execute("ALTER TABLE jurnal_umum ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
                cursor.execute("""
                    INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (tanggal, coa_id, keterangan, debit, kredit, cabang))
            except Exception:
                cursor.execute("INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit) VALUES (%s, %s, %s, %s, %s)", (tanggal, coa_id, keterangan, debit, kredit))

# === API: PROSES PENCAIRAN & AUTO-GENERATE JADWAL ANGSURAN ===
@api_transaksi_bp.route('/api/pencairan_multiguna', methods=['POST'])
def proses_pencairan():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    # === SISTEM PENCEGATAN (INTERCEPT) UNTUK APPROVAL ===
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
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
        finally: cursor.close(); conn.close()
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.start_transaction()
        no_anggota = data.get('no_anggota')
        nama_anggota = data.get('nama_anggota')
        jenis_pencairan = data.get('jenis_pencairan')
        tanggal_cair = data.get('tanggal_cair')
        tanggal_gajian = data.get('tanggal_gajian')
        besar_pinjaman = parse_float(data.get('besar_pinjaman'), 'Besar Pinjaman')
        tenor = parse_int(data.get('tenor'), 'Tenor')
        bunga_persen = parse_float(data.get('bunga_persen'), 'Bunga Persen')
        
        potongan_angsuran = parse_float(data.get('potongan_angsuran'), 'Potongan Angsuran')
        potongan_dana_urgent = parse_float(data.get('potongan_dana_urgent'), 'Potongan Dana Urgent')
        biaya_jamsostek = parse_float(data.get('biaya_jamsostek'), 'Biaya Jamsostek')
        potongan_simpanan_pokok = parse_float(data.get('potongan_simpanan_pokok'), 'Potongan Simpanan Pokok')
        potongan_adm = parse_float(data.get('potongan_adm'), 'Potongan Administrasi')
        potongan_dana_kematian = parse_float(data.get('potongan_dana_kematian'), 'Potongan Dana Kematian')
        potongan_ppap = parse_float(data.get('potongan_ppap'), 'Potongan PPAP')
        terima_bersih = parse_float(data.get('terima_bersih'), 'Terima Bersih')
        
        query_pencairan = """
            INSERT INTO pencairan_multiguna_tempo (
                no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, 
                besar_pinjaman, potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, 
                potongan_simpanan_pokok, potongan_adm, potongan_dana_kematian, potongan_ppap, 
                terima_bersih, tenor
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_pencairan, (
            no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, besar_pinjaman, 
            potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, potongan_simpanan_pokok, 
            potongan_adm, potongan_dana_kematian, potongan_ppap, terima_bersih, tenor
        ))
        
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

        if potongan_simpanan_pokok > 0:
            cursor.execute("SELECT id FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
            if cursor.fetchone():
                cursor.execute("UPDATE simpanan SET simpanan_pokok = simpanan_pokok + %s, total_simpanan = total_simpanan + %s WHERE nomor_anggota = %s", (potongan_simpanan_pokok, potongan_simpanan_pokok, no_anggota))
            else:
                cursor.execute("INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_pokok, simpanan_wajib, total_simpanan) VALUES (%s, %s, %s, 0, %s)", (no_anggota, nama_anggota, potongan_simpanan_pokok, potongan_simpanan_pokok))

        cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        cab_row = cursor.fetchone()
        cabang_member = session.get('cabang', 'GAS')
        if cab_row:
            c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
            if c: cabang_member = c

        akun_piutang = '1201' if jenis_pencairan == 'Multiguna' else '1202'
        catat_jurnal_cabang(cursor, tanggal_cair, akun_piutang, f"Pencairan {jenis_pencairan} (Plafon) - {nama_anggota}", besar_pinjaman, 0, cabang_member)
        if terima_bersih > 0: catat_jurnal_cabang(cursor, tanggal_cair, '1101', f"Pencairan {jenis_pencairan} (Terima Bersih) - {nama_anggota}", 0, terima_bersih, cabang_member)
        if potongan_adm > 0: catat_jurnal_cabang(cursor, tanggal_cair, '4105', f"Pendapatan Adm Pinjaman - {nama_anggota}", 0, potongan_adm, cabang_member)
        if potongan_simpanan_pokok > 0: catat_jurnal_cabang(cursor, tanggal_cair, '3101', f"Simpanan Pokok - {nama_anggota}", 0, potongan_simpanan_pokok, cabang_member)
        if potongan_dana_kematian > 0: catat_jurnal_cabang(cursor, tanggal_cair, '2101', f"Titipan Dana Kematian - {nama_anggota}", 0, potongan_dana_kematian, cabang_member)
        if biaya_jamsostek > 0: catat_jurnal_cabang(cursor, tanggal_cair, '2102', f"Titipan Jamsostek - {nama_anggota}", 0, biaya_jamsostek, cabang_member)
        if potongan_ppap > 0: catat_jurnal_cabang(cursor, tanggal_cair, '2103', f"Jaminan PPAP - {nama_anggota}", 0, potongan_ppap, cabang_member)
        
        # Pastikan Akun Dana Temporer Tersedia di Database
        try: cursor.execute("INSERT IGNORE INTO coa (account_code, account_name, kategori) VALUES ('2104', 'Titipan Dana Temporer Top-Up', 'KEWAJIBAN')")
        except: pass

        if potongan_angsuran > 0: 
            # 1. Masukkan potongan ke Dana Temporer
            catat_jurnal_cabang(cursor, tanggal_cair, '2104', f"Dana Temporer Top-Up Masuk - {nama_anggota}", 0, potongan_angsuran, cabang_member)
            
            # 2. Ambil data sisa hutang lama (Pokok & Margin)
            cursor.execute("SELECT SUM(tagihan_pokok) as sisa_pokok, SUM(tagihan_margin) as sisa_margin FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            tagihan_lama = cursor.fetchone()
            sisa_pokok_lama = float(tagihan_lama[0] or 0) if tagihan_lama else 0.0
            sisa_margin_lama = float(tagihan_lama[1] or 0) if tagihan_lama else 0.0
            
            # 3. Keluarkan dari Dana Temporer untuk melunasi Piutang & Margin
            catat_jurnal_cabang(cursor, tanggal_cair, '2104', f"Penyelesaian Dana Temporer - {nama_anggota}", potongan_angsuran, 0, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_cair, akun_piutang, f"Pelunasan Piutang Lama (Top-Up) - {nama_anggota}", 0, sisa_pokok_lama, cabang_member)
            if sisa_margin_lama > 0:
                akun_pendapatan = '4101' if jenis_pencairan == 'Multiguna' else '4102'
                catat_jurnal_cabang(cursor, tanggal_cair, akun_pendapatan, f"Pendapatan Margin Lama (Top-Up) - {nama_anggota}", 0, sisa_margin_lama, cabang_member)
            sisa_denda = potongan_angsuran - sisa_pokok_lama - sisa_margin_lama
            if sisa_denda > 0:
                catat_jurnal_cabang(cursor, tanggal_cair, '4106', f"Pendapatan Denda (Top-Up) - {nama_anggota}", 0, sisa_denda, cabang_member)

            cursor.execute("""
                UPDATE angsuran_multiguna_tempo 
                SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, angsuran_denda = tagihan_denda, status = 'LUNAS TOP-UP', tgl_bayar = %s 
                WHERE no_anggota = %s AND status = 'BELUM BAYAR'
            """, (tanggal_cair, no_anggota))
            
        if potongan_dana_urgent > 0: 
            catat_jurnal_cabang(cursor, tanggal_cair, '1203', f"Potongan Pelunasan Dana Urgent - {nama_anggota}", 0, potongan_dana_urgent, cabang_member)
            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS TOP-UP', tgl_bayar = %s 
                WHERE no_anggota = %s AND status = 'BELUM BAYAR'
            """, (tanggal_cair, no_anggota))

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

# === API: PROSES PENCAIRAN DANA URGENT ===
@api_transaksi_bp.route('/api/pencairan_urgent', methods=['POST'])
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
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
        finally: cursor.close(); conn.close()

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
        margin_dana_urgent = parse_float(data.get('margin_dana_urgent'), 'Margin Dana Urgent')
        
        cursor.execute("""
            INSERT INTO pencairan_dana_urgent (no_anggota, nama_anggota, jenis_dana_urgent, tanggal_pencairan_dana_urgent, tanggal_pembayaran_dana_urgent, jumlah_dana_urgent, margin_dana_urgent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tgl_pembayaran, jumlah_dana_urgent, margin_dana_urgent))
        
        cursor.execute("""
            INSERT INTO angsuran_dana_urgent (no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tanggal_jatuh_tempo, margin, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tgl_pembayaran, margin_dana_urgent, jumlah_dana_urgent, margin_dana_urgent, 0, 0, 0, 0, 0, 0, 0, 0, 'BELUM BAYAR'))

        cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        cab_row = cursor.fetchone()
        cabang_member = session.get('cabang', 'GAS')
        if cab_row:
            c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
            if c: cabang_member = c

        akun_piutang = '1203' if jenis_dana_urgent == 'Gaji' else '1204'
        catat_jurnal_cabang(cursor, tgl_pencairan, akun_piutang, f"Pencairan Dana Urgent {jenis_dana_urgent} - {nama_anggota}", jumlah_dana_urgent, 0, cabang_member)
        catat_jurnal_cabang(cursor, tgl_pencairan, '1101', f"Pencairan Dana Urgent {jenis_dana_urgent} (Kas Keluar) - {nama_anggota}", 0, jumlah_dana_urgent, cabang_member)
        
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

# === API: PENGATURAN SISTEM DENDA (MODE MIGRASI) ===
@api_transaksi_bp.route('/api/pengaturan/denda', methods=['GET', 'POST'])
def pengaturan_denda():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Pastikan tabel ada
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        if request.method == 'GET':
            cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
            row = cursor.fetchone()
            aktif = True
            if row:
                aktif = (row['nilai'] == '1')
            else:
                cursor.execute("INSERT INTO pengaturan (kunci, nilai) VALUES ('denda_aktif', '1')")
                conn.commit()
            return jsonify({'status': 'success', 'denda_aktif': aktif})
        elif request.method == 'POST':
            status_baru = request.json.get('denda_aktif')
            nilai = '1' if status_baru else '0'
            cursor.execute("INSERT INTO pengaturan (kunci, nilai) VALUES ('denda_aktif', %s) ON DUPLICATE KEY UPDATE nilai = %s", (nilai, nilai))
            conn.commit()
            msg = "Sistem Denda AKTIF. Denda otomatis dihitung." if status_baru else "Sistem Denda DIMATIKAN (Mode Migrasi). Denda 0%."
            return jsonify({'status': 'success', 'message': f'Pengaturan disimpan: {msg}'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: INFO TAGIHAN & PEMBAYARAN ANGSURAN ===
@api_transaksi_bp.route('/api/info_tagihan/<no_anggota>', methods=['GET'])
def get_info_tagihan(no_anggota):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR' ORDER BY angsuran_ke ASC LIMIT 1", (no_anggota,))
        tagihan_utama = cursor.fetchone()
        cursor.execute("SELECT * FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR' ORDER BY tgl_pencairan ASC LIMIT 1", (no_anggota,))
        tagihan_urgent = cursor.fetchone()
        today = datetime.now().date()
        
        # Cek Mode Migrasi (Denda Aktif/Tidak)
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        if tagihan_utama:
            jt = tagihan_utama.get('jatuh_tempo')
            if jt:
                jt = datetime.strptime(jt, '%Y-%m-%d').date() if isinstance(jt, str) else jt
                od_hari = max((today - jt).days, 0)
                tagihan_utama['od_hari'] = od_hari
                tagihan_utama['kalkulasi_denda'] = ((float(tagihan_utama['tagihan_pokok'] or 0) + float(tagihan_utama['tagihan_margin'] or 0)) * 0.05 * od_hari) if denda_aktif else 0
            else:
                tagihan_utama['od_hari'] = 0
                tagihan_utama['kalkulasi_denda'] = 0

        if tagihan_urgent:
            jt_urg = tagihan_urgent.get('tanggal_jatuh_tempo')
            if jt_urg:
                jt_urg = datetime.strptime(jt_urg, '%Y-%m-%d').date() if isinstance(jt_urg, str) else jt_urg
                od_hari_urg = max((today - jt_urg).days, 0)
                tagihan_urgent['od_hari'] = od_hari_urg
                tagihan_urgent['kalkulasi_denda'] = ((float(tagihan_urgent['tagihan_pokok'] or 0) + float(tagihan_urgent['tagihan_margin'] or 0)) * 0.05 * od_hari_urg) if denda_aktif else 0
            else:
                tagihan_urgent['od_hari'] = 0
                tagihan_urgent['kalkulasi_denda'] = 0

        return jsonify({'status': 'success', 'data_utama': tagihan_utama, 'data_urgent': tagihan_urgent}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@api_transaksi_bp.route('/api/bayar_angsuran', methods=['POST'])
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
        
        conn.start_transaction()
        tanggal_bayar = datetime.now().strftime('%Y-%m-%d')
        nama_anggota = data.get('nama_anggota', 'Anggota')
        
        no_angg_byr = data.get('no_anggota')
        if not no_angg_byr and data.get('id_utama'):
            cursor.execute("SELECT no_anggota FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
            r = cursor.fetchone(); no_angg_byr = r[0] if isinstance(r, tuple) else r['no_anggota'] if r else None
        if not no_angg_byr and data.get('id_urgent'):
            cursor.execute("SELECT no_anggota FROM angsuran_dana_urgent WHERE id=%s", (data['id_urgent'],))
            r = cursor.fetchone(); no_angg_byr = r[0] if isinstance(r, tuple) else r['no_anggota'] if r else None
            
        cabang_member = session.get('cabang', 'GAS')
        if no_angg_byr:
            cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_angg_byr,))
            cab_row = cursor.fetchone()
            if cab_row:
                c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
                if c: cabang_member = c
        
        if data.get('bayar_utama') and data.get('id_utama'):
            pokok = parse_float(data.get('nominal_pokok_utama'), 'Nominal Pokok Utama')
            margin = parse_float(data.get('nominal_margin_utama'), 'Nominal Margin Utama')
            denda = parse_float(data.get('nominal_denda_utama'), 'Nominal Denda Utama')
            edc_str = data.get('edc_utama', '0')
            edc_val = parse_float(edc_str, 'Biaya EDC Utama')
            sisa_gaji = parse_float(data.get('sisa_gaji_utama'), 'Sisa Gaji Utama')
            angsuran_ke_utama = data.get('angsuran_ke_utama')
            
            if angsuran_ke_utama is not None and str(angsuran_ke_utama).strip() != "":
                cursor.execute("""
                    UPDATE angsuran_multiguna_tempo SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, status='LUNAS', tgl_bayar=%s, edc=%s, sisa_gaji=%s, angsuran_ke=%s WHERE id=%s
                """, (pokok, margin, denda, tanggal_bayar, edc_str, sisa_gaji, angsuran_ke_utama, data['id_utama']))
            else:
                cursor.execute("UPDATE angsuran_multiguna_tempo SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, status='LUNAS', tgl_bayar=%s, edc=%s, sisa_gaji=%s WHERE id=%s", (pokok, margin, denda, tanggal_bayar, edc_str, sisa_gaji, data['id_utama']))
            
            cursor.execute("SELECT jenis_pinjaman FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
            row_utama = cursor.fetchone()
            j_pinjaman = row_utama[0] if isinstance(row_utama, tuple) else row_utama['jenis_pinjaman'] if row_utama else 'Multiguna'
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            akun_pendapatan = '4101' if j_pinjaman == 'Multiguna' else '4102'
            
            catat_jurnal_cabang(cursor, tanggal_bayar, '1101', f"Terima Angsuran {j_pinjaman} - {nama_anggota}", (pokok+margin+denda+edc_val), 0, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok {j_pinjaman} - {nama_anggota}", 0, pokok, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin {j_pinjaman} - {nama_anggota}", 0, margin, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4106', f"Pendapatan Denda {j_pinjaman} - {nama_anggota}", 0, denda, cabang_member)
            if edc_val > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin {j_pinjaman} - {nama_anggota}", 0, edc_val, cabang_member)

            simpanan_wajib = parse_float(data.get('nominal_simpanan_wajib'), 'Titipan Simpanan Wajib')
            if simpanan_wajib > 0:
                no = data.get('no_anggota')
                if not no:
                    cursor.execute("SELECT no_anggota FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
                    row_no = cursor.fetchone()
                    if row_no:
                        no = row_no[0] if isinstance(row_no, tuple) else row_no['no_anggota']
                
                if no:
                    cursor.execute("SELECT id FROM simpanan WHERE nomor_anggota=%s", (no,))
                    if cursor.fetchone(): cursor.execute("UPDATE simpanan SET simpanan_wajib=simpanan_wajib+%s, total_simpanan=total_simpanan+%s WHERE nomor_anggota=%s", (simpanan_wajib, simpanan_wajib, no))
                    else: cursor.execute("INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_wajib, simpanan_pokok, total_simpanan) VALUES (%s, %s, %s, 0, %s)", (no, nama_anggota, simpanan_wajib, simpanan_wajib))
                    catat_jurnal_cabang(cursor, tanggal_bayar, '1101', f"Terima Simpanan Wajib - {nama_anggota}", simpanan_wajib, 0, cabang_member)
                    catat_jurnal_cabang(cursor, tanggal_bayar, '3102', f"Simpanan Wajib - {nama_anggota}", 0, simpanan_wajib, cabang_member)

        if data.get('bayar_urgent') and data.get('id_urgent'):
            pokok = parse_float(data.get('nominal_pokok_urgent'), 'Nominal Pokok Urgent')
            margin = parse_float(data.get('nominal_margin_urgent'), 'Nominal Margin Urgent')
            denda = parse_float(data.get('nominal_denda_urgent'), 'Nominal Denda Urgent')
            edc_urg_str = data.get('edc_urgent', '0')
            edc_urg_val = parse_float(edc_urg_str, 'Biaya EDC Urgent')
            sisa_gaji = parse_float(data.get('sisa_gaji_urgent'), 'Sisa Gaji Urgent')
            cursor.execute("UPDATE angsuran_dana_urgent SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, status='LUNAS', tgl_bayar=%s, edc=%s, sisa_gaji=%s WHERE id=%s", (pokok, margin, denda, tanggal_bayar, edc_urg_str, sisa_gaji, data['id_urgent']))
            
            cursor.execute("SELECT jenis_dana_urgent FROM angsuran_dana_urgent WHERE id=%s", (data['id_urgent'],))
            row_urg = cursor.fetchone()
            j_urgent = row_urg[0] if isinstance(row_urg, tuple) else row_urg['jenis_dana_urgent'] if row_urg else 'Gaji'
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            akun_pendapatan = '4103' if j_urgent == 'Gaji' else '4104'
            
            catat_jurnal_cabang(cursor, tanggal_bayar, '1101', f"Terima Angsuran Urgent {j_urgent} - {nama_anggota}", (pokok+margin+denda+edc_urg_val), 0, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok Urgent {j_urgent} - {nama_anggota}", 0, pokok, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin Urgent {j_urgent} - {nama_anggota}", 0, margin, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4107', f"Pendapatan Denda Urgent {j_urgent} - {nama_anggota}", 0, denda, cabang_member)
            if edc_urg_val > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin Urgent {j_urgent} - {nama_anggota}", 0, edc_urg_val, cabang_member)

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

# === API: SIMPANAN & PENARIKAN ===
@api_transaksi_bp.route('/api/simpanan', methods=['GET'])
def get_simpanan():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        cursor.execute("""
            SELECT s.* FROM simpanan s
            JOIN identitas i ON s.nomor_anggota = i.no_anggota
            WHERE i.cabang = %s
            ORDER BY s.total_simpanan DESC
        """, (cabang,))
        data = cursor.fetchall()
        total_pokok = sum(float(row['simpanan_pokok']) for row in data)
        total_wajib = sum(float(row['simpanan_wajib']) for row in data)
        total_semua = sum(float(row['total_simpanan']) for row in data)
        return jsonify({'status': 'success', 'data': data, 'summary': {'total_pokok': total_pokok, 'total_wajib': total_wajib, 'total_semua': total_semua}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_transaksi_bp.route('/api/penarikan_simpanan', methods=['POST'])
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
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
        finally: cursor.close(); conn.close()

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
            
        cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        cab_row = cursor.fetchone()
        cabang_member = session.get('cabang', 'GAS')
        if cab_row:
            c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
            if c: cabang_member = c

        if jenis_simpanan == 'pokok':
            if nominal > float(simpanan['simpanan_pokok']): raise ValueError("Saldo Simpanan Pokok tidak mencukupi.")
            cursor.execute("UPDATE simpanan SET simpanan_pokok = simpanan_pokok - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (nominal, nominal, no_anggota))
            catat_jurnal_cabang(cursor, tanggal, '3101', f"Penarikan Simpanan Pokok - {simpanan['nama_anggota']}", nominal, 0, cabang_member)
        else:
            if nominal > float(simpanan['simpanan_wajib']): raise ValueError("Saldo Simpanan Wajib tidak mencukupi.")
            cursor.execute("UPDATE simpanan SET simpanan_wajib = simpanan_wajib - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (nominal, nominal, no_anggota))
            catat_jurnal_cabang(cursor, tanggal, '3102', f"Penarikan Simpanan Wajib - {simpanan['nama_anggota']}", nominal, 0, cabang_member)
            
        catat_jurnal_cabang(cursor, tanggal, '1101', f"Penarikan Simpanan (Kas Keluar) - {simpanan['nama_anggota']}", 0, nominal, cabang_member)
        
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
        cursor.close()
        conn.close()

# === API: UPDATE TANGGAL JATUH TEMPO ===
@api_transaksi_bp.route('/api/update_jatuh_tempo', methods=['POST'])
def update_jatuh_tempo():
    data = request.json
    jenis = data.get('jenis_pinjaman')
    id_tagihan = data.get('id_tagihan')
    tanggal_baru = data.get('tanggal_baru')

    if not jenis or not id_tagihan or not tanggal_baru:
        return jsonify({'status': 'error', 'message': 'Data tidak lengkap.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if jenis == 'utama':
            cursor.execute("UPDATE angsuran_multiguna_tempo SET jatuh_tempo = %s WHERE id = %s", (tanggal_baru, id_tagihan))
        elif jenis == 'urgent':
            cursor.execute("UPDATE angsuran_dana_urgent SET tanggal_jatuh_tempo = %s WHERE id = %s", (tanggal_baru, id_tagihan))
        else:
            return jsonify({'status': 'error', 'message': 'Jenis pinjaman tidak valid.'}), 400

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Tanggal jatuh tempo berhasil diubah!'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: CEK SISA TAGIHAN UNTUK TOP-UP ===
@api_transaksi_bp.route('/api/cek_sisa_tagihan/<no_anggota>', methods=['GET'])
def cek_sisa_tagihan(no_anggota):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Kalkulasi Sisa Pinjaman Multiguna/Tempo
        cursor.execute("""
            SELECT SUM(tagihan_pokok) as sisa_pokok, SUM(tagihan_margin) as sisa_margin
            FROM angsuran_multiguna_tempo 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        multiguna = cursor.fetchone()
        
        # 2. Kalkulasi Sisa Pinjaman Dana Urgent
        cursor.execute("""
            SELECT SUM(tagihan_pokok) as sisa_pokok, SUM(tagihan_margin) as sisa_margin
            FROM angsuran_dana_urgent 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        urgent = cursor.fetchone()
        
        today = datetime.now().date()
        denda_multiguna = 0
        denda_urgent = 0
        
        # Cek Mode Migrasi
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        if denda_aktif:
            # Kalkulasi Denda Keterlambatan Multiguna
            cursor.execute("SELECT jatuh_tempo, tagihan_pokok, tagihan_margin FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                jt = row['jatuh_tempo']
                if isinstance(jt, str): jt = datetime.strptime(jt, '%Y-%m-%d').date()
                if today > jt: denda_multiguna += (float(row['tagihan_pokok']) + float(row['tagihan_margin'])) * 0.05 * (today - jt).days

            # Kalkulasi Denda Keterlambatan Urgent
            cursor.execute("SELECT tanggal_jatuh_tempo, tagihan_pokok, tagihan_margin FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                jt = row['tanggal_jatuh_tempo']
                if isinstance(jt, str): jt = datetime.strptime(jt, '%Y-%m-%d').date()
                if today > jt: denda_urgent += (float(row['tagihan_pokok']) + float(row['tagihan_margin'])) * 0.05 * (today - jt).days

        total_multiguna = float(multiguna['sisa_pokok'] or 0) + float(multiguna['sisa_margin'] or 0) + denda_multiguna
        total_urgent = float(urgent['sisa_pokok'] or 0) + float(urgent['sisa_margin'] or 0) + denda_urgent

        return jsonify({
            'status': 'success',
            'data': {
                'multiguna': {
                    'sisa_pokok': float(multiguna['sisa_pokok'] or 0), 'sisa_margin': float(multiguna['sisa_margin'] or 0),
                    'denda': denda_multiguna, 'total_pelunasan': total_multiguna
                },
                'urgent': {
                    'sisa_pokok': float(urgent['sisa_pokok'] or 0), 'sisa_margin': float(urgent['sisa_margin'] or 0),
                    'denda': denda_urgent, 'total_pelunasan': total_urgent
                }
            }
        }), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: PUSAT DATA APPROVAL MANAGER ===
@api_transaksi_bp.route('/api/approval_queue', methods=['GET'])
def get_approval_queue():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang') or 'GAS'
    role = session.get('role')
    filter_cabang = request.args.get('cabang')
    try:
        # Tabel otomatis dibuat jika belum ada agar tidak error
        cursor.execute("CREATE TABLE IF NOT EXISTS approval_queue (id INT AUTO_INCREMENT PRIMARY KEY, tipe_transaksi VARCHAR(50), data_payload TEXT, diajukan_oleh VARCHAR(50), tanggal_pengajuan DATETIME DEFAULT CURRENT_TIMESTAMP, status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', cabang VARCHAR(50))")
        try:
            cursor.execute("SELECT cabang FROM approval_queue LIMIT 1")
            cursor.fetchall()
        except:
            cursor.execute("ALTER TABLE approval_queue ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
        
        query_pending = "SELECT * FROM approval_queue WHERE status = 'PENDING'"
        query_history = "SELECT * FROM approval_queue WHERE status != 'PENDING'"
        params_pending = []
        params_history = []
        
        if role not in ['Super Admin', 'Manager']:
            query_pending += " AND (cabang = %s OR cabang IS NULL OR cabang = 'GAS')"
            query_history += " AND (cabang = %s OR cabang IS NULL OR cabang = 'GAS')"
            params_pending.append(cabang)
            params_history.append(cabang)
        elif filter_cabang and filter_cabang != 'ALL':
            query_pending += " AND cabang = %s"
            query_history += " AND cabang = %s"
            params_pending.append(filter_cabang)
            params_history.append(filter_cabang)
            
        query_pending += " ORDER BY id ASC"
        query_history += " ORDER BY id DESC LIMIT 100"
        
        cursor.execute(query_pending, tuple(params_pending))
        pending = cursor.fetchall()
        for d in pending: d['tanggal_pengajuan'] = str(d['tanggal_pengajuan'])
        
        cursor.execute(query_history, tuple(params_history))
        history = cursor.fetchall()
        for d in history: d['tanggal_pengajuan'] = str(d['tanggal_pengajuan'])
        
        return jsonify({'status': 'success', 'data': pending, 'history': history}), 200
    finally: cursor.close(); conn.close()

@api_transaksi_bp.route('/api/approval_reject', methods=['POST'])
def reject_approval():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE approval_queue SET status = 'REJECTED' WHERE id = %s", (data.get('id'),))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Transaksi resmi ditolak dan dihapus dari antrean.'}), 200
    finally: cursor.close(); conn.close()

# === API: SINKRONISASI DATA MANUAL (DARI MYSQL) KE JURNAL ===
@api_transaksi_bp.route('/api/sync_jurnal_import', methods=['POST'])
def sync_jurnal_import():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        
        # 1. Sync Pencairan Multiguna (berdasarkan angsuran)
        cursor.execute("""
            SELECT DISTINCT no_anggota, nama_anggota, jenis_pinjaman, tgl_pencairan, besar_pinjaman 
            FROM angsuran_multiguna_tempo 
            WHERE besar_pinjaman > 0 AND tgl_pencairan IS NOT NULL
        """)
        pinjaman_list = cursor.fetchall()
        
        for p in pinjaman_list:
            akun_piutang = '1201' if p['jenis_pinjaman'] == 'Multiguna' else '1202'
            ket_plafon = f"Pencairan {p['jenis_pinjaman']} (Plafon) - {p['nama_anggota']} (Migrasi)"
            
            cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (p['no_anggota'],))
            cab_row = cursor.fetchone()
            cabang_member = session.get('cabang', 'GAS')
            if cab_row:
                c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
                if c: cabang_member = c

            # Cek apakah jurnal pencairan ini sudah ada
            cursor.execute("SELECT id FROM jurnal_umum WHERE keterangan = %s AND tanggal = %s", (ket_plafon, p['tgl_pencairan']))
            if not cursor.fetchone():
                catat_jurnal_cabang(cursor, p['tgl_pencairan'], akun_piutang, ket_plafon, p['besar_pinjaman'], 0, cabang_member)
                catat_jurnal_cabang(cursor, p['tgl_pencairan'], '1101', f"Pencairan {p['jenis_pinjaman']} (Kas Keluar) - {p['nama_anggota']} (Migrasi)", 0, p['besar_pinjaman'], cabang_member)

        # 2. Sync Pembayaran Angsuran Multiguna yang LUNAS
        cursor.execute("""
            SELECT id, no_anggota, nama_anggota, jenis_pinjaman, tgl_bayar, angsuran_pokok, angsuran_margin, angsuran_denda 
            FROM angsuran_multiguna_tempo 
            WHERE status = 'LUNAS' AND tgl_bayar IS NOT NULL
        """)
        angsuran_list = cursor.fetchall()
        
        for a in angsuran_list:
            j_pinjaman = a['jenis_pinjaman'] or 'Multiguna'
            ket_terima = f"Terima Angsuran {j_pinjaman} - {a['nama_anggota']} (Migrasi)"
            
            cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (a['no_anggota'],))
            cab_row = cursor.fetchone()
            cabang_member = session.get('cabang', 'GAS')
            if cab_row:
                c = cab_row[0] if isinstance(cab_row, tuple) else cab_row.get('cabang')
                if c: cabang_member = c

            # Cek apakah pembayaran ini sudah ada di jurnal
            cursor.execute("SELECT id FROM jurnal_umum WHERE keterangan = %s AND tanggal = %s", (ket_terima, a['tgl_bayar']))
            if not cursor.fetchone():
                pokok = float(a['angsuran_pokok'] or 0)
                margin = float(a['angsuran_margin'] or 0)
                denda = float(a['angsuran_denda'] or 0)
                total = pokok + margin + denda
                
                akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
                akun_pend = '4101' if j_pinjaman == 'Multiguna' else '4102'
                
                catat_jurnal_cabang(cursor, a['tgl_bayar'], '1101', ket_terima, total, 0, cabang_member)
                if pokok > 0: catat_jurnal_cabang(cursor, a['tgl_bayar'], akun_piutang, f"Pelunasan Pokok {j_pinjaman} - {a['nama_anggota']} (Migrasi)", 0, pokok, cabang_member)
                if margin > 0: catat_jurnal_cabang(cursor, a['tgl_bayar'], akun_pend, f"Pendapatan Margin {j_pinjaman} - {a['nama_anggota']} (Migrasi)", 0, margin, cabang_member)
                if denda > 0: catat_jurnal_cabang(cursor, a['tgl_bayar'], '4106', f"Pendapatan Denda {j_pinjaman} - {a['nama_anggota']} (Migrasi)", 0, denda, cabang_member)

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Sinkronisasi Jurnal Berhasil! Data lama dari MySQL kini sudah masuk ke Buku Besar, Neraca, dan Laba/Rugi.'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()