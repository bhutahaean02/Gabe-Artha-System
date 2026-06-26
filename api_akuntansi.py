from flask import Blueprint, request, jsonify, session
import json
from datetime import datetime

from db import get_db_connection
from api_helpers import parse_float

api_akuntansi_bp = Blueprint('api_akuntansi', __name__)

# === API: JURNAL & BUKU BESAR ===
@api_akuntansi_bp.route('/api/jurnal', methods=['GET'])
def get_jurnal():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    account_code = request.args.get('account_code')
    filter_type = request.args.get('filter_type') 
    filter_value = request.args.get('filter_value') 
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    filter_cabang = request.args.get('cabang')
    try:
        query = "SELECT j.tanggal, c.account_code, c.account_name, j.keterangan, j.debit, j.kredit, j.cabang FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE 1=1"
        params = []
        
        if role != 'Super Admin':
            query += " AND j.cabang = %s"; params.append(cabang)
        elif filter_cabang and filter_cabang != 'ALL':
            query += " AND j.cabang = %s"; params.append(filter_cabang)
            
        if account_code:
            query += " AND c.account_code = %s"; params.append(account_code)
        if filter_type and filter_value:
            if filter_type == 'harian': query += " AND DATE(j.tanggal) = %s"; params.append(filter_value)
            elif filter_type == 'bulanan': query += " AND DATE_FORMAT(j.tanggal, '%Y-%m') = %s"; params.append(filter_value)
            elif filter_type == 'tahunan': query += " AND YEAR(j.tanggal) = %s"; params.append(filter_value)
        else:
            if start_date and end_date: query += " AND DATE(j.tanggal) BETWEEN %s AND %s"; params.extend([start_date, end_date])
            elif start_date: query += " AND DATE(j.tanggal) >= %s"; params.append(start_date)
            elif end_date: query += " AND DATE(j.tanggal) <= %s"; params.append(end_date)
            
        query += " ORDER BY j.tanggal DESC, j.id DESC"
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
        for row in data:
            if hasattr(row['tanggal'], 'isoformat'): row['tanggal'] = str(row['tanggal'])
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: LAPORAN KEUANGAN INTI ===
@api_akuntansi_bp.route('/api/laba_rugi', methods=['GET'])
def get_laba_rugi():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')
    try:
        # Build date filter
        date_filter = ""
        params_pendapatan = [cabang]
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params_pendapatan.extend([start_date, end_date])
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params_pendapatan.append(start_date)
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params_pendapatan.append(end_date)
        
        # Copy params for the second query
        params_beban = list(params_pendapatan)

        query_pendapatan = f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s {date_filter}
            WHERE c.kategori = 'PENDAPATAN' 
            GROUP BY c.id
            ORDER BY c.account_code ASC
        """
        cursor.execute(query_pendapatan, tuple(params_pendapatan))
        pendapatan = cursor.fetchall()
        
        query_beban = f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.debit - j.kredit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s {date_filter}
            WHERE c.kategori = 'BEBAN' 
            GROUP BY c.id
            ORDER BY c.account_code ASC
        """
        cursor.execute(query_beban, tuple(params_beban))
        beban = cursor.fetchall()
        
        total_pendapatan = sum(item['saldo'] for item in pendapatan)
        total_beban = sum(item['saldo'] for item in beban)
        return jsonify({'status': 'success', 'data': {'pendapatan': pendapatan, 'beban': beban, 'total_pendapatan': float(total_pendapatan), 'total_beban': float(total_beban), 'laba_bersih': float(total_pendapatan - total_beban)}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_akuntansi_bp.route('/api/neraca', methods=['GET'])
def get_neraca():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')

    try:
        date_filter = " AND j.cabang = %s"
        params = [cabang]
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)

        # 1. AKTIVA (Harta) - Saldo Normal Debit (Debit - Kredit)
        cursor.execute(f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.debit - j.kredit), 0) as saldo 
            FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter}
            WHERE c.kategori IN ('KAS', 'AKTIVA') 
            GROUP BY c.id ORDER BY c.account_code ASC
        """, tuple(params))
        aktiva = cursor.fetchall()
        
        # 2. KEWAJIBAN (Hutang/Titipan) - Saldo Normal Kredit (Kredit - Debit)
        cursor.execute(f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo 
            FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter}
            WHERE c.kategori = 'KEWAJIBAN' 
            GROUP BY c.id ORDER BY c.account_code ASC
        """, tuple(params))
        kewajiban = cursor.fetchall()

        # 3. EKUITAS (Modal/Simpanan) - Saldo Normal Kredit (Kredit - Debit)
        cursor.execute(f"""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo 
            FROM coa c LEFT JOIN jurnal_umum j ON c.id = j.coa_id {date_filter}
            WHERE c.kategori = 'EKUITAS' 
            GROUP BY c.id ORDER BY c.account_code ASC
        """, tuple(params))
        ekuitas = cursor.fetchall()

        # 4. LABA/RUGI BERJALAN (Pendapatan - Beban)
        cursor.execute(f"""
            SELECT 
                IFNULL((SELECT SUM(j.kredit - j.debit) FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'PENDAPATAN' {date_filter}), 0) 
                - 
                IFNULL((SELECT SUM(j.debit - j.kredit) FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'BEBAN' {date_filter}), 0) 
            AS laba_berjalan
        """, tuple(params * 2))
        laba_berjalan = cursor.fetchone()['laba_berjalan'] or 0

        total_aktiva = sum(item['saldo'] for item in aktiva)
        total_kewajiban = sum(item['saldo'] for item in kewajiban)
        total_ekuitas = sum(item['saldo'] for item in ekuitas)
        total_pasiva = total_kewajiban + total_ekuitas + laba_berjalan

        return jsonify({'status': 'success', 'data': {
            'aktiva': aktiva, 'kewajiban': kewajiban, 'ekuitas': ekuitas, 
            'laba_berjalan': float(laba_berjalan), 
            'total_aktiva': float(total_aktiva),
            'total_kewajiban': float(total_kewajiban),
            'total_ekuitas': float(total_ekuitas),
            'total_pasiva': float(total_pasiva)
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/arus_kas', methods=['GET'])
def get_arus_kas():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        date_filter = ""
        params = []
        date_filter = " AND j.cabang = %s"
        params = [cabang]
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)

        saldo_awal = 0
        if start_date:
            cursor.execute("SELECT IFNULL(SUM(j.debit - j.kredit), 0) as saldo_awal FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'KAS' AND j.cabang = %s AND DATE(j.tanggal) < %s", (cabang, start_date))
            saldo_awal = cursor.fetchone()['saldo_awal']

        query = f"""
            SELECT j.tanggal, c.account_name, j.keterangan, j.debit as masuk, j.kredit as keluar
            FROM jurnal_umum j
            JOIN coa c ON j.coa_id = c.id
            WHERE c.kategori = 'KAS' {date_filter}
            ORDER BY j.tanggal ASC, j.id ASC
        """
        cursor.execute(query, tuple(params))
        mutasi = cursor.fetchall()
        for row in mutasi:
            if hasattr(row['tanggal'], 'isoformat'): row['tanggal'] = str(row['tanggal'])

        return jsonify({'status': 'success', 'data': {'saldo_awal': float(saldo_awal), 'mutasi': mutasi}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: PENGELUARAN, ASET, ANGGARAN ===
@api_akuntansi_bp.route('/api/realisasi_anggaran', methods=['GET'])
def get_realisasi_anggaran():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    bulan = request.args.get('bulan', datetime.now().strftime('%Y-%m'))
    cabang = session.get('cabang', 'GAS')
    try:
        query = """
            SELECT c.id, c.account_code, c.account_name, c.anggaran_bulanan,
                   IFNULL(SUM(j.debit - j.kredit), 0) as realisasi
            FROM coa c
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND DATE_FORMAT(j.tanggal, '%Y-%m') = %s AND j.cabang = %s
            WHERE c.kategori = 'BEBAN'
            GROUP BY c.id
            ORDER BY c.account_code ASC
        """
        cursor.execute(query, (bulan, cabang))
        return jsonify({'status': 'success', 'data': cursor.fetchall(), 'bulan': bulan}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/update_anggaran', methods=['POST'])
def update_anggaran():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for item in data.get('anggaran_list', []):
            cursor.execute("UPDATE coa SET anggaran_bulanan = %s WHERE id = %s", (item['anggaran_bulanan'], item['id']))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Batas Anggaran Bulanan berhasil diperbarui!'}), 200
    except Exception as e:
        if conn: conn.rollback(); return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/coa/dropdown', methods=['GET'])
def get_coa_dropdown():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, account_code, account_name FROM coa WHERE kategori = 'KAS' ORDER BY account_code ASC")
        kas = cursor.fetchall()
        cursor.execute("SELECT id, account_code, account_name FROM coa WHERE kategori = 'BEBAN' ORDER BY account_code ASC")
        beban = cursor.fetchall()
        return jsonify({'status': 'success', 'data': {'kas': kas, 'beban': beban}}), 200
    finally: cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/coa_all', methods=['GET'])
def get_all_coa():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT account_code, account_name FROM coa ORDER BY account_code ASC")
        return jsonify({'status': 'success', 'data': cursor.fetchall()})
    finally:
        cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/expenses', methods=['POST'])
def add_expense():
    data = request.json
    try:
        data['nominal'] = parse_float(data.get('nominal'), 'Nominal')
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': str(ve)}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        tanggal = data.get('tanggal')
        sumber_dana = data.get('coa_sumber_dana_id')
        beban_id = data.get('coa_beban_id')
        nominal = data.get('nominal')
        keterangan = data.get('keterangan', '')

        # --- PERBAIKAN LOGIKA CABANG ---
        # Secara default, transaksi dicatat di cabang tempat user yang login.
        cabang = session.get('cabang', 'GAS')

        # Namun, jika user adalah 'Super Admin', izinkan dia memilih cabang dari frontend.
        # Ini penting agar Super Admin bisa mencatat pengeluaran atas nama cabang lain.
        if session.get('role') == 'Super Admin' and data.get('cabang'):
            cabang = data.get('cabang')
            
        cursor.execute("INSERT INTO pengeluaran_operasional (tanggal, coa_sumber_dana_id, coa_beban_id, nominal, keterangan, cabang) VALUES (%s, %s, %s, %s, %s, %s)", (tanggal, sumber_dana, beban_id, nominal, keterangan, cabang))
        
        query_jurnal = "INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(query_jurnal, (tanggal, beban_id, f"Beban Operasional: {keterangan}", nominal, 0, cabang))
        cursor.execute(query_jurnal, (tanggal, sumber_dana, f"Kas Keluar Operasional: {keterangan}", 0, nominal, cabang))

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pengeluaran operasional berhasil dicatat!'}), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_akuntansi_bp.route('/api/aset', methods=['GET', 'POST', 'PUT'])
def kelola_aset():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        if request.method == 'GET':
            cursor.execute("SELECT * FROM aset_operasional WHERE lokasi_cabang = %s ORDER BY id DESC", (cabang,))
            data = cursor.fetchall()
            for d in data:
                if hasattr(d.get('tanggal_perolehan'), 'isoformat'): d['tanggal_perolehan'] = str(d['tanggal_perolehan'])
            return jsonify({'status': 'success', 'data': data}), 200
        elif request.method == 'POST':
            data = request.json

            # --- PERBAIKAN LOGIKA CABANG (UNTUK ASET) ---
            # Default ke cabang user yang login.
            lokasi_cabang = cabang
            # Jika user adalah Super Admin, izinkan dia memilih cabang dari frontend.
            if session.get('role') == 'Super Admin' and data.get('lokasi_cabang'):
                lokasi_cabang = data.get('lokasi_cabang')

            cursor.execute("INSERT INTO aset_operasional (nama_aset, lokasi_cabang, tanggal_perolehan, nilai_aset, kondisi, keterangan) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (data.get('nama_aset'), lokasi_cabang, data.get('tanggal_perolehan'), parse_float(data.get('nilai_aset'), 'Nilai'), data.get('kondisi'), data.get('keterangan', '')))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Data inventaris aset berhasil dicatat!'}), 201
        elif request.method == 'PUT':
            data = request.json
            cursor.execute("UPDATE aset_operasional SET kondisi = %s, keterangan = %s WHERE id = %s", (data.get('kondisi'), data.get('keterangan', ''), data.get('id')))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Kondisi aset berhasil diperbarui!'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()