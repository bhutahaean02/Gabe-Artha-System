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
        
        tanggal_req = request.args.get('tanggal')
        if tanggal_req:
            try: today = datetime.strptime(tanggal_req[:10], '%Y-%m-%d').date()
            except: today = datetime.now().date()
        else:
            today = datetime.now().date()
        
        # Cek Mode Migrasi (Denda Aktif/Tidak)
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        if tagihan_utama:
            jt = tagihan_utama.get('jatuh_tempo')
            if jt:
                jt = datetime.strptime(str(jt)[:10], '%Y-%m-%d').date() if isinstance(jt, str) else jt
                last_pay = tagihan_utama.get('tgl_bayar')
                if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(str(last_pay)[:10], '%Y-%m-%d').date()
                base_date = jt
                if last_pay and last_pay > jt: base_date = last_pay
                
                od_hari_sisa = max((today - base_date).days, 0)
                tagihan_utama['od_hari'] = max((today - jt).days, 0)
                
                sisa_p = float(tagihan_utama.get('tagihan_pokok') or 0) - float(tagihan_utama.get('angsuran_pokok') or 0)
                sisa_m = float(tagihan_utama.get('tagihan_margin') or 0) - float(tagihan_utama.get('angsuran_margin') or 0)
                if sisa_p <= 0.01 and sisa_m <= 0.01:
                    d_kalk = float(tagihan_utama.get('tagihan_denda') or 0) - float(tagihan_utama.get('angsuran_denda') or 0)
                else:
                    add_denda = (sisa_p + sisa_m) * 0.005 * od_hari_sisa
                    d_kalk = float(tagihan_utama.get('tagihan_denda') or 0) - float(tagihan_utama.get('angsuran_denda') or 0) + add_denda
                tagihan_utama['kalkulasi_denda'] = max(0, d_kalk) if denda_aktif else 0
            else:
                tagihan_utama['od_hari'] = 0
                tagihan_utama['kalkulasi_denda'] = 0

        if tagihan_urgent:
            jt_urg = tagihan_urgent.get('tanggal_jatuh_tempo')
            if jt_urg:
                jt_urg = datetime.strptime(str(jt_urg)[:10], '%Y-%m-%d').date() if isinstance(jt_urg, str) else jt_urg
                last_pay_urg = tagihan_urgent.get('tgl_bayar')
                if isinstance(last_pay_urg, str) and last_pay_urg: last_pay_urg = datetime.strptime(str(last_pay_urg)[:10], '%Y-%m-%d').date()
                base_date_urg = jt_urg
                if last_pay_urg and last_pay_urg > jt_urg: base_date_urg = last_pay_urg
                
                od_hari_urg_sisa = max((today - base_date_urg).days, 0)
                tagihan_urgent['od_hari'] = max((today - jt_urg).days, 0)
                
                sisa_p_urg = float(tagihan_urgent.get('tagihan_pokok') or 0) - float(tagihan_urgent.get('angsuran_pokok') or 0)
                sisa_m_urg = float(tagihan_urgent.get('tagihan_margin') or 0) - float(tagihan_urgent.get('angsuran_margin') or 0)
                if sisa_p_urg <= 0.01 and sisa_m_urg <= 0.01:
                    d_kalk_urg = float(tagihan_urgent.get('tagihan_denda') or 0) - float(tagihan_urgent.get('angsuran_denda') or 0)
                else:
                    add_denda_urg = (sisa_p_urg + sisa_m_urg) * 0.005 * od_hari_urg_sisa
                    d_kalk_urg = float(tagihan_urgent.get('tagihan_denda') or 0) - float(tagihan_urgent.get('angsuran_denda') or 0) + add_denda_urg
                tagihan_urgent['kalkulasi_denda'] = max(0, d_kalk_urg) if denda_aktif else 0
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
        tanggal_bayar = data.get('tanggal_bayar') or datetime.now().strftime('%Y-%m-%d')
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
            
            cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, tagihan_pokok, tagihan_margin, tagihan_denda, jatuh_tempo, tgl_bayar FROM angsuran_multiguna_tempo WHERE id=%s", (data['id_utama'],))
            row_u = cursor.fetchone()
            
            if row_u:
                prev_p = float(row_u['angsuran_pokok'] if isinstance(row_u, dict) else row_u[0] or 0)
                prev_m = float(row_u['angsuran_margin'] if isinstance(row_u, dict) else row_u[1] or 0)
                prev_d = float(row_u['angsuran_denda'] if isinstance(row_u, dict) else row_u[2] or 0)
                tag_p = float(row_u['tagihan_pokok'] if isinstance(row_u, dict) else row_u[3] or 0)
                tag_m = float(row_u['tagihan_margin'] if isinstance(row_u, dict) else row_u[4] or 0)
                tag_d_db = float(row_u['tagihan_denda'] if isinstance(row_u, dict) else row_u[5] or 0)
                jt = row_u['jatuh_tempo'] if isinstance(row_u, dict) else row_u[6]
                last_pay = row_u['tgl_bayar'] if isinstance(row_u, dict) else row_u[7]
            else:
                prev_p, prev_m, prev_d, tag_p, tag_m, tag_d_db, jt, last_pay = 0, 0, 0, 0, 0, 0, None, None
                
            new_p = prev_p + pokok
            new_m = prev_m + margin
            new_d = prev_d + denda
            
            today_d = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_h_sisa = max((today_d - base_date).days, 0) if base_date else 0
            
            cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
            cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
            p_row = cursor.fetchone()
            denda_aktif = (p_row['nilai'] == '1') if isinstance(p_row, dict) else (p_row[0] == '1') if p_row else True
            
            curr_tag_d = tag_d_db
            sisa_p_before = max(0, tag_p - prev_p)
            sisa_m_before = max(0, tag_m - prev_m)
            if sisa_p_before > 0.01 or sisa_m_before > 0.01:
                if denda_aktif:
                    curr_tag_d = tag_d_db + ((sisa_p_before + sisa_m_before) * 0.005 * od_h_sisa)
            
            sisa_p_baru = tag_p - new_p
            sisa_m_baru = tag_m - new_m
            sisa_d_baru = curr_tag_d - new_d
            status_baru = 'LUNAS' if sisa_p_baru <= 0.01 and sisa_m_baru <= 0.01 and sisa_d_baru <= 0.01 else 'BELUM BAYAR'

            if angsuran_ke_utama is not None and str(angsuran_ke_utama).strip() != "":
                cursor.execute("""
                    UPDATE angsuran_multiguna_tempo SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, tagihan_denda=%s, status=%s, tgl_bayar=%s, edc=%s, sisa_gaji=%s, angsuran_ke=%s WHERE id=%s
                """, (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_str, sisa_gaji, angsuran_ke_utama, data['id_utama']))
            else:
                cursor.execute("UPDATE angsuran_multiguna_tempo SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, tagihan_denda=%s, status=%s, tgl_bayar=%s, edc=%s, sisa_gaji=%s WHERE id=%s", (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_str, sisa_gaji, data['id_utama']))
            
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
            
            cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, tagihan_pokok, tagihan_margin, tagihan_denda, tanggal_jatuh_tempo, tgl_bayar FROM angsuran_dana_urgent WHERE id=%s", (data['id_urgent'],))
            row_u = cursor.fetchone()
            if row_u:
                prev_p = float(row_u['angsuran_pokok'] if isinstance(row_u, dict) else row_u[0] or 0)
                prev_m = float(row_u['angsuran_margin'] if isinstance(row_u, dict) else row_u[1] or 0)
                prev_d = float(row_u['angsuran_denda'] if isinstance(row_u, dict) else row_u[2] or 0)
                tag_p = float(row_u['tagihan_pokok'] if isinstance(row_u, dict) else row_u[3] or 0)
                tag_m = float(row_u['tagihan_margin'] if isinstance(row_u, dict) else row_u[4] or 0)
                tag_d_db = float(row_u['tagihan_denda'] if isinstance(row_u, dict) else row_u[5] or 0)
                jt = row_u['tanggal_jatuh_tempo'] if isinstance(row_u, dict) else row_u[6]
                last_pay = row_u['tgl_bayar'] if isinstance(row_u, dict) else row_u[7]
            else:
                prev_p, prev_m, prev_d, tag_p, tag_m, tag_d_db, jt, last_pay = 0, 0, 0, 0, 0, 0, None, None
                
            new_p = prev_p + pokok
            new_m = prev_m + margin
            new_d = prev_d + denda
            
            today_d = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_h_sisa = max((today_d - base_date).days, 0) if base_date else 0
            
            cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
            cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
            p_row = cursor.fetchone()
            denda_aktif = (p_row['nilai'] == '1') if isinstance(p_row, dict) else (p_row[0] == '1') if p_row else True
            
            curr_tag_d = tag_d_db
            sisa_p_before = max(0, tag_p - prev_p)
            sisa_m_before = max(0, tag_m - prev_m)
            if sisa_p_before > 0.01 or sisa_m_before > 0.01:
                if denda_aktif:
                    curr_tag_d = tag_d_db + ((sisa_p_before + sisa_m_before) * 0.005 * od_h_sisa)
            
            sisa_p_baru = tag_p - new_p
            sisa_m_baru = tag_m - new_m
            sisa_d_baru = curr_tag_d - new_d
            status_baru = 'LUNAS' if sisa_p_baru <= 0.01 and sisa_m_baru <= 0.01 and sisa_d_baru <= 0.01 else 'BELUM BAYAR'

            cursor.execute("UPDATE angsuran_dana_urgent SET angsuran_pokok=%s, angsuran_margin=%s, angsuran_denda=%s, tagihan_denda=%s, status=%s, tgl_bayar=%s, edc=%s, sisa_gaji=%s WHERE id=%s", (new_p, new_m, new_d, curr_tag_d, status_baru, tanggal_bayar, edc_urg_str, sisa_gaji, data['id_urgent']))
            
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
        return jsonify({'status': 'success', 'message': 'Tanggal jatuh tempo berhasil diubah (jadwal bulan berikutnya otomatis menyesuaikan)!'}), 200
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
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin
            FROM angsuran_multiguna_tempo 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        multiguna = cursor.fetchone()
        
        # 2. Kalkulasi Sisa Pinjaman Dana Urgent
        cursor.execute("""
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin
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
            cursor.execute("SELECT jatuh_tempo, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, tagihan_denda, angsuran_denda FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                jt = row['jatuh_tempo']
                if isinstance(jt, str): jt = datetime.strptime(str(jt)[:10], '%Y-%m-%d').date()
                
                sisa_p = float(row['tagihan_pokok'] or 0) - float(row['angsuran_pokok'] or 0)
                sisa_m = float(row['tagihan_margin'] or 0) - float(row['angsuran_margin'] or 0)
                if sisa_p <= 0.01 and sisa_m <= 0.01:
                    d_kalk = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0)
                else:
                    d_kalk = ((float(row['tagihan_pokok'] or 0) + float(row['tagihan_margin'] or 0)) * 0.005 * max((today - jt).days, 0)) - float(row['angsuran_denda'] or 0)
                denda_multiguna += max(0, d_kalk)

            # Kalkulasi Denda Keterlambatan Urgent
            cursor.execute("SELECT tanggal_jatuh_tempo, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, tagihan_denda, angsuran_denda FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                jt = row['tanggal_jatuh_tempo']
                if isinstance(jt, str): jt = datetime.strptime(str(jt)[:10], '%Y-%m-%d').date()
                
                sisa_p_urg = float(row['tagihan_pokok'] or 0) - float(row['angsuran_pokok'] or 0)
                sisa_m_urg = float(row['tagihan_margin'] or 0) - float(row['angsuran_margin'] or 0)
                if sisa_p_urg <= 0.01 and sisa_m_urg <= 0.01:
                    d_kalk_urg = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0)
                else:
                    d_kalk_urg = ((float(row['tagihan_pokok'] or 0) + float(row['tagihan_margin'] or 0)) * 0.005 * max((today - jt).days, 0)) - float(row['angsuran_denda'] or 0)
                denda_urgent += max(0, d_kalk_urg)

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

# === API: BATAL ANGSURAN (REVERSE TRANSAKSI) ===
@api_transaksi_bp.route('/api/batal_angsuran', methods=['POST'])
def batal_angsuran():
    data = request.json
    
    jenis = data.get('jenis')
    id_tagihan = data.get('id_tagihan')
    if not jenis:
        if data.get('kategori') == 'utama' or 'jenis_pinjaman' in data: jenis = 'utama'
        elif data.get('kategori') == 'urgent' or 'jenis_dana_urgent' in data: jenis = 'urgent'
        
    if str(jenis).lower() in ['multiguna', 'tempo', 'utama']: jenis = 'utama'
    elif str(jenis).lower() in ['gaji', 'thr', 'dana urgent', 'urgent']: jenis = 'urgent'
    
    id_tagihan = data.get('id_tagihan') or data.get('id')
    
    if not id_tagihan or not jenis:
        return jsonify({'status': 'error', 'message': f'Data batal angsuran tidak lengkap. Payload: {json.dumps(data)}'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        tanggal_batal = datetime.now().strftime('%Y-%m-%d')
        cabang_member = session.get('cabang', 'GAS')

        if jenis == 'utama':
            cursor.execute("SELECT * FROM angsuran_multiguna_tempo WHERE id = %s AND (status = 'LUNAS' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)", (id_tagihan,))
            row = cursor.fetchone()
            if not row: raise ValueError("Data angsuran tidak ditemukan, atau tidak ada pembayaran yang bisa dibatalkan (Lunas Top-Up tidak dapat dibatalkan otomatis).")
            
            no_anggota = row['no_anggota']
            nama_anggota = row.get('nama_anggota', 'Anggota')
            pokok = float(row.get('angsuran_pokok') or 0)
            margin = float(row.get('angsuran_margin') or 0)
            denda = float(row.get('angsuran_denda') or 0)
            try: edc_val = float(row.get('edc') or 0)
            except: edc_val = 0.0
            j_pinjaman = row.get('jenis_pinjaman') or 'Multiguna'
            
            cursor.execute("""
                UPDATE angsuran_multiguna_tempo 
                SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0 
                WHERE id=%s
            """, (id_tagihan,))
            
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            akun_pendapatan = '4101' if j_pinjaman == 'Multiguna' else '4102'
            
            total = pokok + margin + denda + edc_val
            catat_jurnal_cabang(cursor, tanggal_batal, '1101', f"Batal Angsuran {j_pinjaman} - {nama_anggota}", 0, total, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Pelunasan Pokok {j_pinjaman} - {nama_anggota}", pokok, 0, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_batal, akun_pendapatan, f"Batal Pendapatan Margin {j_pinjaman} - {nama_anggota}", margin, 0, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4106', f"Batal Pendapatan Denda {j_pinjaman} - {nama_anggota}", denda, 0, cabang_member)
            if edc_val > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4105', f"Batal Pendapatan EDC/Admin {j_pinjaman} - {nama_anggota}", edc_val, 0, cabang_member)

        elif jenis == 'urgent':
            cursor.execute("SELECT * FROM angsuran_dana_urgent WHERE id = %s AND (status = 'LUNAS' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)", (id_tagihan,))
            row = cursor.fetchone()
            if not row: raise ValueError("Data angsuran urgent tidak ditemukan atau tidak ada pembayaran yang bisa dibatalkan.")
            
            no_anggota = row['no_anggota']
            nama_anggota = row.get('nama_anggota', 'Anggota')
            pokok = float(row.get('angsuran_pokok') or 0)
            margin = float(row.get('angsuran_margin') or 0)
            denda = float(row.get('angsuran_denda') or 0)
            try: edc_val = float(row.get('edc') or 0)
            except: edc_val = 0.0
            j_urgent = row.get('jenis_dana_urgent') or 'Gaji'
            
            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0 
                WHERE id=%s
            """, (id_tagihan,))
            
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            akun_pendapatan = '4103' if j_urgent == 'Gaji' else '4104'
            
            total = pokok + margin + denda + edc_val
            catat_jurnal_cabang(cursor, tanggal_batal, '1101', f"Batal Angsuran Urgent {j_urgent} - {nama_anggota}", 0, total, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Pelunasan Pokok Urgent {j_urgent} - {nama_anggota}", pokok, 0, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_batal, akun_pendapatan, f"Batal Pendapatan Margin Urgent {j_urgent} - {nama_anggota}", margin, 0, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4107', f"Batal Pendapatan Denda Urgent {j_urgent} - {nama_anggota}", denda, 0, cabang_member)
            if edc_val > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4105', f"Batal Pendapatan EDC/Admin Urgent {j_urgent} - {nama_anggota}", edc_val, 0, cabang_member)

        # --- AUDIT LOG ---
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(100), role VARCHAR(50), cabang VARCHAR(50), aksi VARCHAR(255), detail TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            detail_log = json.dumps({'id_tagihan': id_tagihan, 'jenis': jenis, 'nama_anggota': nama_anggota, 'pokok': pokok, 'margin': margin})
            user_aktif = session.get('nama_lengkap', session.get('username', 'System'))
            role_aktif = session.get('role', 'System')
            cursor.execute("INSERT INTO audit_logs (username, role, cabang, aksi, detail) VALUES (%s, %s, %s, %s, %s)", 
                           (user_aktif, role_aktif, cabang_member, 'BATAL_ANGSURAN', detail_log))
        except Exception:
            pass

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pembayaran angsuran berhasil dibatalkan dan jurnal dikoreksi.'}), 200
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close(); conn.close()

# === API: BATAL PENCAIRAN (REVERSE TRANSAKSI) ===
@api_transaksi_bp.route('/api/batal_pencairan', methods=['POST'])
def batal_pencairan():
    data = request.json
    
    jenis = data.get('jenis')
    no_anggota = data.get('no_anggota')
    if not jenis:
        if 'jenis_pencairan' in data: jenis = 'utama'
        elif 'jenis_dana_urgent' in data: jenis = 'urgent'
        elif data.get('kategori') == 'utama': jenis = 'utama'
        elif data.get('kategori') == 'urgent': jenis = 'urgent'
        
    if str(jenis).lower() in ['multiguna', 'tempo', 'utama']: jenis = 'utama'
    elif str(jenis).lower() in ['gaji', 'thr', 'dana urgent', 'urgent']: jenis = 'urgent'
    
    # Terima variasi key jika frontend menggunakan nama kolom dari list array pencairan
    no_anggota = data.get('no_anggota') or data.get('nomor_anggota')
    
    tgl_pencairan = data.get('tgl_pencairan') or data.get('tanggal_cair') or data.get('tanggal_pencairan_dana_urgent') or data.get('tanggal_pencairan')
    if tgl_pencairan:
        tgl_pencairan = str(tgl_pencairan)[:10]
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        
        # Jika no_anggota atau tgl_pencairan kosong, coba cari dari ID
        if not tgl_pencairan or not no_anggota:
            id_pencairan = data.get('id') or data.get('id_pencairan') or data.get('id_tagihan')
            if id_pencairan and jenis == 'utama':
                cursor.execute("SELECT no_anggota, tanggal_cair FROM pencairan_multiguna_tempo WHERE id=%s", (id_pencairan,))
                row = cursor.fetchone()
                if row:
                    no_anggota = row['no_anggota']
                    tgl_pencairan = str(row['tanggal_cair'])[:10]
            elif id_pencairan and jenis == 'urgent':
                cursor.execute("SELECT no_anggota, tanggal_pencairan_dana_urgent FROM pencairan_dana_urgent WHERE id=%s", (id_pencairan,))
                row = cursor.fetchone()
                if row:
                    no_anggota = row['no_anggota']
                    tgl_pencairan = str(row['tanggal_pencairan_dana_urgent'])[:10]

        if not tgl_pencairan:
            raise ValueError(f"Tanggal pencairan tidak valid atau tidak disertakan. Payload: {json.dumps(data)}")
        if not no_anggota:
            raise ValueError(f"Nomor anggota tidak disertakan dari sistem. Payload: {json.dumps(data)}")
        if not jenis:
            raise ValueError(f"Jenis pencairan tidak dikenali. Payload: {json.dumps(data)}")

        tanggal_batal = datetime.now().strftime('%Y-%m-%d')
        cabang_member = session.get('cabang', 'GAS')

        if not tgl_pencairan:
            raise ValueError("Tanggal pencairan tidak valid atau tidak disertakan dari sistem.")

        if jenis == 'utama':
            cursor.execute("SELECT id FROM angsuran_multiguna_tempo WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s AND status != 'BELUM BAYAR'", (no_anggota, tgl_pencairan))
            if cursor.fetchone(): raise ValueError("Tidak bisa membatalkan pencairan karena sudah ada angsuran yang dibayar. Batalkan angsurannya terlebih dahulu.")
            
            cursor.execute("SELECT * FROM pencairan_multiguna_tempo WHERE no_anggota=%s AND DATE(tanggal_cair)=%s", (no_anggota, tgl_pencairan))
            pencairan = cursor.fetchone()
            if not pencairan: raise ValueError("Data pencairan tidak ditemukan.")
            
            nama_anggota = pencairan.get('nama_anggota', 'Anggota')
            j_pinjaman = pencairan.get('jenis_pencairan', 'Multiguna')
            besar_pinjaman = float(pencairan.get('besar_pinjaman') or 0)
            terima_bersih = float(pencairan.get('terima_bersih') or 0)
            potongan_adm = float(pencairan.get('potongan_adm') or 0)
            potongan_simp = float(pencairan.get('potongan_simpanan_pokok') or 0)
            potongan_kematian = float(pencairan.get('potongan_dana_kematian') or 0)
            biaya_jamsostek = float(pencairan.get('biaya_jamsostek') or 0)
            potongan_ppap = float(pencairan.get('potongan_ppap') or 0)
            potongan_angsuran = float(pencairan.get('potongan_angsuran') or 0)
            potongan_urgent = float(pencairan.get('potongan_dana_urgent') or 0)
            
            cursor.execute("DELETE FROM angsuran_multiguna_tempo WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s", (no_anggota, tgl_pencairan))
            cursor.execute("DELETE FROM pencairan_multiguna_tempo WHERE no_anggota=%s AND DATE(tanggal_cair)=%s", (no_anggota, tgl_pencairan))
            
            if potongan_simp > 0: cursor.execute("UPDATE simpanan SET simpanan_pokok = simpanan_pokok - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (potongan_simp, potongan_simp, no_anggota))
                
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Pencairan {j_pinjaman} - {nama_anggota}", 0, besar_pinjaman, cabang_member)
            if terima_bersih > 0: catat_jurnal_cabang(cursor, tanggal_batal, '1101', f"Batal Pencairan {j_pinjaman} (Terima Bersih) - {nama_anggota}", terima_bersih, 0, cabang_member)
            if potongan_adm > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4105', f"Batal Pendapatan Adm - {nama_anggota}", potongan_adm, 0, cabang_member)
            if potongan_simp > 0: catat_jurnal_cabang(cursor, tanggal_batal, '3101', f"Batal Simpanan Pokok - {nama_anggota}", potongan_simp, 0, cabang_member)
            if potongan_kematian > 0: catat_jurnal_cabang(cursor, tanggal_batal, '2101', f"Batal Titipan Dana Kematian - {nama_anggota}", potongan_kematian, 0, cabang_member)
            if biaya_jamsostek > 0: catat_jurnal_cabang(cursor, tanggal_batal, '2102', f"Batal Titipan Jamsostek - {nama_anggota}", biaya_jamsostek, 0, cabang_member)
            if potongan_ppap > 0: catat_jurnal_cabang(cursor, tanggal_batal, '2103', f"Batal Jaminan PPAP - {nama_anggota}", potongan_ppap, 0, cabang_member)
            
            # Memulihkan tagihan lama yang sempat dilunasi dengan skema Top-Up
            if potongan_angsuran > 0: 
                catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Potongan Top-Up - {nama_anggota}", potongan_angsuran, 0, cabang_member)
                cursor.execute("UPDATE angsuran_multiguna_tempo SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, status='BELUM BAYAR', tgl_bayar=NULL WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'", (no_anggota, tgl_pencairan))
            if potongan_urgent > 0: 
                catat_jurnal_cabang(cursor, tanggal_batal, '1203', f"Batal Potongan Urgent - {nama_anggota}", potongan_urgent, 0, cabang_member)
                cursor.execute("UPDATE angsuran_dana_urgent SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, status='BELUM BAYAR', tgl_bayar=NULL WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'", (no_anggota, tgl_pencairan))

        elif jenis == 'urgent':
            cursor.execute("SELECT id FROM angsuran_dana_urgent WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s AND status != 'BELUM BAYAR'", (no_anggota, tgl_pencairan))
            if cursor.fetchone(): raise ValueError("Tidak bisa membatalkan pencairan karena sudah ada pembayaran yang lunas. Batalkan angsuran terlebih dahulu.")
            
            cursor.execute("SELECT * FROM pencairan_dana_urgent WHERE no_anggota=%s AND DATE(tanggal_pencairan_dana_urgent)=%s", (no_anggota, tgl_pencairan))
            pencairan = cursor.fetchone()
            if not pencairan: raise ValueError("Data pencairan urgent tidak ditemukan.")
            
            nama_anggota = pencairan.get('nama_anggota', 'Anggota')
            j_urgent = pencairan.get('jenis_dana_urgent') or 'Gaji'
            jumlah_dana = float(pencairan.get('jumlah_dana_urgent') or 0)
            
            cursor.execute("DELETE FROM angsuran_dana_urgent WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s", (no_anggota, tgl_pencairan))
            cursor.execute("DELETE FROM pencairan_dana_urgent WHERE no_anggota=%s AND DATE(tanggal_pencairan_dana_urgent)=%s", (no_anggota, tgl_pencairan))
            
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Pencairan Urgent {j_urgent} - {nama_anggota}", 0, jumlah_dana, cabang_member)
            catat_jurnal_cabang(cursor, tanggal_batal, '1101', f"Batal Pencairan Urgent {j_urgent} (Kas Keluar) - {nama_anggota}", jumlah_dana, 0, cabang_member)

        else:
            raise ValueError("Jenis pencairan tidak valid.")

        # --- AUDIT LOG ---
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(100), role VARCHAR(50), cabang VARCHAR(50), aksi VARCHAR(255), detail TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            detail_log = json.dumps({'no_anggota': no_anggota, 'jenis': jenis, 'nama_anggota': nama_anggota, 'tanggal_cair': tgl_pencairan})
            user_aktif = session.get('nama_lengkap', session.get('username', 'System'))
            role_aktif = session.get('role', 'System')
            cursor.execute("INSERT INTO audit_logs (username, role, cabang, aksi, detail) VALUES (%s, %s, %s, %s, %s)", 
                           (user_aktif, role_aktif, cabang_member, 'BATAL_PENCAIRAN', detail_log))
        except Exception:
            pass

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pencairan berhasil dibatalkan dan seluruh tagihan telah dihapus.'}), 200
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close(); conn.close()

# === API: DOWNLOAD TEMPLATE MIGRASI EXCEL (CSV) ===
@api_transaksi_bp.route('/api/download_template/<jenis>', methods=['GET'])
def download_template_migrasi(jenis):
    import csv, io
    from flask import Response
    output = io.StringIO()
    writer = csv.writer(output, delimiter=',')
    
    if jenis == 'identitas':
        writer.writerow(['no_referensi_excel', 'nama_anggota', 'cabang', 'tgl_lahir', 'no_telp', 'nik_ktp', 'nik_kk', 'alamat_ktp', 'alamat_tagih', 'status_tempat_tinggal', 'email', 'password', 'pt_instansi', 'status_karyawan', 'jabatan', 'awal_bekerja', 'lama_kerja', 'akhir_bekerja', 'no_jmo', 'status_jmo', 'bank', 'no_rek', 'nama_penanggung_jawab', 'no_telp_penanggung_jawab', 'bank_penanggung_jawab', 'no_rek_penanggung_jawab', 'kol', 'kriteria', 'marketing', 'simpanan_pokok', 'simpanan_wajib'])
        writer.writerow(['1', 'SAIPU NAWASI (LANCAR)', 'GAS', '1990-01-01', '08123456789', '367100000000', '367100000000', 'Jl. Mawar No 1', 'Jl. Mawar No 1', 'Milik Sendiri', 'email@test.com', '123456', 'PT ABC', 'Tetap', 'Staff', '2020-01-01', '6 Tahun', '', '112233', 'Aktif', 'BCA', '123456789', 'Istri', '081222', 'BRI', '987654', 'Lancar', 'VIP', 'Sales A', '100000', '250000'])
        writer.writerow(['2', 'BUDI SANTOSO (MACET)', 'GAS', '1985-05-15', '08133333', '367100000001', '367100000001', 'Jl. Melati No 2', 'Jl. Melati No 2', 'Sewa', 'budi@test.com', '123456', 'PT XYZ', 'Tetap', 'Staff', '2015-01-01', '11 Tahun', '', '112244', 'Aktif', 'Mandiri', '987654321', 'Istri', '08133333', 'BCA', '112233', 'Macet', 'Reguler', 'Sales B', '50000', '150000'])
        filename = 'Template_1_Identitas_Simpanan.csv'
        
    elif jenis == 'multiguna':
        writer.writerow(['no_referensi_excel', 'nama_anggota', 'jenis_pinjaman', 'tgl_pencairan_awal', 'besar_pinjaman_awal', 'tenor_bulan', 'bunga_persen_perbulan', 'jml_angsuran_lunas', 'tgl_jatuh_tempo_berikutnya', 'angsuran_pokok_perbulan', 'angsuran_margin_perbulan'])
        writer.writerow(['1', 'SAIPU NAWASI (LANCAR)', 'Multiguna', '2026-01-15', '5000000', '10', '2.5', '4', '2026-06-15', '500000', '125000'])
        writer.writerow(['2', 'BUDI SANTOSO (MACET)', 'Tempo', '2025-08-10', '2000000', '12', '3.0', '5', '2026-02-10', '166666', '60000'])
        filename = 'Template_2_Multiguna_Tempo.csv'
        
    elif jenis == 'urgent':
        writer.writerow(['no_referensi_excel', 'nama_anggota', 'jenis_urgent', 'tgl_pencairan_awal', 'tgl_jatuh_tempo', 'jumlah_dana_urgent', 'margin_nominal', 'status_pembayaran'])
        writer.writerow(['1', 'SAIPU NAWASI (LANCAR)', 'Gaji', '2026-05-01', '2026-06-01', '1000000', '100000', 'BELUM BAYAR'])
        writer.writerow(['2', 'BUDI SANTOSO (MACET)', 'THR', '2025-04-10', '2025-05-10', '2000000', '200000', 'BELUM BAYAR'])
        filename = 'Template_3_Dana_Urgent.csv'
        
    else:
        return "Jenis template tidak valid", 400
        
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response