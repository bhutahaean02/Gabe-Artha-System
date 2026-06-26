from flask import Blueprint, request, jsonify, session, send_file
from datetime import datetime, timedelta
import calendar
import json
import pandas as pd
import io

from db import get_db_connection
from api_helpers import extract_gmaps_coordinates

api_laporan_bp = Blueprint('api_laporan', __name__)

# === API: KOORDINAT ANGGOTA UNTUK PETA ===
@api_laporan_bp.route('/api/koordinat_anggota', methods=['GET'])
def get_koordinat_anggota():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    try:
        # PERBAIKAN: Query diubah untuk tidak lagi bergantung pada kolom `lat` dan `lng` di database,
        # yang kemungkinan menjadi penyebab error jika kolom tersebut belum ada (missing).
        # Sekarang, sistem akan selalu mencoba mengekstrak koordinat dari `alamat_tagih`.
        query = """
            SELECT 
                i.no_anggota, i.nama_anggota, i.alamat_tagih,
                COALESCE(overdue.kol_count, 0) AS kol_count
            FROM 
                identitas i
            LEFT JOIN (
                SELECT
                    no_anggota,
                    COUNT(*) AS kol_count
                FROM (
                    SELECT no_anggota FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR' AND jatuh_tempo < CURDATE()
                    UNION ALL
                    SELECT no_anggota FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR' AND tanggal_jatuh_tempo < CURDATE()
                ) AS all_overdue
                GROUP BY no_anggota
            ) AS overdue ON i.no_anggota = overdue.no_anggota
            WHERE 
                i.alamat_tagih IS NOT NULL AND i.alamat_tagih != ''
        """
        params = []
        if role != 'Super Admin':
            query += " AND i.cabang = %s"
            params.append(cabang)
            
        cursor.execute(query, tuple(params))
        anggota_list = cursor.fetchall()
        
        koordinat_list = []
        for anggota in anggota_list:
            lat = None
            lng = None
            link = anggota.get('alamat_tagih')

            # Pengecekan 'http' untuk memastikan itu URL, bukan alamat teks biasa.
            if not link or 'http' not in str(link):
                continue # Lewati jika bukan URL, sesuai permintaan.

            coord_result = extract_gmaps_coordinates(link)
            if coord_result.get('status') == 'success':
                lat = coord_result.get('lat')
                lng = coord_result.get('lng')
            else:
                continue # Lewati jika ekstraksi dari URL gagal.

            # Pastikan kita punya koordinat valid sebelum melanjutkan
            if lat and lng:
                kol_count = int(anggota.get('kol_count', 0) or 0)
                status = "LANCAR"
                if 1 <= kol_count <= 6: status = "Kurang Lancar"
                elif 7 <= kol_count <= 12: status = "Macet"
                elif kol_count > 12: status = "WO"

                # Buat dictionary baru untuk dikirim ke frontend
                koordinat_data = {
                    'no_anggota': anggota['no_anggota'],
                    'nama_anggota': anggota['nama_anggota'],
                    'alamat_tagih': anggota['alamat_tagih'],
                    'lat': lat,
                    'lon': lng, # Frontend (monitoring_lokasi.js) mengharapkan 'lon'
                    'status': status
                }
                koordinat_list.append(koordinat_data)
                
        return jsonify({'status': 'success', 'data': koordinat_list}), 200
    except Exception as e:
        import traceback
        # Mengembalikan pesan error yang lebih umum namun tetap informatif dengan traceback.
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500
    finally:
        cursor.close()
        conn.close()

