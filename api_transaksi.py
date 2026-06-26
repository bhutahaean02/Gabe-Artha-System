from flask import Blueprint, request, jsonify, session
from datetime import datetime
import json
from db import get_db_connection
from api_helpers import tambah_bulan, parse_float, parse_int, catat_jurnal, hitung_denda_keterlambatan

api_transaksi_bp = Blueprint('api_transaksi', __name__)

# === FUNGSI BANTUAN UNTUK MENCATAT JURNAL DENGAN CABANG ===
def catat_jurnal_cabang(cursor, tanggal, account_code, keterangan, debit, kredit, cabang='GAS'):
    if debit == 0 and kredit == 0:
        return
    cursor.execute("SELECT id FROM coa WHERE account_code = %s", (account_code,))
    coa = cursor.fetchone()
    if coa:
        coa_id = coa[0] if isinstance(coa, tuple) else coa['id']
        cursor.execute("""
            INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (tanggal, coa_id, keterangan, debit, kredit, cabang))

# === API: PROSES PENCAIRAN & AUTO-GENERATE JADWAL ANGSURAN ===
@api_transaksi_bp.route('/api/pencairan_multiguna', methods=['POST'])
def proses_pencairan():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    try:
        data['besar_pinjaman'] = parse_float(data.get('besar_pinjaman'), 'Besar Pinjaman')
        data['tenor'] = parse_int(data.get('tenor'), 'Tenor')
        data['bunga_persen'] = parse_float(data.get('bunga_persen'), 'Bunga Persen')
        if data.get('jenis_pencairan') == 'Tempo':
            data['bunga_persen'] = 20.0
        data['potongan_angsuran'] = parse_float(data.get('potongan_angsuran'), 'Potongan Angsuran')
        data['potongan_dana_urgent'] = parse_float(data.get('potongan_dana_urgent'), 'Potongan Dana Urgent')
        data['biaya_jamsostek'] = parse_float(data.get('biaya_jamsostek'), 'Biaya Jamsostek')
        data['potongan_simpanan_pokok'] = parse_float(data.get('potongan_simpanan_pokok'), 'Potongan Simpanan Pokok')
        data['potongan_adm'] = parse_float(data.get('potongan_adm'), 'Potongan Administrasi')
        data['potongan_dana_kematian'] = parse_float(data.get('potongan_dana_kematian'), 'Potongan Dana Kematian')
        data['potongan_ppap'] = parse_float(data.get('potongan_ppap'), 'Potongan PPAP')
        data['terima_bersih'] = parse_float(data.get('terima_bersih'), 'Terima Bersih')
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    
    # === SISTEM PENCEGATAN (INTERCEPT) UNTUK APPROVAL ===
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
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
        besar_pinjaman = data.get('besar_pinjaman')
        tenor = data.get('tenor')
        bunga_persen = data.get('bunga_persen')
        
        potongan_angsuran = data.get('potongan_angsuran')
        potongan_dana_urgent = data.get('potongan_dana_urgent')
        biaya_jamsostek = data.get('biaya_jamsostek')
        potongan_simpanan_pokok = data.get('potongan_simpanan_pokok')
        potongan_adm = data.get('potongan_adm')
        potongan_dana_kematian = data.get('potongan_dana_kematian')
        potongan_ppap = data.get('potongan_ppap')
        terima_bersih = data.get('terima_bersih')
        
        query_pencairan = """
            INSERT INTO pencairan_multiguna_tempo (
                no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, 
                besar_pinjaman, potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, 
                potongan_simpanan_pokok, potongan_adm, potongan_dana_kematian, potongan_ppap, 
                terima_bersih, tenor, is_restruktur
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_pencairan, (
            no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, tanggal_gajian, besar_pinjaman, 
            potongan_angsuran, potongan_dana_urgent, biaya_jamsostek, potongan_simpanan_pokok, 
            potongan_adm, potongan_dana_kematian, potongan_ppap, terima_bersih, tenor, 0
        ))
        
        tagihan_pokok = besar_pinjaman / tenor if tenor > 0 else 0
        tagihan_margin = besar_pinjaman * (bunga_persen / 100)
        total_margin = tagihan_margin * tenor
        tgl_cair_obj = datetime.strptime(tanggal_cair, '%Y-%m-%d').date()
        try:
            base_date_obj = datetime.strptime(tanggal_gajian, '%Y-%m-%d').date() if tanggal_gajian else tgl_cair_obj
        except:
            base_date_obj = tgl_cair_obj
        
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
            if tanggal_gajian:
                jatuh_tempo = tambah_bulan(base_date_obj, i - 1)
            else:
                jatuh_tempo = tambah_bulan(base_date_obj, i)
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
        
        if potongan_angsuran > 0: 
            # 1. Ambil data sisa hutang lama (Pokok & Margin) - Kecualikan pinjaman yang baru saja diinsert
            cursor.execute("SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR' AND tgl_pencairan != %s", (no_anggota, tanggal_cair))
            tagihan_lama = cursor.fetchone()
            
            sisa_pokok_lama = 0.0
            sisa_margin_lama = 0.0
            if tagihan_lama:
                sisa_pokok_lama = float(tagihan_lama[0] or 0) if isinstance(tagihan_lama, tuple) else float(tagihan_lama.get('sisa_pokok') or 0)
                sisa_margin_lama = float(tagihan_lama[1] or 0) if isinstance(tagihan_lama, tuple) else float(tagihan_lama.get('sisa_margin') or 0)
            
            if (sisa_pokok_lama + sisa_margin_lama) > potongan_angsuran:
                if sisa_pokok_lama >= potongan_angsuran:
                    sisa_pokok_lama = potongan_angsuran
                    sisa_margin_lama = 0
                else:
                    sisa_margin_lama = potongan_angsuran - sisa_pokok_lama
                    
            if sisa_pokok_lama == 0 and sisa_margin_lama == 0:
                sisa_pokok_lama = potongan_angsuran
            
            # 2. Langsung melunasi Piutang Pokok, Margin, & Denda (Tanpa Dana Temporer)
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
                WHERE no_anggota = %s AND status = 'BELUM BAYAR' AND tgl_pencairan != %s
            """, (tanggal_cair, no_anggota, tanggal_cair))
            
        if potongan_dana_urgent > 0: 
            catat_jurnal_cabang(cursor, tanggal_cair, '1203', f"Potongan Pelunasan Dana Urgent - {nama_anggota}", 0, potongan_dana_urgent, cabang_member)
            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS TOP-UP', tgl_bayar = %s 
                WHERE no_anggota = %s AND status = 'BELUM BAYAR' AND tgl_pencairan != %s
            """, (tanggal_cair, no_anggota, tanggal_cair))

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
    
    try:
        data['jumlah_dana_urgent'] = parse_float(data.get('jumlah_dana_urgent'), 'Jumlah Dana Urgent')
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400
        
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
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
        jumlah_dana_urgent = data.get('jumlah_dana_urgent')
        # Margin otomatis 20% dari pokok pinjaman dana urgent
        margin_dana_urgent = jumlah_dana_urgent * 0.20
        
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
        
        tanggal_req = request.args.get('tanggal')
        today = datetime.strptime(tanggal_req[:10], '%Y-%m-%d').date() if tanggal_req else datetime.now().date()
        
        # Query tunggal yang menggabungkan semua logika
        # Mengambil tagihan multiguna & urgent, dan menghitung denda langsung di database
        query = """
            SELECT
                data.*,
                -- Kalkulasi Denda Real-time di SQL
                GREATEST(0, 
                    IF(
                        (data.sisa_tagihan_pokok > 0.01 OR data.sisa_tagihan_margin > 0.01) AND denda.is_active,
                        (
                            (data.sisa_tagihan_pokok + data.sisa_tagihan_margin) 
                            * CASE 
                                WHEN data.jenis_pinjaman IN ('Tempo', 'Gaji', 'THR') THEN 0.007
                                ELSE 0.005 
                              END
                            * GREATEST(0, DATEDIFF(%s, data.jatuh_tempo))
                        ) + GREATEST(0, data.tagihan_denda - data.angsuran_denda),
                        GREATEST(0, data.tagihan_denda - data.angsuran_denda)
                    )
                ) AS kalkulasi_denda,
                GREATEST(0, DATEDIFF(%s, data.jatuh_tempo)) AS od_hari
            FROM (
                -- Query untuk Pinjaman Multiguna/Tempo
                SELECT 
                    'utama' AS `type`,
                    amt.id, amt.no_anggota, amt.nama_anggota, amt.jenis_pinjaman, amt.tgl_pencairan, amt.jatuh_tempo,
                    amt.sisa_pokok, amt.sisa_margin, amt.tenor, amt.angsuran_ke,
                    amt.tagihan_pokok, amt.tagihan_margin, amt.tagihan_denda,
                    amt.angsuran_pokok, amt.angsuran_margin, amt.angsuran_denda,
                    (amt.tagihan_pokok - amt.angsuran_pokok) AS sisa_tagihan_pokok,
                    (amt.tagihan_margin - amt.angsuran_margin) AS sisa_tagihan_margin
                FROM (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY tgl_pencairan ORDER BY angsuran_ke ASC) as rn
                    FROM angsuran_multiguna_tempo 
                    WHERE no_anggota = %s AND status = 'BELUM BAYAR'
                ) amt
                WHERE amt.rn = 1

                UNION ALL

                -- Query untuk Pinjaman Dana Urgent
                SELECT 
                    'urgent' AS `type`,
                    adu.id, adu.no_anggota, adu.nama_anggota, adu.jenis_dana_urgent AS jenis_pinjaman, adu.tgl_pencairan, adu.tanggal_jatuh_tempo AS jatuh_tempo,
                    NULL AS sisa_pokok, NULL AS sisa_margin, 1 AS tenor, 1 AS angsuran_ke,
                    adu.tagihan_pokok, adu.tagihan_margin, adu.tagihan_denda,
                    adu.angsuran_pokok, adu.angsuran_margin, adu.angsuran_denda,
                    (adu.tagihan_pokok - adu.angsuran_pokok) AS sisa_tagihan_pokok,
                    (adu.tagihan_margin - adu.angsuran_margin) AS sisa_tagihan_margin
                FROM (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY tgl_pencairan ORDER BY id ASC) as rn
                    FROM angsuran_dana_urgent 
                    WHERE no_anggota = %s AND status = 'BELUM BAYAR'
                ) adu
                WHERE adu.rn = 1
            ) AS data
            -- Cross join untuk mendapatkan status denda aktif secara aman
            CROSS JOIN (
                SELECT COALESCE((SELECT nilai = '1' FROM pengaturan WHERE kunci = 'denda_aktif'), 1) AS is_active
            ) AS denda;
        """
        
        # Parameter untuk query: today, today, no_anggota, no_anggota
        params = (today, today, no_anggota, no_anggota)
        cursor.execute(query, params)
        all_tagihan = cursor.fetchall()
        
        # Pisahkan kembali hasilnya menjadi data_utama dan data_urgent untuk frontend
        tagihan_utama_list = []
        tagihan_urgent_list = []
        
        for tagihan in all_tagihan:
            # Menambahkan kembali field tunggakan untuk kompatibilitas frontend
            tagihan['tunggakan_pokok'] = tagihan['sisa_tagihan_pokok']
            tagihan['tunggakan_margin'] = tagihan['sisa_tagihan_margin']
            tagihan['tunggakan_denda'] = tagihan['kalkulasi_denda']
            
            if tagihan['type'] == 'utama':
                tagihan_utama_list.append(tagihan)
            else: # urgent
                # Frontend untuk kartu urgent menggunakan key yang berbeda
                tagihan['jenis_dana_urgent'] = tagihan['jenis_pinjaman']
                tagihan['tanggal_jatuh_tempo'] = tagihan['jatuh_tempo']
                tagihan_urgent_list.append(tagihan)

        return jsonify({'status': 'success', 'data_utama': tagihan_utama_list, 'data_urgent': tagihan_urgent_list}), 200
    except Exception as e:
        import traceback
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# === API: RESTRUKTURISASI PINJAMAN MACET ===
@api_transaksi_bp.route('/api/restruktur_pinjaman', methods=['POST'])
def restruktur_pinjaman():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)

    # --- Validasi Input ---
    try:
        no_anggota = data.get('no_anggota')
        tgl_pencairan_lama = data.get('tgl_pencairan_lama')
        tanggal_restruktur = data.get('tanggal_restruktur') or datetime.now().strftime('%Y-%m-%d')
        tenor_baru = parse_int(data.get('tenor_baru'), 'Tenor Baru')
        bunga_persen_baru = parse_float(data.get('bunga_persen_baru'), 'Bunga Baru')
        jenis_pinjaman_baru = data.get('jenis_pinjaman_baru', 'Multiguna') # Default to Multiguna
        if not all([no_anggota, tgl_pencairan_lama, tenor_baru, bunga_persen_baru]):
            raise ValueError("Data untuk restrukturisasi tidak lengkap.")
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400

    # --- Approval Intercept ---
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", 
                           ('Restrukturisasi Pinjaman', json.dumps(data), session.get('nama_lengkap', 'Admin'), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Restrukturisasi diajukan! Menunggu Approval dari Manager.'}), 201
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()

        # 1. Ambil data anggota dan cabang
        cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        member = cursor.fetchone()
        if not member:
            raise ValueError("Anggota tidak ditemukan.")
        nama_anggota = member['nama_anggota']
        cabang_member = member.get('cabang') or session.get('cabang', 'GAS')

        # 2. Hitung total sisa kewajiban dari pinjaman lama
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        sisa_pokok_lama = 0.0
        sisa_margin_lama = 0.0
        denda_lama = 0.0
        jenis_pinjaman_lama = 'Multiguna'

        # Ambil semua angsuran belum bayar dari pinjaman lama
        cursor.execute("""
            SELECT * FROM angsuran_multiguna_tempo 
            WHERE no_anggota = %s AND tgl_pencairan = %s AND status = 'BELUM BAYAR'
        """, (no_anggota, tgl_pencairan_lama))
        angsuran_lama_list = cursor.fetchall()

        if not angsuran_lama_list:
            raise ValueError("Tidak ada angsuran yang belum dibayar untuk pinjaman ini.")

        for angsuran in angsuran_lama_list:
            jenis_pinjaman_lama = angsuran.get('jenis_pinjaman', 'Multiguna')
            sisa_pokok_lama += float(angsuran['tagihan_pokok'] or 0) - float(angsuran['angsuran_pokok'] or 0)
            sisa_margin_lama += float(angsuran['tagihan_margin'] or 0) - float(angsuran['angsuran_margin'] or 0)
            
            denda_calc, _ = hitung_denda_keterlambatan(
                jatuh_tempo=angsuran.get('jatuh_tempo'),
                tgl_bayar=angsuran.get('tgl_bayar'),
                tagihan_pokok=angsuran.get('tagihan_pokok'),
                tagihan_margin=angsuran.get('tagihan_margin'),
                angsuran_pokok=angsuran.get('angsuran_pokok'),
                angsuran_margin=angsuran.get('angsuran_margin'),
                tagihan_denda_db=angsuran.get('tagihan_denda'),
                angsuran_denda=angsuran.get('angsuran_denda'),
                denda_aktif=denda_aktif,
                jenis_pinjaman=jenis_pinjaman_lama,
                tgl_referensi=datetime.strptime(tanggal_restruktur, '%Y-%m-%d').date()
            )
            denda_lama += denda_calc

        besar_pinjaman_baru = sisa_pokok_lama + sisa_margin_lama + denda_lama
        if besar_pinjaman_baru <= 0.01:
            raise ValueError("Total kewajiban pinjaman lama adalah nol. Tidak ada yang perlu direstruktur.")

        # 3. Tutup pinjaman lama
        cursor.execute("""
            UPDATE angsuran_multiguna_tempo 
            SET status = 'LUNAS RESTRUKTUR', tgl_bayar = %s
            WHERE no_anggota = %s AND tgl_pencairan = %s AND status = 'BELUM BAYAR'
        """, (tanggal_restruktur, no_anggota, tgl_pencairan_lama))

        # 4. Buat pencairan baru (tanpa kas keluar)
        cursor.execute("""
            INSERT INTO pencairan_multiguna_tempo (
                no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, besar_pinjaman, 
                terima_bersih, tenor, is_restruktur
            ) VALUES (%s, %s, %s, %s, %s, 0, %s, 1)
        """, (no_anggota, nama_anggota, jenis_pinjaman_baru, tanggal_restruktur, besar_pinjaman_baru, tenor_baru))
        
        # 5. Buat jadwal angsuran baru
        tagihan_pokok_baru = besar_pinjaman_baru / tenor_baru if tenor_baru > 0 else 0
        tagihan_margin_baru = besar_pinjaman_baru * (bunga_persen_baru / 100)
        total_margin_baru = tagihan_margin_baru * tenor_baru
        tgl_restruktur_obj = datetime.strptime(tanggal_restruktur, '%Y-%m-%d').date()

        for i in range(1, tenor_baru + 1):
            jatuh_tempo_baru = tambah_bulan(tgl_restruktur_obj, i)
            sisa_pokok_berjalan = besar_pinjaman_baru - (tagihan_pokok_baru * (i - 1))
            sisa_margin_berjalan = total_margin_baru - (tagihan_margin_baru * (i - 1))
            cursor.execute("""
                INSERT INTO angsuran_multiguna_tempo (no_anggota, nama_anggota, jenis_pinjaman, tgl_pencairan, jatuh_tempo, besar_pinjaman, tenor, bunga_persen, margin, total_margin, sisa_pokok, sisa_margin, angsuran_ke, tagihan_pokok, tagihan_margin, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'BELUM BAYAR')
            """, (no_anggota, nama_anggota, jenis_pinjaman_baru, tanggal_restruktur, jatuh_tempo_baru, besar_pinjaman_baru, tenor_baru, bunga_persen_baru, tagihan_margin_baru, total_margin_baru, sisa_pokok_berjalan, sisa_margin_berjalan, i, tagihan_pokok_baru, tagihan_margin_baru))

        # 6. Jurnal Akuntansi (Penting!)
        akun_piutang_lama = '1201' if jenis_pinjaman_lama == 'Multiguna' else '1202'
        akun_pendapatan_lama = '4101' if jenis_pinjaman_lama == 'Multiguna' else '4102'
        akun_piutang_baru = '1201' if jenis_pinjaman_baru == 'Multiguna' else '1202'
        
        catat_jurnal_cabang(cursor, tanggal_restruktur, akun_piutang_baru, f"Pencairan Restruktur - {nama_anggota}", besar_pinjaman_baru, 0, cabang_member)
        if sisa_pokok_lama > 0: catat_jurnal_cabang(cursor, tanggal_restruktur, akun_piutang_lama, f"Pelunasan Pokok (Restruktur) - {nama_anggota}", 0, sisa_pokok_lama, cabang_member)
        if sisa_margin_lama > 0: catat_jurnal_cabang(cursor, tanggal_restruktur, akun_pendapatan_lama, f"Pendapatan Margin (Restruktur) - {nama_anggota}", 0, sisa_margin_lama, cabang_member)
        if denda_lama > 0: catat_jurnal_cabang(cursor, tanggal_restruktur, '4106', f"Pendapatan Denda (Restruktur) - {nama_anggota}", 0, denda_lama, cabang_member)

        # 7. Update status approval jika ini adalah eksekusi
        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))
            
        conn.commit()
        return jsonify({'status': 'success', 'message': f'Pinjaman berhasil direstruktur! Jadwal angsuran baru ({tenor_baru} bulan) telah dibuat.'}), 201

    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        import traceback
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def _proses_satu_pembayaran(cursor, payment_data, shared_data, config):
    """
    Fungsi helper terpusat untuk memproses satu kartu pembayaran (baik utama maupun urgent).
    Mengembalikan sisa gaji berjalan yang telah diperbarui dan info untuk struk.
    """
    id_tagihan = payment_data.get('id_tagihan')
    if not id_tagihan:
        return shared_data['sisa_gaji_berjalan'], None

    log_name = config['log_name']
    pokok = parse_float(payment_data.get('nominal_pokok'), f"Nominal Pokok {log_name}")
    margin = parse_float(payment_data.get('nominal_margin'), f"Nominal Margin {log_name}")
    denda = parse_float(payment_data.get('nominal_denda'), f"Nominal Denda {log_name}")
    simpanan_wajib = parse_float(payment_data.get('simpanan_wajib'), f"Titipan Simpanan Wajib {log_name}")
    edc = parse_float(payment_data.get('edc'), f"Biaya EDC {log_name}")
    edc_val_to_db = edc if edc > 0 else None
    angsuran_ke = payment_data.get('angsuran_ke')

    query_select = f"""
        SELECT angsuran_pokok, angsuran_margin, angsuran_denda, tagihan_pokok, tagihan_margin, tagihan_denda, 
               {config['date_column']} as jatuh_tempo, tgl_bayar, edc, sisa_gaji, gaji_awal, 
               {config['type_column']} as jenis_pinjaman 
        FROM {config['table_name']} WHERE id=%s FOR UPDATE
    """
    cursor.execute(query_select, (id_tagihan,))
    row = cursor.fetchone()
    if not row:
        return shared_data['sisa_gaji_berjalan'], None

    prev_p, prev_m, prev_d = float(row.get('angsuran_pokok') or 0), float(row.get('angsuran_margin') or 0), float(row.get('angsuran_denda') or 0)
    tag_p, tag_m, tag_d_db = float(row.get('tagihan_pokok') or 0), float(row.get('tagihan_margin') or 0), float(row.get('tagihan_denda') or 0)
    jt, last_pay, j_pinjaman = row.get('jatuh_tempo'), row.get('tgl_bayar'), row.get('jenis_pinjaman', config['default_type'])
    
    new_p, new_m, new_d = prev_p + pokok, prev_m + margin, prev_d + denda
    
    if new_p > (tag_p + 0.01) or new_m > (tag_m + 0.01):
        raise ValueError(f"Pembayaran melebihi sisa tagihan {log_name} yang harus dibayar!")

    today_d = datetime.strptime(shared_data['tanggal_bayar'][:10], '%Y-%m-%d').date()
    cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
    p_row = cursor.fetchone()
    denda_aktif = (p_row['nilai'] == '1') if p_row else True
    
    denda_berjalan_calc, _ = hitung_denda_keterlambatan(
        jatuh_tempo=jt, tgl_bayar=last_pay, tagihan_pokok=tag_p, tagihan_margin=tag_m,
        angsuran_pokok=prev_p, angsuran_margin=prev_m, tagihan_denda_db=tag_d_db, angsuran_denda=0,
        denda_aktif=denda_aktif, jenis_pinjaman=j_pinjaman, tgl_referensi=today_d
    )
    curr_tag_d = denda_berjalan_calc
    
    sisa_p_baru, sisa_m_baru, sisa_d_baru = tag_p - new_p, tag_m - new_m, curr_tag_d - new_d
    status_baru = 'LUNAS' if sisa_p_baru <= 0.01 and sisa_m_baru <= 0.01 and sisa_d_baru <= 0.01 else 'BELUM BAYAR'

    total_potongan_kartu = pokok + margin + denda + simpanan_wajib + edc
    sisa_gaji_berjalan = shared_data['sisa_gaji_berjalan']
    if shared_data['gaji_awal'] > 0:
        sisa_gaji_berjalan -= total_potongan_kartu

    update_fields = {
        'angsuran_pokok': new_p, 'angsuran_margin': new_m, 'angsuran_denda': new_d,
        'tagihan_denda': curr_tag_d, 'status': status_baru, 'tgl_bayar': shared_data['tanggal_bayar'],
        'edc': edc_val_to_db, 'gaji_awal': shared_data['gaji_awal'], 'sisa_gaji': sisa_gaji_berjalan,
        'simpanan_wajib_bayar': simpanan_wajib
    }
    if angsuran_ke is not None and str(angsuran_ke).strip() != "" and config['table_name'] == 'angsuran_multiguna_tempo':
        update_fields['angsuran_ke'] = angsuran_ke
    
    set_clause = ", ".join([f"{key}=%s" for key in update_fields.keys()])
    values = list(update_fields.values()) + [id_tagihan]
    
    query_update = f"UPDATE {config['table_name']} SET {set_clause} WHERE id=%s"
    cursor.execute(query_update, tuple(values))

    akun_piutang = config['akun_piutang_map'].get(j_pinjaman, list(config['akun_piutang_map'].values())[0])
    akun_pendapatan = config['akun_pendapatan_map'].get(j_pinjaman, list(config['akun_pendapatan_map'].values())[0])
    
    catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], '1101', f"Terima Angsuran {j_pinjaman} - {shared_data['nama_anggota']}", (pokok + margin + denda), 0, shared_data['cabang_member'])
    if edc > 0: catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], '1101', f"Terima EDC/Admin {j_pinjaman} - {shared_data['nama_anggota']}", edc, 0, shared_data['cabang_member'])
    
    catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], akun_piutang, f"Pelunasan Pokok {j_pinjaman} - {shared_data['nama_anggota']}", 0, pokok, shared_data['cabang_member'])
    catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], akun_pendapatan, f"Pendapatan Margin {j_pinjaman} - {shared_data['nama_anggota']}", 0, margin, shared_data['cabang_member'])
    if denda > 0: catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], config['akun_denda'], f"Pendapatan Denda {j_pinjaman} - {shared_data['nama_anggota']}", 0, denda, shared_data['cabang_member'])
    if edc > 0: catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], '4105', f"Pendapatan EDC/Admin {j_pinjaman} - {shared_data['nama_anggota']}", 0, edc, shared_data['cabang_member'])

    if simpanan_wajib > 0 and shared_data['no_anggota']:
        cursor.execute("SELECT id FROM simpanan WHERE nomor_anggota=%s", (shared_data['no_anggota'],))
        if cursor.fetchone():
            cursor.execute("UPDATE simpanan SET simpanan_wajib=simpanan_wajib+%s, total_simpanan=total_simpanan+%s WHERE nomor_anggota=%s", (simpanan_wajib, simpanan_wajib, shared_data['no_anggota']))
        else:
            cursor.execute("INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_wajib, simpanan_pokok, total_simpanan) VALUES (%s, %s, %s, 0, %s)", (shared_data['no_anggota'], shared_data['nama_anggota'], simpanan_wajib, simpanan_wajib))
        
        catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], '1101', f"Terima Simpanan Wajib ({log_name}) - {shared_data['nama_anggota']}", simpanan_wajib, 0, shared_data['cabang_member'])
        catat_jurnal_cabang(cursor, shared_data['tanggal_bayar'], '3102', f"Simpanan Wajib ({log_name}) - {shared_data['nama_anggota']}", 0, simpanan_wajib, shared_data['cabang_member'])

    cetak_info = {'jenis': config['type_for_cetak'], 'id': id_tagihan}
    return sisa_gaji_berjalan, cetak_info

@api_transaksi_bp.route('/api/bayar_angsuran', methods=['POST'])
def bayar_angsuran():
    conn = None
    cursor = None
    try:
        data = request.get_json(silent=True) or {}
        gaji_awal = parse_float(data.get('gaji_awal'), 'Gaji Awal Keseluruhan')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()

        shared_data = {
            'tanggal_bayar': data.get('tanggal_bayar') or datetime.now().strftime('%Y-%m-%d'),
            'nama_anggota': data.get('nama_anggota', 'Anggota'),
            'no_anggota': data.get('no_anggota'),
            'gaji_awal': gaji_awal,
            'sisa_gaji_berjalan': gaji_awal,
            'cabang_member': session.get('cabang', 'GAS')
        }

        if shared_data['no_anggota']:
            cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (shared_data['no_anggota'],))
            cab_row = cursor.fetchone()
            if cab_row and cab_row.get('cabang'):
                shared_data['cabang_member'] = cab_row['cabang']
        
        cetak_info_list = []

        configs = {
            'utama': {
                'table_name': 'angsuran_multiguna_tempo', 'date_column': 'jatuh_tempo',
                'type_column': 'jenis_pinjaman', 'default_type': 'Multiguna',
                'akun_piutang_map': {'Multiguna': '1201', 'Tempo': '1202'},
                'akun_pendapatan_map': {'Multiguna': '4101', 'Tempo': '4102'},
                'akun_denda': '4106', 'log_name': 'Utama', 'type_for_cetak': 'utama'
            },
            'urgent': {
                'table_name': 'angsuran_dana_urgent', 'date_column': 'tanggal_jatuh_tempo',
                'type_column': 'jenis_dana_urgent', 'default_type': 'Gaji',
                'akun_piutang_map': {'Gaji': '1203', 'THR': '1204'},
                'akun_pendapatan_map': {'Gaji': '4103', 'THR': '4104'},
                'akun_denda': '4107', 'log_name': 'Urgent', 'type_for_cetak': 'urgent'
            }
        }

        for payment in data.get('payments', []):
            jenis = payment.get('jenis')
            if jenis in configs:
                new_sisa_gaji, cetak_info = _proses_satu_pembayaran(cursor, payment, shared_data, configs[jenis])
                shared_data['sisa_gaji_berjalan'] = new_sisa_gaji
                if cetak_info:
                    cetak_info_list.append(cetak_info)

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pembayaran berhasil diproses dan status telah menjadi bayar angsuran!', 'cetak_info': cetak_info_list}), 200
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
    
    try:
        data['nominal'] = parse_float(data.get('nominal'), 'Nominal Penarikan')
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400
        
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
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
        nominal = data.get('nominal')
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
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin, COUNT(id) as jml_belum_bayar
            FROM angsuran_multiguna_tempo 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        multiguna = cursor.fetchone()
        
        # 2. Kalkulasi Sisa Pinjaman Dana Urgent
        cursor.execute("""
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin, COUNT(id) as jml_belum_bayar
            FROM angsuran_dana_urgent 
            WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        urgent = cursor.fetchone()
        
        today = datetime.now().date()
        denda_multiguna = 0.0
        denda_urgent = 0.0
        
        # Cek Mode Migrasi
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        if denda_aktif:
            # Kalkulasi Denda Keterlambatan Multiguna
            cursor.execute("SELECT jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, tagihan_denda, angsuran_denda, jenis_pinjaman FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                denda_calc, _ = hitung_denda_keterlambatan(
                    jatuh_tempo=row.get('jatuh_tempo'),
                    tgl_bayar=row.get('tgl_bayar'),
                    tagihan_pokok=row.get('tagihan_pokok'),
                    tagihan_margin=row.get('tagihan_margin'),
                    angsuran_pokok=row.get('angsuran_pokok'),
                    angsuran_margin=row.get('angsuran_margin'),
                    tagihan_denda_db=row.get('tagihan_denda'),
                    angsuran_denda=row.get('angsuran_denda'),
                    denda_aktif=denda_aktif,
                    jenis_pinjaman=row.get('jenis_pinjaman', 'Multiguna'),
                    tgl_referensi=today
                )
                denda_multiguna += denda_calc

            # Kalkulasi Denda Keterlambatan Urgent
            cursor.execute("SELECT tanggal_jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, tagihan_denda, angsuran_denda, jenis_dana_urgent FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            for row in cursor.fetchall():
                denda_calc, _ = hitung_denda_keterlambatan(
                    jatuh_tempo=row.get('tanggal_jatuh_tempo'),
                    tgl_bayar=row.get('tgl_bayar'),
                    tagihan_pokok=row.get('tagihan_pokok'),
                    tagihan_margin=row.get('tagihan_margin'),
                    angsuran_pokok=row.get('angsuran_pokok'),
                    angsuran_margin=row.get('angsuran_margin'),
                    tagihan_denda_db=row.get('tagihan_denda'),
                    angsuran_denda=row.get('angsuran_denda'),
                    denda_aktif=denda_aktif,
                    jenis_pinjaman=row.get('jenis_dana_urgent', 'urgent'),
                    tgl_referensi=today
                )
                denda_urgent += denda_calc

        jml_belum_bayar_multi = multiguna['jml_belum_bayar'] if multiguna and multiguna['jml_belum_bayar'] else 0
        jml_belum_bayar_urgent = urgent['jml_belum_bayar'] if urgent and urgent['jml_belum_bayar'] else 0
        edc_multiguna = jml_belum_bayar_multi * 5000
        edc_urgent = jml_belum_bayar_urgent * 5000

        total_multiguna = float(multiguna['sisa_pokok'] or 0) + float(multiguna['sisa_margin'] or 0) + denda_multiguna + edc_multiguna
        total_urgent = float(urgent['sisa_pokok'] or 0) + float(urgent['sisa_margin'] or 0) + denda_urgent + edc_urgent

        cursor.execute("SELECT simpanan_pokok, simpanan_wajib, total_simpanan FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
        simpanan = cursor.fetchone()
        sim_pokok = float(simpanan['simpanan_pokok'] or 0) if simpanan else 0
        sim_wajib = float(simpanan['simpanan_wajib'] or 0) if simpanan else 0
        sim_total = float(simpanan['total_simpanan'] or 0) if simpanan else 0

        return jsonify({
            'status': 'success',
            'data': {
                'multiguna': {
                    'sisa_pokok': float(multiguna['sisa_pokok'] or 0), 'sisa_margin': float(multiguna['sisa_margin'] or 0),
                    'denda': denda_multiguna, 'edc': edc_multiguna, 'total_pelunasan': total_multiguna
                },
                'urgent': {
                    'sisa_pokok': float(urgent['sisa_pokok'] or 0), 'sisa_margin': float(urgent['sisa_margin'] or 0),
                    'denda': denda_urgent, 'edc': edc_urgent, 'total_pelunasan': total_urgent
                },
                'simpanan': {
                    'simpanan_pokok': sim_pokok,
                    'simpanan_wajib': sim_wajib,
                    'total_simpanan': sim_total
                },
                'total_semua_tagihan': total_multiguna + total_urgent
            }
        }), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: PELUNASAN PINJAMAN KESELURUHAN ===
@api_transaksi_bp.route('/api/pelunasan', methods=['POST'])
def pelunasan_pinjaman():
    data = request.json
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    try:
        data['edc_utama'] = parse_float(data.get('edc_utama'), 'Biaya EDC Utama')
        data['edc_urgent'] = parse_float(data.get('edc_urgent'), 'Biaya EDC Urgent')
        data['denda_utama'] = parse_float(data.get('denda_utama'), 'Denda Utama')
        data['denda_urgent'] = parse_float(data.get('denda_urgent'), 'Denda Urgent')
        data['nominal_bayar_tunai'] = parse_float(data.get('nominal_bayar_tunai'), 'Nominal Bayar Tunai')
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400
        
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Pelunasan Pinjaman', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Pelunasan diajukan! Menunggu Approval dari Manager.'}), 201
        finally: cursor.close(); conn.close()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        no_anggota = data.get('no_anggota')
        metode_pelunasan = data.get('metode_pelunasan', 'tunai') # 'simpanan' atau 'tunai'
        tanggal_bayar = data.get('tanggal_bayar') or datetime.now().strftime('%Y-%m-%d')
        
        edc_utama_val = data.get('edc_utama')
        edc_urgent_val = data.get('edc_urgent')
        denda_utama_val = data.get('denda_utama')
        denda_urgent_val = data.get('denda_urgent')
        nominal_bayar_tunai = data.get('nominal_bayar_tunai')
        
        cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        member = cursor.fetchone()
        if not member: raise ValueError("Anggota tidak ditemukan.")
        nama_anggota = member['nama_anggota']
        cabang_member = member.get('cabang') or session.get('cabang', 'GAS')

        today = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
        
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        # 1. PELUNASAN MULTIGUNA / TEMPO
        cursor.execute("""
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin
            FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        sisa_utama = cursor.fetchone()
        total_pokok_utama = float(sisa_utama['sisa_pokok'] or 0) if sisa_utama else 0
        total_margin_utama = float(sisa_utama['sisa_margin'] or 0) if sisa_utama else 0

        if total_pokok_utama > 0 or total_margin_utama > 0:
            cursor.execute("SELECT MIN(id) as first_id FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            first_id_row = cursor.fetchone()
            first_id_utama = first_id_row['first_id'] if first_id_row else None

            cursor.execute("""
                UPDATE angsuran_multiguna_tempo 
                SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS', tgl_bayar = %s
                WHERE no_anggota = %s AND status = 'BELUM BAYAR'
            """, (tanggal_bayar, no_anggota))

            if first_id_utama:
                cursor.execute("""
                    UPDATE angsuran_multiguna_tempo
                    SET tagihan_denda = %s, angsuran_denda = %s, edc = %s
                    WHERE id = %s
                """, (denda_utama_val, denda_utama_val, edc_utama_val if edc_utama_val > 0 else None, first_id_utama))
            
        total_denda_utama = denda_utama_val

        # 2. PELUNASAN DANA URGENT
        cursor.execute("""
            SELECT SUM(tagihan_pokok - angsuran_pokok) as sisa_pokok, SUM(tagihan_margin - angsuran_margin) as sisa_margin
            FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR'
        """, (no_anggota,))
        sisa_urgent = cursor.fetchone()
        total_pokok_urgent = float(sisa_urgent['sisa_pokok'] or 0) if sisa_urgent else 0
        total_margin_urgent = float(sisa_urgent['sisa_margin'] or 0) if sisa_urgent else 0

        if total_pokok_urgent > 0 or total_margin_urgent > 0:
            cursor.execute("SELECT MIN(id) as first_id FROM angsuran_dana_urgent WHERE no_anggota = %s AND status = 'BELUM BAYAR'", (no_anggota,))
            first_id_row = cursor.fetchone()
            first_id_urgent = first_id_row['first_id'] if first_id_row else None

            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok = tagihan_pokok, angsuran_margin = tagihan_margin, status = 'LUNAS', tgl_bayar = %s
                WHERE no_anggota = %s AND status = 'BELUM BAYAR'
            """, (tanggal_bayar, no_anggota))

            if first_id_urgent:
                cursor.execute("""
                    UPDATE angsuran_dana_urgent
                    SET tagihan_denda = %s, angsuran_denda = %s, edc = %s
                    WHERE id = %s
                """, (denda_urgent_val, denda_urgent_val, edc_urgent_val if edc_urgent_val > 0 else None, first_id_urgent))
            
        total_denda_urgent = denda_urgent_val

        total_kewajiban_utama = total_pokok_utama + total_margin_utama + total_denda_utama + edc_utama_val
        total_kewajiban_urgent = total_pokok_urgent + total_margin_urgent + total_denda_urgent + edc_urgent_val
        total_kewajiban_semua = total_kewajiban_utama + total_kewajiban_urgent
        
        if total_kewajiban_semua <= 0: raise ValueError("Tidak ada tagihan yang bisa dilunasi.")

        # 3. METODE PELUNASAN (SIMPANAN / TUNAI)
        if metode_pelunasan == 'simpanan':
            cursor.execute("SELECT simpanan_pokok, simpanan_wajib FROM simpanan WHERE nomor_anggota = %s FOR UPDATE", (no_anggota, ))
            simpanan = cursor.fetchone()
            saldo_pokok = float(simpanan['simpanan_pokok']) if simpanan else 0
            saldo_wajib = float(simpanan['simpanan_wajib']) if simpanan else 0
            saldo_total = saldo_pokok + saldo_wajib

            bayar_dari_simpanan = min(saldo_total, total_kewajiban_semua)
            kekurangan = total_kewajiban_semua - bayar_dari_simpanan
            
            if nominal_bayar_tunai < kekurangan - 0.01:
                raise ValueError(f"Uang tunai kurang! Kekurangan dari simpanan adalah Rp {kekurangan:,.0f}.")
            
            bayar_tunai = kekurangan

            if bayar_dari_simpanan > 0:
                sisa_potongan = bayar_dari_simpanan
                potong_wajib = min(saldo_wajib, sisa_potongan)
                sisa_potongan -= potong_wajib
                potong_pokok = sisa_potongan
                
                cursor.execute("UPDATE simpanan SET simpanan_wajib = simpanan_wajib - %s, simpanan_pokok = simpanan_pokok - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (potong_wajib, potong_pokok, bayar_dari_simpanan, no_anggota))
                if potong_wajib > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '3102', f"Debit Simp Wajib (Pelunasan) - {nama_anggota}", potong_wajib, 0, cabang_member)
                if potong_pokok > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '3101', f"Debit Simp Pokok (Pelunasan) - {nama_anggota}", potong_pokok, 0, cabang_member)
            
            if bayar_tunai > 0:
                catat_jurnal_cabang(cursor, tanggal_bayar, '1101', f"Kas Masuk Pelunasan (Tunai Tambahan) - {nama_anggota}", bayar_tunai, 0, cabang_member)

        else:
            if nominal_bayar_tunai < total_kewajiban_semua - 0.01:
                raise ValueError(f"Uang tunai kurang! Total tagihan adalah Rp {total_kewajiban_semua:,.0f}.")
            bayar_tunai = total_kewajiban_semua
            catat_jurnal_cabang(cursor, tanggal_bayar, '1101', f"Kas Masuk Pelunasan Tunai - {nama_anggota}", bayar_tunai, 0, cabang_member)

        # 4. PENGAKUAN PENDAPATAN JURNAL 
        if total_kewajiban_utama > 0:
            j_pinjaman = 'Multiguna' # Asumsi default, bisa diperbaiki jika perlu info jenis pinjaman spesifik
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            akun_pendapatan = '4101' if j_pinjaman == 'Multiguna' else '4102'
            if total_pokok_utama > 0: catat_jurnal_cabang(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok {j_pinjaman} - {nama_anggota}", 0, total_pokok_utama, cabang_member)
            if total_margin_utama > 0: catat_jurnal_cabang(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin {j_pinjaman} - {nama_anggota}", 0, total_margin_utama, cabang_member)
            if total_denda_utama > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4106', f"Pendapatan Denda {j_pinjaman} - {nama_anggota}", 0, total_denda_utama, cabang_member)
            if edc_utama_val > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin {j_pinjaman} - {nama_anggota}", 0, edc_utama_val, cabang_member)

        if total_kewajiban_urgent > 0:
            j_urgent = 'Gaji' # Asumsi default
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            akun_pendapatan = '4103' if j_urgent == 'Gaji' else '4104'
            if total_pokok_urgent > 0: catat_jurnal_cabang(cursor, tanggal_bayar, akun_piutang, f"Pelunasan Pokok Urgent {j_urgent} - {nama_anggota}", 0, total_pokok_urgent, cabang_member)
            if total_margin_urgent > 0: catat_jurnal_cabang(cursor, tanggal_bayar, akun_pendapatan, f"Pendapatan Margin Urgent {j_urgent} - {nama_anggota}", 0, total_margin_urgent, cabang_member)
            if total_denda_urgent > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4107', f"Pendapatan Denda Urgent {j_urgent} - {nama_anggota}", 0, total_denda_urgent, cabang_member)
            if edc_urgent_val > 0: catat_jurnal_cabang(cursor, tanggal_bayar, '4105', f"Pendapatan EDC/Admin Urgent {j_urgent} - {nama_anggota}", 0, edc_urgent_val, cabang_member)

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Pelunasan Berhasil Diproses menggunakan {metode_pelunasan.upper()}!', 'cetak_info': {'no_anggota': no_anggota, 'tanggal_bayar': tanggal_bayar[:10]}}), 200
    except ValueError as ve:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# === API: PUSAT DATA APPROVAL MANAGER ===
@api_transaksi_bp.route('/api/approval_queue', methods=['GET'])
def get_approval_queue():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang') or 'GAS'
    role = session.get('role')
    filter_cabang = request.args.get('cabang')
    try:
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
    
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Batal Angsuran', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Pembatalan angsuran diajukan! Menunggu Approval dari Manager.'}), 201
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
        finally: cursor.close(); conn.close()
        
    jenis = data.get('jenis')
    id_tagihan = data.get('id_tagihan')
    if not jenis:
        if data.get('kategori') == 'utama' or 'jenis_pinjaman' in data: jenis = 'utama'
        elif data.get('kategori') == 'urgent' or 'jenis_dana_urgent' in data: jenis = 'urgent'
        
    if str(jenis).lower() in ['multiguna', 'tempo', 'utama']: jenis = 'utama'
    elif str(jenis).lower() in ['gaji', 'thr', 'dana urgent', 'urgent']: jenis = 'urgent'
    
    id_tagihan = data.get('id_tagihan') or data.get('id')
    alasan_batal = data.get('alasan', 'Tidak ada alasan')
    
    if not id_tagihan or not jenis:
        return jsonify({'status': 'error', 'message': f'Data batal angsuran tidak lengkap. Payload: {json.dumps(data)}'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Inisialisasi variabel untuk mencegah NameError
        nama_anggota = 'N/A'
        pokok = margin = denda = 0.0

        conn.start_transaction()
        tanggal_batal = datetime.now().strftime('%Y-%m-%d')

        if jenis == 'utama':
            cursor.execute("SELECT * FROM angsuran_multiguna_tempo WHERE id = %s AND status != 'LUNAS TOP-UP' AND (status = 'LUNAS' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)", (id_tagihan,))
            row = cursor.fetchone()
            if not row: raise ValueError("Data angsuran tidak ditemukan, atau tidak ada pembayaran yang bisa dibatalkan (Lunas Top-Up tidak dapat dibatalkan otomatis).")
            
            no_anggota = row['no_anggota']
            
            # Ambil cabang dari anggota yang bersangkutan untuk pencatatan jurnal yang akurat
            cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
            identitas_row = cursor.fetchone()
            cabang_member = (identitas_row['cabang'] if identitas_row and identitas_row.get('cabang') else session.get('cabang', 'GAS'))
            nama_anggota = (identitas_row['nama_anggota'] if identitas_row else row.get('nama_anggota', 'Anggota'))

            pokok = float(row.get('angsuran_pokok') or 0)
            margin = float(row.get('angsuran_margin') or 0)
            denda = float(row.get('angsuran_denda') or 0)
            tgl_bayar = row.get('tgl_bayar') or tanggal_batal
            simpanan_batal = float(row.get('simpanan_wajib_bayar') or 0)
            edc_val = float(row.get('edc') or 0)
            j_pinjaman = row.get('jenis_pinjaman') or 'Multiguna'
            
            cursor.execute("""
                UPDATE angsuran_multiguna_tempo 
                SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0, simpanan_wajib_bayar=0 
                WHERE id=%s
            """, (id_tagihan,))
            
            akun_piutang = '1201' if j_pinjaman == 'Multiguna' else '1202'
            akun_pendapatan = '4101' if j_pinjaman == 'Multiguna' else '4102'
            
            total_kas_batal = pokok + margin + denda
            catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal Angsuran {j_pinjaman} - {nama_anggota}", 0, total_kas_batal, cabang_member)
            if edc_val > 0:
                catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal EDC/Admin {j_pinjaman} - {nama_anggota}", 0, edc_val, cabang_member)
            catat_jurnal_cabang(cursor, tgl_bayar, akun_piutang, f"Batal Pelunasan Pokok {j_pinjaman} - {nama_anggota}", pokok, 0, cabang_member)
            catat_jurnal_cabang(cursor, tgl_bayar, akun_pendapatan, f"Batal Pendapatan Margin {j_pinjaman} - {nama_anggota}", margin, 0, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tgl_bayar, '4106', f"Batal Pendapatan Denda {j_pinjaman} - {nama_anggota}", denda, 0, cabang_member)
            if edc_val > 0: catat_jurnal_cabang(cursor, tgl_bayar, '4105', f"Batal Pendapatan EDC/Admin {j_pinjaman} - {nama_anggota}", edc_val, 0, cabang_member)

            # --- BATAL SIMPANAN WAJIB ---
            if simpanan_batal > 0:
                cursor.execute("UPDATE simpanan SET simpanan_wajib = simpanan_wajib - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (simpanan_batal, simpanan_batal, no_anggota))
                catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal Kas Simpanan Wajib - {nama_anggota}", 0, simpanan_batal, cabang_member)
                catat_jurnal_cabang(cursor, tgl_bayar, '3102', f"Batal Simpanan Wajib - {nama_anggota}", simpanan_batal, 0, cabang_member)

        elif jenis == 'urgent':
            cursor.execute("SELECT * FROM angsuran_dana_urgent WHERE id = %s AND status != 'LUNAS TOP-UP' AND (status = 'LUNAS' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)", (id_tagihan,))
            row = cursor.fetchone()
            if not row: raise ValueError("Data angsuran urgent tidak ditemukan atau tidak ada pembayaran yang bisa dibatalkan.")
            
            no_anggota = row['no_anggota']

            # Ambil cabang dari anggota yang bersangkutan untuk pencatatan jurnal yang akurat
            cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
            identitas_row = cursor.fetchone()
            cabang_member = (identitas_row['cabang'] if identitas_row and identitas_row.get('cabang') else session.get('cabang', 'GAS'))
            nama_anggota = (identitas_row['nama_anggota'] if identitas_row else row.get('nama_anggota', 'Anggota'))

            pokok = float(row.get('angsuran_pokok') or 0)
            margin = float(row.get('angsuran_margin') or 0)
            denda = float(row.get('angsuran_denda') or 0)
            tgl_bayar = row.get('tgl_bayar') or tanggal_batal
            simpanan_batal = float(row.get('simpanan_wajib_bayar') or 0)
            edc_val = float(row.get('edc') or 0)
            j_urgent = row.get('jenis_dana_urgent') or 'Gaji'
            
            cursor.execute("""
                UPDATE angsuran_dana_urgent 
                SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0, simpanan_wajib_bayar=0 
                WHERE id=%s
            """, (id_tagihan,))
            
            akun_piutang = '1203' if j_urgent == 'Gaji' else '1204'
            akun_pendapatan = '4103' if j_urgent == 'Gaji' else '4104'
            
            total_kas_batal = pokok + margin + denda
            catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal Angsuran Urgent {j_urgent} - {nama_anggota}", 0, total_kas_batal, cabang_member)
            if edc_val > 0:
                catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal EDC/Admin Urgent {j_urgent} - {nama_anggota}", 0, edc_val, cabang_member)
            catat_jurnal_cabang(cursor, tgl_bayar, akun_piutang, f"Batal Pelunasan Pokok Urgent {j_urgent} - {nama_anggota}", pokok, 0, cabang_member)
            catat_jurnal_cabang(cursor, tgl_bayar, akun_pendapatan, f"Batal Pendapatan Margin Urgent {j_urgent} - {nama_anggota}", margin, 0, cabang_member)
            if denda > 0: catat_jurnal_cabang(cursor, tgl_bayar, '4107', f"Batal Pendapatan Denda Urgent {j_urgent} - {nama_anggota}", denda, 0, cabang_member)
            if edc_val > 0: catat_jurnal_cabang(cursor, tgl_bayar, '4105', f"Batal Pendapatan EDC/Admin Urgent {j_urgent} - {nama_anggota}", edc_val, 0, cabang_member)

            # --- BATAL SIMPANAN WAJIB ---
            if simpanan_batal > 0:
                cursor.execute("UPDATE simpanan SET simpanan_wajib = simpanan_wajib - %s, total_simpanan = total_simpanan - %s WHERE nomor_anggota = %s", (simpanan_batal, simpanan_batal, no_anggota))
                catat_jurnal_cabang(cursor, tgl_bayar, '1101', f"Batal Kas Simpanan Wajib - {nama_anggota}", 0, simpanan_batal, cabang_member)
                catat_jurnal_cabang(cursor, tgl_bayar, '3102', f"Batal Simpanan Wajib - {nama_anggota}", simpanan_batal, 0, cabang_member)
        else:
            raise ValueError(f"Jenis pinjaman '{jenis}' tidak valid untuk pembatalan.")

        # --- AUDIT LOG ---
        try:
            detail_log = json.dumps({'id_tagihan': id_tagihan, 'jenis': jenis, 'nama_anggota': nama_anggota, 'pokok': pokok, 'margin': margin, 'alasan': alasan_batal})
            user_aktif = session.get('nama_lengkap', session.get('username', 'System'))
            role_aktif = session.get('role', 'System')
            cursor.execute("INSERT INTO audit_logs (username, role, cabang, aksi, detail) VALUES (%s, %s, %s, %s, %s)", 
                           (user_aktif, role_aktif, cabang_member, 'BATAL_ANGSURAN', detail_log))
        except Exception:
            pass

        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))

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
    
    is_approval = data.get('is_approval_execution', False)
    approval_id = data.get('approval_id', None)
    
    if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)", ('Batal Pencairan', json.dumps(data), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Pembatalan pencairan diajukan! Menunggu Approval dari Manager.'}), 201
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
        finally: cursor.close(); conn.close()
        
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
    alasan_batal = data.get('alasan', 'Tidak ada alasan')
    
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

        if not tgl_pencairan:
            raise ValueError("Tanggal pencairan tidak valid atau tidak disertakan dari sistem.")

        if jenis == 'utama':
            cursor.execute("""
                SELECT id FROM angsuran_multiguna_tempo 
                WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s 
                AND status != 'LUNAS TOP-UP' 
                AND (status != 'BELUM BAYAR' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)
            """, (no_anggota, tgl_pencairan))
            if cursor.fetchone(): raise ValueError("Tidak bisa membatalkan pencairan karena sudah ada angsuran yang dibayar. Batalkan angsurannya terlebih dahulu.")
            
            cursor.execute("SELECT * FROM pencairan_multiguna_tempo WHERE no_anggota=%s AND DATE(tanggal_cair)=%s", (no_anggota, tgl_pencairan))
            pencairan = cursor.fetchone()
            if not pencairan: raise ValueError("Data pencairan tidak ditemukan.")
            
            # Ambil cabang dari anggota yang bersangkutan untuk pencatatan jurnal yang akurat
            cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
            identitas_row = cursor.fetchone()
            cabang_member = (identitas_row['cabang'] if identitas_row and identitas_row.get('cabang') else session.get('cabang', 'GAS'))
            nama_anggota = (identitas_row['nama_anggota'] if identitas_row else pencairan.get('nama_anggota', 'Anggota'))

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
                # AMBIL KEMBALI NILAI YANG DILUNASI SECARA AKURAT
                cursor.execute("""
                    SELECT SUM(tagihan_pokok) as pokok, SUM(tagihan_margin) as margin, SUM(tagihan_denda) as denda
                    FROM angsuran_multiguna_tempo
                    WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'
                """, (no_anggota, tgl_pencairan))
                reversal_topup = cursor.fetchone()
                
                pokok_batal_topup = float(reversal_topup.get('pokok') or 0)
                margin_batal_topup = float(reversal_topup.get('margin') or 0)
                denda_batal_topup = float(reversal_topup.get('denda') or 0)

                # JURNAL PEMBALIK YANG AKURAT
                akun_pendapatan_lama = '4101' # Asumsi default
                if pokok_batal_topup > 0: catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang, f"Batal Pelunasan Pokok (Top-Up) - {nama_anggota}", pokok_batal_topup, 0, cabang_member)
                if margin_batal_topup > 0: catat_jurnal_cabang(cursor, tanggal_batal, akun_pendapatan_lama, f"Batal Pendapatan Margin (Top-Up) - {nama_anggota}", margin_batal_topup, 0, cabang_member)
                if denda_batal_topup > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4106', f"Batal Pendapatan Denda (Top-Up) - {nama_anggota}", denda_batal_topup, 0, cabang_member)

                cursor.execute("UPDATE angsuran_multiguna_tempo SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, status='BELUM BAYAR', tgl_bayar=NULL WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'", (no_anggota, tgl_pencairan))
            if potongan_urgent > 0:
                cursor.execute("""
                    SELECT SUM(tagihan_pokok) as pokok, SUM(tagihan_margin) as margin, SUM(tagihan_denda) as denda, jenis_dana_urgent
                    FROM angsuran_dana_urgent
                    WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'
                    GROUP BY jenis_dana_urgent
                """, (no_anggota, tgl_pencairan))
                for reversal_urgent in cursor.fetchall():
                    pokok_batal_urgent = float(reversal_urgent.get('pokok') or 0)
                    margin_batal_urgent = float(reversal_urgent.get('margin') or 0)
                    denda_batal_urgent = float(reversal_urgent.get('denda') or 0)
                    j_urgent_lama = reversal_urgent.get('jenis_dana_urgent') or 'Gaji'
                    akun_piutang_urgent = '1203' if j_urgent_lama == 'Gaji' else '1204'
                    akun_pendapatan_urgent = '4103' if j_urgent_lama == 'Gaji' else '4104'
                    if pokok_batal_urgent > 0: catat_jurnal_cabang(cursor, tanggal_batal, akun_piutang_urgent, f"Batal Pelunasan Pokok Urgent (Top-Up) - {nama_anggota}", pokok_batal_urgent, 0, cabang_member)
                    if margin_batal_urgent > 0: catat_jurnal_cabang(cursor, tanggal_batal, akun_pendapatan_urgent, f"Batal Pendapatan Margin Urgent (Top-Up) - {nama_anggota}", margin_batal_urgent, 0, cabang_member)
                    if denda_batal_urgent > 0: catat_jurnal_cabang(cursor, tanggal_batal, '4107', f"Batal Pendapatan Denda Urgent (Top-Up) - {nama_anggota}", denda_batal_urgent, 0, cabang_member)
                cursor.execute("UPDATE angsuran_dana_urgent SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, status='BELUM BAYAR', tgl_bayar=NULL WHERE no_anggota=%s AND DATE(tgl_bayar)=%s AND status='LUNAS TOP-UP'", (no_anggota, tgl_pencairan))

        elif jenis == 'urgent':
            cursor.execute("""
                SELECT id FROM angsuran_dana_urgent 
                WHERE no_anggota=%s AND DATE(tgl_pencairan)=%s 
                AND status != 'LUNAS TOP-UP' 
                AND (status != 'BELUM BAYAR' OR angsuran_pokok > 0 OR angsuran_margin > 0 OR angsuran_denda > 0)
            """, (no_anggota, tgl_pencairan))
            if cursor.fetchone(): raise ValueError("Tidak bisa membatalkan pencairan karena sudah ada pembayaran yang lunas. Batalkan angsuran terlebih dahulu.")
            
            cursor.execute("SELECT * FROM pencairan_dana_urgent WHERE no_anggota=%s AND DATE(tanggal_pencairan_dana_urgent)=%s", (no_anggota, tgl_pencairan))
            pencairan = cursor.fetchone()
            if not pencairan: raise ValueError("Data pencairan urgent tidak ditemukan.")
            
            # Ambil cabang dari anggota yang bersangkutan untuk pencatatan jurnal yang akurat
            cursor.execute("SELECT nama_anggota, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
            identitas_row = cursor.fetchone()
            cabang_member = (identitas_row['cabang'] if identitas_row and identitas_row.get('cabang') else session.get('cabang', 'GAS'))
            nama_anggota = (identitas_row['nama_anggota'] if identitas_row else pencairan.get('nama_anggota', 'Anggota'))

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
            detail_log = json.dumps({'no_anggota': no_anggota, 'jenis': jenis, 'nama_anggota': nama_anggota, 'tanggal_cair': tgl_pencairan, 'alasan': alasan_batal})
            user_aktif = session.get('nama_lengkap', session.get('username', 'System'))
            role_aktif = session.get('role', 'System')
            cursor.execute("INSERT INTO audit_logs (username, role, cabang, aksi, detail) VALUES (%s, %s, %s, %s, %s)", 
                           (user_aktif, role_aktif, cabang_member, 'BATAL_PENCAIRAN', detail_log))
        except Exception:
            pass

        if is_approval and approval_id:
            cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))

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
        writer.writerow(['no_referensi_excel', 'nama_anggota', 'cabang', 'tgl_lahir', 'no_telp', 'nik_ktp', 'nik_kk', 'alamat_ktp', 'alamat_tagih', 'status_tempat_tinggal', 'email', 'password', 'pt_instansi', 'status_karyawan', 'jabatan', 'awal_bekerja', 'lama_kerja', 'akhir_bekerja', 'no_jmo', 'status_jmo', 'bank', 'no_rek', 'nama_penanggung_jawab', 'no_telp_penanggung_jawab', 'bank_penanggung_jawab', 'no_rek_penanggung_jawab', 'kol', 'kriteria', 'marketing', 'status_pernikahan', 'alamat_penanggung_jawab', 'simpanan_pokok', 'simpanan_wajib'])
        writer.writerow(['1', 'SAIPU NAWASI (LANCAR)', 'GAS', '1990-01-01', '08123456789', '367100000000', '367100000000', 'Jl. Mawar No 1', 'Jl. Mawar No 1', 'Milik Sendiri', 'email@test.com', '123456', 'PT ABC', 'Tetap', 'Staff', '2020-01-01', '6 Tahun', '', '112233', 'Aktif', 'BCA', '123456789', 'Istri', '081222', 'BRI', '987654', 'Lancar', 'VIP', 'Sales A', 'Menikah', 'Jl. Mawar No 2', '100000', '250000'])
        writer.writerow(['2', 'BUDI SANTOSO (MACET)', 'GAS', '1985-05-15', '08133333', '367100000001', '367100000001', 'Jl. Melati No 2', 'Jl. Melati No 2', 'Sewa', 'budi@test.com', '123456', 'PT XYZ', 'Tetap', 'Staff', '2015-01-01', '11 Tahun', '', '112244', 'Aktif', 'Mandiri', '987654321', 'Istri', '08133333', 'BCA', '112233', 'Macet', 'Reguler', 'Sales B', 'Belum Menikah', 'Jl. Melati No 3', '50000', '150000'])
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