# === API: MONITORING & LAPORAN HARIAN ===
@api_laporan_bp.route('/api/evaluasi_dashboard', methods=['GET'])
def evaluasi_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        today = datetime.now().date()
        def get_totals(start, end):
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN c.kategori = 'PENDAPATAN' THEN j.kredit - j.debit ELSE 0 END) as pendapatan,
                    SUM(CASE WHEN c.kategori = 'BEBAN' THEN j.debit - j.kredit ELSE 0 END) as beban
                FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id 
                WHERE c.kategori IN ('PENDAPATAN', 'BEBAN') AND j.cabang = %s AND j.tanggal BETWEEN %s AND %s
            """, (cabang, start, end))
            res = cursor.fetchone()
            return float(res['pendapatan'] or 0), float(res['beban'] or 0)

        try: bulan_lalu_hari_ini = today.replace(month=today.month - 1)
        except ValueError:
            bulan_lalu = today.month - 1 if today.month > 1 else 12
            tahun_lalu = today.year if today.month > 1 else today.year - 1
            last_day = calendar.monthrange(tahun_lalu, bulan_lalu)[1]
            bulan_lalu_hari_ini = today.replace(year=tahun_lalu, month=bulan_lalu, day=min(today.day, last_day))

        harian_now_p, harian_now_b = get_totals(today, today)
        harian_prev_p, harian_prev_b = get_totals(bulan_lalu_hari_ini, bulan_lalu_hari_ini)

        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        start_of_prev_week = start_of_week - timedelta(days=28)
        end_of_prev_week = end_of_week - timedelta(days=28)

        mingguan_now_p, mingguan_now_b = get_totals(start_of_week, end_of_week)
        mingguan_prev_p, mingguan_prev_b = get_totals(start_of_prev_week, end_of_prev_week)

        cursor.execute("""
            SELECT 
                MONTH(j.tanggal) as bulan,
                SUM(CASE WHEN c.kategori = 'PENDAPATAN' THEN j.kredit - j.debit ELSE 0 END) as pendapatan,
                SUM(CASE WHEN c.kategori = 'BEBAN' THEN j.debit - j.kredit ELSE 0 END) as beban
            FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id 
            WHERE c.kategori IN ('PENDAPATAN', 'BEBAN') AND j.cabang = %s AND YEAR(j.tanggal) = %s
            GROUP BY MONTH(j.tanggal)
        """, (cabang, today.year))
        monthly_data = {row['bulan']: {'pendapatan': float(row['pendapatan'] or 0), 'beban': float(row['beban'] or 0)} for row in cursor.fetchall()}

        bulanan = []
        for month in range(1, today.month + 1):
            start_date = today.replace(month=month, day=1)
            data_bulan = monthly_data.get(month, {'pendapatan': 0.0, 'beban': 0.0})
            bulanan.append({'bulan': start_date.strftime('%b'), 'pendapatan': data_bulan['pendapatan'], 'beban': data_bulan['beban']})

        # --- TAMBAHAN METRIK UTAMA DASHBOARD ---
        cursor.execute("""
            SELECT 
                (SELECT IFNULL(SUM(j.debit - j.kredit), 0) FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'KAS' AND j.cabang = %s) as total_kas,
                (SELECT COUNT(no_anggota) FROM identitas WHERE cabang = %s) as total_anggota,
                (SELECT IFNULL(SUM(s.total_simpanan), 0) FROM simpanan s JOIN identitas i ON s.nomor_anggota = i.no_anggota WHERE i.cabang = %s) as total_simpanan,
                (SELECT IFNULL(SUM(a.tagihan_pokok - a.angsuran_pokok), 0) FROM angsuran_multiguna_tempo a JOIN identitas i ON a.no_anggota = i.no_anggota WHERE a.status = 'BELUM BAYAR' AND i.cabang = %s) +
                (SELECT IFNULL(SUM(a.tagihan_pokok - a.angsuran_pokok), 0) FROM angsuran_dana_urgent a JOIN identitas i ON a.no_anggota = i.no_anggota WHERE a.status = 'BELUM BAYAR' AND i.cabang = %s) as total_piutang
        """, (cabang, cabang, cabang, cabang, cabang))
        summary_res = cursor.fetchone()
        
        total_kas = float(summary_res['total_kas'] or 0)
        total_anggota = summary_res['total_anggota'] or 0
        total_simpanan = float(summary_res['total_simpanan'] or 0)
        total_piutang = float(summary_res['total_piutang'] or 0)

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

@api_laporan_bp.route('/api/monitoring_jmo', methods=['GET'])
def monitoring_jmo_api():
    """
    API untuk mengambil data monitoring status JMO (Jamsostek/BPJS) anggota.
    Menyediakan data detail per anggota dan ringkasan jumlah per status.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    role = session.get('role')
    cabang = session.get('cabang', 'GAS')
    
    try:
        where_clause = ""
        params = []
        # Super Admin bisa melihat semua cabang, role lain hanya bisa melihat cabang masing-masing.
        if role != 'Super Admin':
            where_clause = " WHERE cabang = %s"
            params.append(cabang)

        # 1. Ambil data detail anggota untuk tabel
        query = f"""
            SELECT no_anggota, nama_anggota, nik_ktp, alamat_tagih, email, password, status_jmo, cabang 
            FROM identitas
            {where_clause}
            ORDER BY nama_anggota ASC
        """
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()

        # Amankan password sebelum dikirim ke frontend
        for row in data:
            if row.get('password'):
                row['password'] = '********'

        # 2. Ambil data ringkasan (summary) dengan query yang lebih eksplisit dan aman
        summary_query = f"""
            SELECT 
                COUNT(*) as total_anggota,
                SUM(CASE WHEN TRIM(status_jmo) = 'Aktif' THEN 1 ELSE 0 END) as `Aktif`,
                SUM(CASE WHEN TRIM(status_jmo) = 'Non Aktif' THEN 1 ELSE 0 END) as `Non Aktif`,
                SUM(CASE WHEN TRIM(status_jmo) = 'Riset' THEN 1 ELSE 0 END) as `Riset`,
                SUM(CASE WHEN TRIM(status_jmo) = 'Sudah Cair' THEN 1 ELSE 0 END) as `Sudah Cair`,
                SUM(CASE WHEN TRIM(status_jmo) = 'Link' THEN 1 ELSE 0 END) as `Link`,
                SUM(CASE WHEN TRIM(status_jmo) = 'Lunas' THEN 1 ELSE 0 END) as `Lunas`,
                SUM(CASE WHEN TRIM(status_jmo) = 'BPU' THEN 1 ELSE 0 END) as `BPU`,
                SUM(CASE WHEN status_jmo IS NULL OR TRIM(status_jmo) = '' THEN 1 ELSE 0 END) as `belum_ada_status`
            FROM identitas 
            {where_clause}
        """
        cursor.execute(summary_query, tuple(params))
        summary = cursor.fetchone() # fetchone() karena hanya akan ada satu baris hasil

        # Mengonversi nilai None menjadi 0 untuk konsistensi di frontend
        if summary:
            for key in summary:
                if summary[key] is None:
                    summary[key] = 0
        else:
            # Fallback jika tidak ada anggota sama sekali di cabang tsb
            summary = {'total_anggota': 0, 'Aktif': 0, 'Non Aktif': 0, 'Riset': 0, 'Sudah Cair': 0, 'Link': 0, 'Lunas': 0, 'BPU': 0, 'belum_ada_status': 0}

        return jsonify({'status': 'success', 'data': data, 'summary': summary}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_laporan_bp.route('/api/monitoring_pinjaman', methods=['GET'])
def monitoring_pinjaman_api():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        # PERBAIKAN: Query yang hilang telah ditambahkan untuk mengambil semua data pinjaman yang belum lunas.
        query = """
            SELECT i.no_anggota, i.nama_anggota, i.pt_instansi, i.status_karyawan, i.akhir_bekerja, i.kol,
                a.besar_pinjaman, a.tenor, a.bunga_persen, a.simpanan_wajib_bayar, a.edc,
                a.jatuh_tempo, a.tgl_bayar, a.jenis_pinjaman, a.tgl_pencairan, a.angsuran_ke, a.status as status_pembayaran,
                a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda
            FROM identitas i
            JOIN (
                SELECT id, no_anggota, jenis_pinjaman, tgl_pencairan, jatuh_tempo, tgl_bayar, angsuran_ke, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, status, besar_pinjaman, tenor, bunga_persen, simpanan_wajib_bayar, edc FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT id, no_anggota, jenis_dana_urgent as jenis_pinjaman, tgl_pencairan, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, 1 as angsuran_ke, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, status, tagihan_pokok as besar_pinjaman, 1 as tenor, 0 as bunga_persen, 0 as simpanan_wajib_bayar, edc FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
            ) a ON i.no_anggota = a.no_anggota
            WHERE i.cabang = %s
            ORDER BY a.jatuh_tempo ASC
        """
        cursor.execute(query, (cabang,))
        data = cursor.fetchall()
        today = datetime.now().date()

        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        # --- NEW SUMMARY CALCULATION (Disesuaikan dengan all data tagihan) ---
        cursor.execute("""
            SELECT a.no_anggota, a.jatuh_tempo, a.tgl_bayar, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.jenis_pinjaman
            FROM (
                SELECT no_anggota, jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, jenis_pinjaman FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT no_anggota, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, jenis_dana_urgent as jenis_pinjaman FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
            ) a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE i.cabang = %s
        """, (cabang,))
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
                j_pinjaman = u.get('jenis_pinjaman')
                if j_pinjaman in ['Tempo', 'Gaji', 'THR']:
                    add_denda = (sisa_p + sisa_m) * 0.007 * od_sisa
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
            d['tunggakan_pokok'] = "0"
            d['tunggakan_margin'] = "0"
            d['tunggakan_denda'] = "0"

            if d['jatuh_tempo'] and d.get('status_pembayaran') == 'BELUM BAYAR':
                jt_date = datetime.strptime(str(d['jatuh_tempo'])[:10], '%Y-%m-%d').date() if isinstance(d['jatuh_tempo'], str) else d['jatuh_tempo']
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
                    j_pinjaman = d.get('jenis_pinjaman')
                    if j_pinjaman in ['Tempo', 'Gaji', 'THR']:
                        add_denda = (sisa_p + sisa_m) * 0.007 * od_sisa
                    else:
                        add_denda = (sisa_p + sisa_m) * 0.005 * od_sisa
                    d_kalk = float(d.get('tagihan_denda') or 0) - float(d['angsuran_denda'] or 0) + add_denda
                    
                d_kalk = max(0, d_kalk) if denda_aktif else 0
                
                d['tunggakan_pokok'] = sisa_p if sisa_p > 0.01 else "0"
                d['tunggakan_margin'] = sisa_m if sisa_m > 0.01 else "0"
                d['tunggakan_denda'] = d_kalk if d_kalk > 0.01 else "0"
                d['tagihan_denda'] = d_kalk + float(d['angsuran_denda'] or 0)
            else:
                d['od_hari'], d['tunggakan_denda'] = 0, "0"
            for key, val in d.items():
                if hasattr(val, 'isoformat') and val is not None: d[key] = str(val)
        return jsonify({'status': 'success', 'data': data, 'summary': summary}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_laporan_bp.route('/api/laporan_harian', methods=['GET'])
def get_laporan_harian():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    tanggal = request.args.get('tanggal', datetime.now().strftime('%Y-%m-%d'))
    cabang = session.get('cabang', 'GAS')
    try:
        cursor.execute("SELECT 'Multiguna/Tempo' as jenis, p.no_anggota, p.nama_anggota, p.besar_pinjaman as nominal, p.terima_bersih FROM pencairan_multiguna_tempo p JOIN identitas i ON p.no_anggota = i.no_anggota WHERE DATE(p.tanggal_cair) = %s AND i.cabang = %s UNION ALL SELECT 'Dana Urgent' as jenis, u.no_anggota, u.nama_anggota, u.jumlah_dana_urgent as nominal, u.jumlah_dana_urgent as terima_bersih FROM pencairan_dana_urgent u JOIN identitas i ON u.no_anggota = i.no_anggota WHERE DATE(u.tanggal_pencairan_dana_urgent) = %s AND i.cabang = %s", (tanggal, cabang, tanggal, cabang))
        pencairan = cursor.fetchall()

        cursor.execute("""
            SELECT 'Multiguna/Tempo' as jenis, a.no_anggota, a.nama_anggota, a.angsuran_ke, (a.tagihan_pokok + a.tagihan_margin) as total_tagihan, a.status, a.tgl_bayar 
            FROM angsuran_multiguna_tempo a JOIN identitas i ON a.no_anggota = i.no_anggota 
            WHERE DATE(a.jatuh_tempo) = %s AND i.cabang = %s 
            UNION ALL 
            SELECT 'Dana Urgent' as jenis, a.no_anggota, a.nama_anggota, 1 as angsuran_ke, (a.tagihan_pokok + a.tagihan_margin) as total_tagihan, a.status, a.tgl_bayar 
            FROM angsuran_dana_urgent a JOIN identitas i ON a.no_anggota = i.no_anggota 
            WHERE DATE(a.tanggal_jatuh_tempo) = %s AND i.cabang = %s
        """, (tanggal, cabang, tanggal, cabang))
        angsuran = cursor.fetchall()

        cursor.execute("""
            SELECT c.account_name, j.keterangan, j.debit as kas_masuk, j.kredit as kas_keluar
            FROM jurnal_umum j
            JOIN coa c ON j.coa_id = c.id
            WHERE j.tanggal >= %s AND j.tanggal < DATE_ADD(%s, INTERVAL 1 DAY) AND j.cabang = %s AND (c.account_code LIKE '11%%' OR c.kategori = 'KAS')
        """, (tanggal, tanggal, cabang))
        cashflow = cursor.fetchall()

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
            WHERE DATE(a.jatuh_tempo) < %s AND i.cabang = %s
        """
        cursor.execute(query_macet, (tanggal, cabang))
        data_macet = cursor.fetchall()

        # --- KONVERSI DATA AGAR BISA DI-SERIALISASI OLEH JSONIFY ---
        for p in pencairan:
            p['nominal'] = float(p['nominal'] or 0)
            p['terima_bersih'] = float(p['terima_bersih'] or 0)
            
        for a in angsuran:
            a['total_tagihan'] = float(a['total_tagihan'] or 0)
            if hasattr(a['tgl_bayar'], 'isoformat') and a['tgl_bayar']:
                a['tgl_bayar'] = str(a['tgl_bayar'])
                
        for c in cashflow:
            c['kas_masuk'] = float(c['kas_masuk'] or 0)
            c['kas_keluar'] = float(c['kas_keluar'] or 0)

        target_date = datetime.strptime(tanggal, '%Y-%m-%d').date()
        macet_dict = {}
        for row in data_macet:
            jt = row['jatuh_tempo']
            if not jt: continue # Hindari error jika tanggal jatuh tempo kosong
            if isinstance(jt, str): jt = datetime.strptime(str(jt)[:10], '%Y-%m-%d').date()
            
            od_hari = (target_date - jt).days
            na = row['no_anggota']
            
            if na not in macet_dict:
                row['od_hari'] = od_hari
                row['jatuh_tempo'] = str(row['jatuh_tempo'])
                row['tagihan'] = float(row['tagihan'] or 0)
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

@api_laporan_bp.route('/api/update_penanganan_macet', methods=['POST'])
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

@api_laporan_bp.route('/api/laporan_tunggakan_urgent', methods=['GET'])
def get_laporan_tunggakan_urgent():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        today = datetime.now().date()
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        query = """
            SELECT a.id, a.no_anggota, i.nama_anggota, i.pt_instansi, i.no_telp, 
                   a.jenis_dana_urgent, a.tgl_pencairan, a.tanggal_jatuh_tempo, 
                   a.tgl_bayar, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda,
                   a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda
            FROM angsuran_dana_urgent a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE a.status = 'BELUM BAYAR' AND DATE(a.tanggal_jatuh_tempo) < %s
            AND i.cabang = %s
            ORDER BY a.tanggal_jatuh_tempo ASC
        """
        cursor.execute(query, (today, cabang))
        data = cursor.fetchall()
        
        total_tunggakan = 0
        total_denda = 0
        
        for row in data:
            jt = row['tanggal_jatuh_tempo']
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            
            last_pay = row.get('tgl_bayar')
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_sisa = max((today - base_date).days, 0)
            row['od_hari'] = max((today - jt).days, 0)
            
            sisa_p = float(row['tagihan_pokok'] or 0) - float(row['angsuran_pokok'] or 0)
            sisa_m = float(row['tagihan_margin'] or 0) - float(row['angsuran_margin'] or 0)
            
            if sisa_p <= 0.01 and sisa_m <= 0.01:
                d_kalk = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0)
            else:
                # Rumus denda khusus Urgent/Gaji/THR: (Pokok * Margin) * 0.007 * Hari
                add_denda = (sisa_p + sisa_m) * 0.007 * od_sisa
                d_kalk = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0) + add_denda
                
            row['tunggakan_denda'] = max(0, d_kalk) if denda_aktif else 0
            row['sisa_pokok'] = sisa_p
            row['sisa_margin'] = sisa_m
            row['tunggakan_pokok'] = sisa_p
            row['tunggakan_margin'] = sisa_m
            row['total_tagihan'] = sisa_p + sisa_m + row['tunggakan_denda']
            
            total_tunggakan += row['total_tagihan']
            total_denda += row['tunggakan_denda']
            
            if hasattr(row['tgl_pencairan'], 'isoformat') and row['tgl_pencairan']: row['tgl_pencairan'] = str(row['tgl_pencairan'])
            if hasattr(row['tanggal_jatuh_tempo'], 'isoformat') and row['tanggal_jatuh_tempo']: row['tanggal_jatuh_tempo'] = str(row['tanggal_jatuh_tempo'])
            if hasattr(row['tgl_bayar'], 'isoformat') and row['tgl_bayar']: row['tgl_bayar'] = str(row['tgl_bayar'])
            
        return jsonify({'status': 'success', 'data': data, 'summary': {
            'total_anggota': len(data),
            'total_denda': total_denda,
            'total_tunggakan': total_tunggakan
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_laporan_bp.route('/api/laporan_tunggakan_multiguna', methods=['GET'])
def get_laporan_tunggakan_multiguna():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        today = datetime.now().date()
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        query = """
            SELECT a.id, a.no_anggota, i.nama_anggota, i.pt_instansi, i.no_telp, 
                   a.jenis_pinjaman, a.tgl_pencairan, a.jatuh_tempo, 
                   a.tgl_bayar, a.angsuran_ke, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda,
                   a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda
            FROM angsuran_multiguna_tempo a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE a.status = 'BELUM BAYAR' AND DATE(a.jatuh_tempo) < %s
            AND i.cabang = %s
            ORDER BY a.jatuh_tempo ASC
        """
        cursor.execute(query, (today, cabang))
        data = cursor.fetchall()
        
        total_tunggakan = 0
        total_denda = 0
        unique_members = set()
        
        for row in data:
            unique_members.add(row['no_anggota'])
            jt = row['jatuh_tempo']
            if isinstance(jt, str): jt = datetime.strptime(jt[:10], '%Y-%m-%d').date()
            
            last_pay = row.get('tgl_bayar')
            if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(last_pay[:10], '%Y-%m-%d').date()
            
            base_date = jt
            if last_pay and last_pay > jt: base_date = last_pay
            
            od_sisa = max((today - base_date).days, 0)
            row['od_hari'] = max((today - jt).days, 0)
            
            sisa_p = float(row['tagihan_pokok'] or 0) - float(row['angsuran_pokok'] or 0)
            sisa_m = float(row['tagihan_margin'] or 0) - float(row['angsuran_margin'] or 0)
            
            if sisa_p <= 0.01 and sisa_m <= 0.01:
                d_kalk = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0)
            else:
                if row.get('jenis_pinjaman') == 'Tempo':
                    add_denda = (sisa_p + sisa_m) * 0.007 * od_sisa
                else:
                    add_denda = (sisa_p + sisa_m) * 0.005 * od_sisa
                d_kalk = float(row['tagihan_denda'] or 0) - float(row['angsuran_denda'] or 0) + add_denda
                
            row['tunggakan_denda'] = max(0, d_kalk) if denda_aktif else 0
            row['sisa_pokok'] = sisa_p
            row['sisa_margin'] = sisa_m
            row['tunggakan_pokok'] = sisa_p
            row['tunggakan_margin'] = sisa_m
            row['total_tagihan'] = sisa_p + sisa_m + row['tunggakan_denda']
            
            total_tunggakan += row['total_tagihan']
            total_denda += row['tunggakan_denda']
            
            if hasattr(row['tgl_pencairan'], 'isoformat') and row['tgl_pencairan']: row['tgl_pencairan'] = str(row['tgl_pencairan'])
            if hasattr(row['jatuh_tempo'], 'isoformat') and row['jatuh_tempo']: row['jatuh_tempo'] = str(row['jatuh_tempo'])
            if hasattr(row['tgl_bayar'], 'isoformat') and row['tgl_bayar']: row['tgl_bayar'] = str(row['tgl_bayar'])
            
        return jsonify({'status': 'success', 'data': data, 'summary': {
            'total_anggota': len(unique_members),
            'total_denda': total_denda,
            'total_tunggakan': total_tunggakan
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_laporan_bp.route('/api/audit_logs', methods=['GET'])
def get_audit_logs():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role', 'System')
    
    try:
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

@api_laporan_bp.route('/api/riwayat_pembayaran', methods=['GET'])
def get_riwayat_pembayaran():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    
    # Ambil parameter filter dari request
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    nama_anggota = request.args.get('nama_anggota')
    
    try:
        query = """
            SELECT 
                id, no_anggota, nama_anggota, jenis, angsuran_ke, tgl_bayar, kategori,
                angsuran_pokok, angsuran_margin, angsuran_denda, edc, simpanan_wajib_bayar
            FROM (
                SELECT 
                    a.id, a.no_anggota, a.nama_anggota, a.jenis_pinjaman as jenis, a.angsuran_ke, a.tgl_bayar, 'utama' as kategori,
                    a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.edc, a.simpanan_wajib_bayar
                FROM angsuran_multiguna_tempo a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.tgl_bayar IS NOT NULL AND i.cabang = %s
                
                UNION ALL
                
                SELECT 
                    a.id, a.no_anggota, a.nama_anggota, a.jenis_dana_urgent as jenis, 1 as angsuran_ke, a.tgl_bayar, 'urgent' as kategori,
                    a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.edc, a.simpanan_wajib_bayar
                FROM angsuran_dana_urgent a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.tgl_bayar IS NOT NULL AND i.cabang = %s
            ) as combined_payments
            WHERE 1=1
        """
        params = [cabang, cabang]

        if start_date:
            query += " AND DATE(tgl_bayar) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(tgl_bayar) <= %s"
            params.append(end_date)
        if nama_anggota:
            query += " AND (nama_anggota LIKE %s OR no_anggota LIKE %s)"
            params.append(f"%{nama_anggota}%")
            params.append(f"%{nama_anggota}%")

        query += " ORDER BY tgl_bayar DESC, id DESC"
        
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
        
        for row in data:
            if hasattr(row['tgl_bayar'], 'isoformat'): row['tgl_bayar'] = str(row['tgl_bayar'])
            pokok = float(row.get('angsuran_pokok') or 0); margin = float(row.get('angsuran_margin') or 0); denda = float(row.get('angsuran_denda') or 0); simpanan = float(row.get('simpanan_wajib_bayar') or 0)
            edc = float(row.get('edc') or 0)
            row['edc_val'] = edc # Tetap gunakan edc_val agar tidak merusak frontend
            row['total_bayar'] = pokok + margin + denda + edc + simpanan

        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_laporan_bp.route('/api/export_riwayat_pembayaran', methods=['GET'])
def export_riwayat_pembayaran():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    nama_anggota = request.args.get('nama_anggota')
    
    try:
        query = """
            SELECT 
                id, no_anggota, nama_anggota, jenis, angsuran_ke, tgl_bayar, kategori,
                angsuran_pokok, angsuran_margin, angsuran_denda, edc, simpanan_wajib_bayar
            FROM (
                SELECT 
                    a.id, a.no_anggota, a.nama_anggota, a.jenis_pinjaman as jenis, a.angsuran_ke, a.tgl_bayar, 'utama' as kategori,
                    a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.edc, a.simpanan_wajib_bayar
                FROM angsuran_multiguna_tempo a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.tgl_bayar IS NOT NULL AND i.cabang = %s
                
                UNION ALL
                
                SELECT 
                    a.id, a.no_anggota, a.nama_anggota, a.jenis_dana_urgent as jenis, 1 as angsuran_ke, a.tgl_bayar, 'urgent' as kategori,
                    a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.edc, a.simpanan_wajib_bayar
                FROM angsuran_dana_urgent a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.tgl_bayar IS NOT NULL AND i.cabang = %s
            ) as combined_payments
            WHERE 1=1
        """
        params = [cabang, cabang]

        if start_date:
            query += " AND DATE(tgl_bayar) >= %s"; params.append(start_date)
        if end_date:
            query += " AND DATE(tgl_bayar) <= %s"; params.append(end_date)
        if nama_anggota:
            query += " AND (nama_anggota LIKE %s OR no_anggota LIKE %s)"; params.extend([f"%{nama_anggota}%", f"%{nama_anggota}%"])

        query += " ORDER BY tgl_bayar DESC, id DESC"
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
        
        if not data: return "<h3>Tidak ada data untuk diekspor pada filter ini.</h3>", 404

        for row in data:
            row['edc_val'] = float(row.get('edc') or 0)

        df = pd.DataFrame(data)
        df_export = df[[
            'tgl_bayar', 'no_anggota', 'nama_anggota', 'jenis', 'angsuran_ke',
            'angsuran_pokok', 'angsuran_margin', 'angsuran_denda', 'edc_val',
            'simpanan_wajib_bayar'
        ]].copy()
        df_export['total_bayar'] = df_export[['angsuran_pokok', 'angsuran_margin', 'angsuran_denda', 'edc_val', 'simpanan_wajib_bayar']].sum(axis=1)

        df_export.rename(columns={
            'tgl_bayar': 'Tanggal Bayar', 'no_anggota': 'No. Anggota', 'nama_anggota': 'Nama Anggota',
            'jenis': 'Jenis Pinjaman', 'angsuran_ke': 'Angsuran Ke', 'angsuran_pokok': 'Pokok (Rp)',
            'angsuran_margin': 'Margin (Rp)', 'angsuran_denda': 'Denda (Rp)', 'edc_val': 'EDC (Rp)',
            'simpanan_wajib_bayar': 'Simpanan Wajib (Rp)', 'total_bayar': 'Total Bayar (Rp)'
        }, inplace=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Riwayat Pembayaran')
            worksheet = writer.sheets['Riwayat Pembayaran']
            for i, col in enumerate(df_export.columns):
                column_len = max(df_export[col].astype(str).map(len).max(), len(col))
                worksheet.set_column(i, i, column_len + 2)
        output.seek(0)
        
        filename = f"Riwayat_Pembayaran_{cabang}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)

    except Exception as e: return f"<h3>Terjadi kesalahan saat membuat file Excel:</h3><p>{str(e)}</p>", 500
    finally: cursor.close(); conn.close()

@api_laporan_bp.route('/api/export_laba_rugi_excel', methods=['GET'])
def export_laba_rugi_excel():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    try:
        # Build date filter
        date_filter = ""
        params = [cabang]
        periode_str = "Semua_Waktu"
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
            periode_str = f"{start_date}_sd_{end_date}"
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
            periode_str = f"Mulai_{start_date}"
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)
            periode_str = f"Hingga_{end_date}"

        params_beban = list(params)

        query_pendapatan = f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s {date_filter}
            WHERE c.kategori = 'PENDAPATAN' 
            GROUP BY c.id ORDER BY c.account_code ASC
        """
        cursor.execute(query_pendapatan, tuple(params))
        pendapatan = cursor.fetchall()
        
        query_beban = f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.debit - j.kredit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s {date_filter}
            WHERE c.kategori = 'BEBAN' 
            GROUP BY c.id ORDER BY c.account_code ASC
        """
        cursor.execute(query_beban, tuple(params_beban))
        beban = cursor.fetchall()
        
        total_pendapatan = sum(float(item['saldo']) for item in pendapatan)
        total_beban = sum(float(item['saldo']) for item in beban)
        laba_bersih = total_pendapatan - total_beban

        # Create DataFrame
        data_rows = []
        for p in pendapatan:
            data_rows.append({'Kategori': 'PENDAPATAN', 'Kode Akun': p['account_code'], 'Nama Akun': p['account_name'], 'Saldo': float(p['saldo'])})
        data_rows.append({'Kategori': 'PENDAPATAN', 'Kode Akun': '', 'Nama Akun': 'Total Pendapatan', 'Saldo': total_pendapatan})
        data_rows.append({'Kategori': '', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''}) # Spacer
        for b in beban:
            data_rows.append({'Kategori': 'BEBAN', 'Kode Akun': b['account_code'], 'Nama Akun': b['account_name'], 'Saldo': float(b['saldo'])})
        data_rows.append({'Kategori': 'BEBAN', 'Kode Akun': '', 'Nama Akun': 'Total Beban', 'Saldo': total_beban})
        data_rows.append({'Kategori': '', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''}) # Spacer
        data_rows.append({'Kategori': 'LABA BERSIH', 'Kode Akun': '', 'Nama Akun': 'Laba Bersih', 'Saldo': laba_bersih})

        df = pd.DataFrame(data_rows)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Laba Rugi')
            worksheet = writer.sheets['Laba Rugi']
            # Auto-adjust columns width
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).map(len).max(), len(col))
                worksheet.set_column(i, i, column_len + 2)
        output.seek(0)
        
        filename = f"Laba_Rugi_{cabang}_{periode_str}.xlsx"
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)

    except Exception as e:
        return f"<h3>Terjadi kesalahan saat membuat file Excel:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

@api_laporan_bp.route('/api/export_neraca_excel', methods=['GET'])
def export_neraca_excel():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        date_filter = " AND j.cabang = %s"
        params = [cabang]
        periode_str = "Semua_Waktu"
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
            periode_str = f"{start_date}_sd_{end_date}"
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
            periode_str = f"Mulai_{start_date}"
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)
            periode_str = f"Hingga_{end_date}"

        cursor.execute(f"SELECT c.account_code, c.account_name, IFNULL(SUM(j.debit - j.kredit), 0) as saldo FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter} WHERE c.kategori IN ('KAS', 'AKTIVA') GROUP BY c.id ORDER BY c.account_code ASC", tuple(params))
        aktiva = cursor.fetchall()
        
        cursor.execute(f"SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter} WHERE c.kategori = 'KEWAJIBAN' GROUP BY c.id ORDER BY c.account_code ASC", tuple(params))
        kewajiban = cursor.fetchall()

        cursor.execute(f"SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter} WHERE c.kategori = 'EKUITAS' GROUP BY c.id ORDER BY c.account_code ASC", tuple(params))
        ekuitas = cursor.fetchall()

        cursor.execute(f"SELECT IFNULL((SELECT SUM(j.kredit - j.debit) FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'PENDAPATAN' {date_filter}), 0) - IFNULL((SELECT SUM(j.debit - j.kredit) FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'BEBAN' {date_filter}), 0) AS laba_berjalan", tuple(params * 2))
        laba_berjalan = cursor.fetchone()['laba_berjalan'] or 0

        total_aktiva = sum(float(item['saldo']) for item in aktiva)
        total_kewajiban = sum(float(item['saldo']) for item in kewajiban)
        total_ekuitas = sum(float(item['saldo']) for item in ekuitas)
        total_pasiva = total_kewajiban + total_ekuitas + float(laba_berjalan)

        # Create DataFrame
        data_rows = []
        data_rows.append({'Grup': 'AKTIVA', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''})
        for a in aktiva:
            data_rows.append({'Grup': '', 'Kode Akun': a['account_code'], 'Nama Akun': a['account_name'], 'Saldo': float(a['saldo'])})
        data_rows.append({'Grup': 'AKTIVA', 'Kode Akun': '', 'Nama Akun': 'Total Aktiva', 'Saldo': total_aktiva})
        data_rows.append({'Grup': '', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''}) # Spacer

        data_rows.append({'Grup': 'PASIVA', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''})
        data_rows.append({'Grup': 'KEWAJIBAN', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''})
        for k in kewajiban:
            data_rows.append({'Grup': '', 'Kode Akun': k['account_code'], 'Nama Akun': k['account_name'], 'Saldo': float(k['saldo'])})
        data_rows.append({'Grup': 'KEWAJIBAN', 'Kode Akun': '', 'Nama Akun': 'Total Kewajiban', 'Saldo': total_kewajiban})
        data_rows.append({'Grup': '', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''}) # Spacer

        data_rows.append({'Grup': 'EKUITAS', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''})
        for e in ekuitas:
            data_rows.append({'Grup': '', 'Kode Akun': e['account_code'], 'Nama Akun': e['account_name'], 'Saldo': float(e['saldo'])})
        data_rows.append({'Grup': 'EKUITAS', 'Kode Akun': '', 'Nama Akun': 'Laba Berjalan', 'Saldo': float(laba_berjalan)})
        data_rows.append({'Grup': 'EKUITAS', 'Kode Akun': '', 'Nama Akun': 'Total Ekuitas + Laba', 'Saldo': total_ekuitas + float(laba_berjalan)})
        data_rows.append({'Grup': '', 'Kode Akun': '', 'Nama Akun': '', 'Saldo': ''}) # Spacer
        
        data_rows.append({'Grup': 'PASIVA', 'Kode Akun': '', 'Nama Akun': 'Total Pasiva', 'Saldo': total_pasiva})

        df = pd.DataFrame(data_rows)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Neraca')
            worksheet = writer.sheets['Neraca']
            # Auto-adjust columns width
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).map(len).max(), len(col))
                worksheet.set_column(i, i, column_len + 2)
        output.seek(0)
        
        filename = f"Neraca_{cabang}_{periode_str}.xlsx"
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)

    except Exception as e:
        return f"<h3>Terjadi kesalahan saat membuat file Excel:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()
@api_laporan_bp.route('/api/alldata', methods=['GET'])
def get_alldata_pivot():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    
    try:
        # Ambil Data Anggota & Simpanan
        query_id = "SELECT i.*, s.simpanan_pokok, s.simpanan_wajib FROM identitas i LEFT JOIN simpanan s ON i.no_anggota = s.nomor_anggota"
        params_id = []
        if role != 'Super Admin':
            query_id += " WHERE i.cabang = %s"
            params_id.append(cabang)
        cursor.execute(query_id, tuple(params_id))
        members = cursor.fetchall()
        member_dict = {m['no_anggota']: m for m in members}
        
        # Ambil Data Angsuran Multiguna & Tempo (Hanya Tagihan Terakhir per Pinjaman)
        cursor.execute("""
            SELECT a.id, a.no_anggota, a.jenis_pinjaman as kategori_pinjaman, a.jatuh_tempo, a.tgl_pencairan, a.status, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.tunggakan_pokok, a.tunggakan_margin, a.tunggakan_denda, a.od_hari, a.angsuran_ke, a.sisa_gaji,
            (SELECT SUM(tagihan_pokok - angsuran_pokok) FROM angsuran_multiguna_tempo WHERE no_anggota = a.no_anggota AND tgl_pencairan = a.tgl_pencairan AND status = 'BELUM BAYAR') as baki_debet
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY no_anggota, tgl_pencairan ORDER BY jatuh_tempo ASC) as rn
                FROM angsuran_multiguna_tempo
                WHERE status = 'BELUM BAYAR'
            ) a
            WHERE a.rn = 1
        """)
        amts = cursor.fetchall()

        # Ambil Data Angsuran Dana Urgent (Hanya Tagihan Terakhir per Pinjaman)
        cursor.execute("""
            SELECT a.id, a.no_anggota, a.jenis_dana_urgent as kategori_pinjaman, a.tanggal_jatuh_tempo as jatuh_tempo, a.tgl_pencairan, a.status, a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.tunggakan_pokok, a.tunggakan_margin, a.tunggakan_denda, a.od_hari, 1 as angsuran_ke, a.sisa_gaji,
            (SELECT SUM(tagihan_pokok - angsuran_pokok) FROM angsuran_dana_urgent WHERE no_anggota = a.no_anggota AND tgl_pencairan = a.tgl_pencairan AND status = 'BELUM BAYAR') as baki_debet
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY no_anggota, tgl_pencairan ORDER BY tanggal_jatuh_tempo ASC) as rn
                FROM angsuran_dana_urgent
                WHERE status = 'BELUM BAYAR'
            ) a
            WHERE a.rn = 1
        """)
        adus = cursor.fetchall()

        all_trans = amts + adus
        
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
            
            jt_date = None
            if t['status'] == 'BELUM BAYAR':
                jt_date = t['jatuh_tempo']
                if isinstance(jt_date, str):
                    try: jt_date = datetime.strptime(jt_date[:10], '%Y-%m-%d').date()
                    except: jt_date = None
                if jt_date:
                    od_hari = max((today - jt_date).days, 0)
                    if (sisa_p > 0.01 or sisa_m > 0.01) and denda_aktif:
                        if t['kategori_pinjaman'] in ['Tempo', 'Gaji', 'THR']: denda_berjalan += (sisa_p + sisa_m) * 0.007 * od_hari
                        else: denda_berjalan += (sisa_p + sisa_m) * 0.005 * od_hari

            denda_berjalan = max(0, denda_berjalan)

            for prefix in ['MG', 'TM', 'GJ', 'THR']:
                row[f'{prefix}_Status'] = None
                row[f'{prefix}_Angsuran_Ke'] = None
                row[f'{prefix}_Tagihan_Pokok'] = 0; row[f'{prefix}_Tagihan_Margin'] = 0; row[f'{prefix}_Denda_Berjalan'] = 0
                row[f'{prefix}_Angsuran_Pokok'] = 0; row[f'{prefix}_Angsuran_Margin'] = 0; row[f'{prefix}_Angsuran_Denda'] = 0
                row[f'{prefix}_Tunggakan_Pokok'] = 0; row[f'{prefix}_Tunggakan_Margin'] = 0
                row[f'{prefix}_Baki_Debet'] = 0
                row[f'{prefix}_Sisa_Gaji'] = 0

            kat = t['kategori_pinjaman']
            px = 'MG' if kat == 'Multiguna' else ('TM' if kat == 'Tempo' else ('GJ' if kat == 'Gaji' else ('THR' if kat == 'THR' else None)))

            if px:
                row[f'{px}_Status'] = t['status']
                row[f'{px}_Angsuran_Ke'] = t.get('angsuran_ke')
                row[f'{px}_Tagihan_Pokok'] = tag_p; row[f'{px}_Tagihan_Margin'] = tag_m; row[f'{px}_Denda_Berjalan'] = denda_berjalan
                row[f'{px}_Angsuran_Pokok'] = ang_p; row[f'{px}_Angsuran_Margin'] = ang_m; row[f'{px}_Angsuran_Denda'] = ang_d
                row[f'{px}_Baki_Debet'] = float(t.get('baki_debet') or 0)
                row[f'{px}_Sisa_Gaji'] = float(t.get('sisa_gaji') or 0)
                
                is_overdue = jt_date and (jt_date < today)
                if is_overdue:
                    row[f'{px}_Tunggakan_Pokok'] = sisa_p
                    row[f'{px}_Tunggakan_Margin'] = sisa_m
                else:
                    row[f'{px}_Tunggakan_Pokok'] = 0.0
                    row[f'{px}_Tunggakan_Margin'] = 0.0

            result.append(row)

        return jsonify({'status': 'success', 'data': result}), 200

    except Exception as e:
        import traceback
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500
    finally:
        cursor.close()
        conn.close()