from flask import Blueprint, request, jsonify, send_file, session
import mysql.connector
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from db import get_db_connection
from api_helpers import generate_nomor_anggota_logic

api_anggota_bp = Blueprint('api_anggota', __name__)

# === API: MENGAMBIL DAFTAR ANGGOTA UNTUK DROPDOWN ===
@api_anggota_bp.route('/api/anggota_list', methods=['GET'])
def get_anggota_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    filter_cabang = request.args.get('cabang')
    try:
        query = "SELECT no_anggota, nama_anggota, cabang FROM identitas WHERE 1=1"
        params = []
        if role != 'Super Admin':
            query += " AND cabang = %s"; params.append(cabang)
        elif filter_cabang and filter_cabang != 'ALL':
            query += " AND cabang = %s"; params.append(filter_cabang)
            
        query += " ORDER BY nama_anggota ASC"
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: GENERATE NOMOR ANGGOTA OTOMATIS ===
@api_anggota_bp.route('/api/generate_no_anggota', methods=['GET'])
def generate_no_anggota():
    cabang = session.get('cabang', 'GAS')
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

# === API: IDENTITAS (READ, CREATE, UPDATE) ===
@api_anggota_bp.route('/api/identitas', methods=['GET', 'POST', 'PUT'])
def api_identitas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Auto-Migrate Kolom PDF ke Tabel jika belum ada
        try:
            cursor.execute("SELECT berkas_pdf FROM identitas LIMIT 1")
            cursor.fetchall()
        except:
            cursor.execute("ALTER TABLE identitas ADD COLUMN berkas_pdf VARCHAR(255)")
            
        try:
            cursor.execute("SELECT marketing FROM identitas LIMIT 1")
            cursor.fetchall()
        except:
            cursor.execute("ALTER TABLE identitas ADD COLUMN marketing VARCHAR(100)")
            
        if request.method == 'GET':
            cabang = session.get('cabang', 'GAS')
            cursor.execute("SELECT no_anggota, nama_anggota, pt_instansi, no_telp, kol, marketing FROM identitas WHERE cabang = %s ORDER BY no_anggota DESC", (cabang,))
            data = cursor.fetchall()
            return jsonify({'status': 'success', 'data': data}), 200
            
        elif request.method == 'POST':
            cabang = session.get('cabang', 'GAS')
            data = request.form if request.form else request.json
            no_anggota_final = data.get('no_anggota')
            if not no_anggota_final or no_anggota_final == "":
                no_anggota_final = generate_nomor_anggota_logic(cursor, cabang)
                
            # Menangani File PDF Upload
            berkas_pdf = request.files.get('berkas_pdf')
            berkas_path = None
            if berkas_pdf and berkas_pdf.filename != '':
                if not berkas_pdf.filename.lower().endswith('.pdf'):
                    return jsonify({'status': 'error', 'message': 'Berkas harus berformat PDF!'}), 400
                
                # Buat folder jika belum ada
                upload_folder = os.path.join(os.getcwd(), 'uploads', 'berkas_anggota')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                
                filename = secure_filename(f"{no_anggota_final}_{berkas_pdf.filename}")
                berkas_path = os.path.join('uploads', 'berkas_anggota', filename)
                berkas_pdf.save(os.path.join(upload_folder, filename))
                
            # Hash Password Jika Ada
            password_plain = data.get('password')
            password_hashed = generate_password_hash(password_plain) if password_plain else None
                
            query = """
                INSERT INTO identitas (
                    no_anggota, nama_anggota, tgl_lahir, no_telp, nik_ktp, nik_kk, 
                    alamat_ktp, alamat_tagih, status_tempat_tinggal, pt_instansi, 
                    status_karyawan, awal_bekerja, lama_kerja, akhir_bekerja, jabatan, 
                    no_jmo, status_jmo, email, password, no_rek, bank, 
                    nama_penanggung_jawab, no_telp_penanggung_jawab, no_rek_penanggung_jawab, 
                    bank_penanggung_jawab, kol, kriteria, marketing, berkas_pdf, cabang
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                data.get('kol'), data.get('kriteria'), data.get('marketing'), berkas_path, cabang
            )
            cursor.execute(query, values)
            conn.commit()
            return jsonify({'status': 'success', 'message': f"Data berhasil disimpan! No Anggota: {no_anggota_final}"}), 201
            
        elif request.method == 'PUT':
            data = request.form if request.form else request.json
            no_anggota = data.get('no_anggota')
            if not no_anggota:
                return jsonify({'status': 'error', 'message': 'Nomor Anggota wajib disertakan!'}), 400
                
            berkas_pdf = request.files.get('berkas_pdf')
            berkas_path = None
            if berkas_pdf and berkas_pdf.filename != '':
                if not berkas_pdf.filename.lower().endswith('.pdf'):
                    return jsonify({'status': 'error', 'message': 'Berkas harus berformat PDF!'}), 400
                upload_folder = os.path.join(os.getcwd(), 'uploads', 'berkas_anggota')
                if not os.path.exists(upload_folder): os.makedirs(upload_folder)
                filename = secure_filename(f"{no_anggota}_{berkas_pdf.filename}")
                berkas_path = os.path.join('uploads', 'berkas_anggota', filename)
                berkas_pdf.save(os.path.join(upload_folder, filename))
                
            query = """
                UPDATE identitas SET 
                    nama_anggota=%s, tgl_lahir=%s, no_telp=%s, nik_ktp=%s, nik_kk=%s, 
                    alamat_ktp=%s, alamat_tagih=%s, status_tempat_tinggal=%s, pt_instansi=%s, 
                    status_karyawan=%s, awal_bekerja=%s, lama_kerja=%s, akhir_bekerja=%s, jabatan=%s, 
                    no_jmo=%s, status_jmo=%s, email=%s, no_rek=%s, bank=%s, 
                    nama_penanggung_jawab=%s, no_telp_penanggung_jawab=%s, no_rek_penanggung_jawab=%s, 
                    bank_penanggung_jawab=%s, kol=%s, kriteria=%s, marketing=%s
            """
            values = [
                data.get('nama_anggota'), data.get('tgl_lahir') or None, data.get('no_telp'), data.get('nik_ktp'), data.get('nik_kk'),
                data.get('alamat_ktp'), data.get('alamat_tagih'), data.get('status_tempat_tinggal'), data.get('pt_instansi'), 
                data.get('status_karyawan'), data.get('awal_bekerja') or None, data.get('lama_kerja'), data.get('akhir_bekerja') or None, 
                data.get('jabatan'), data.get('no_jmo'), data.get('status_jmo'), data.get('email'), data.get('no_rek'), data.get('bank'),
                data.get('nama_penanggung_jawab'), data.get('no_telp_penanggung_jawab'), data.get('no_rek_penanggung_jawab'), 
                data.get('bank_penanggung_jawab'), data.get('kol'), data.get('kriteria'), data.get('marketing')
            ]
            
            password_plain = data.get('password')
            if password_plain:
                query += ", password=%s"
                values.append(generate_password_hash(password_plain))
            if berkas_path:
                query += ", berkas_pdf=%s"
                values.append(berkas_path)
                
            query += " WHERE no_anggota=%s"
            values.append(no_anggota)
            cursor.execute(query, tuple(values))
            conn.commit()
            return jsonify({'status': 'success', 'message': "Data identitas berhasil diperbarui!"}), 200
    except mysql.connector.Error as err:
        return jsonify({'status': 'error', 'message': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: DOWNLOAD BERKAS ANGGOTA ===
@api_anggota_bp.route('/api/download_berkas/<no_anggota>', methods=['GET'])
def download_berkas(no_anggota):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT berkas_pdf FROM identitas WHERE no_anggota = %s", (no_anggota,))
        row = cursor.fetchone()
        if row and row.get('berkas_pdf'):
            filepath = os.path.join(os.getcwd(), row['berkas_pdf'])
            if os.path.exists(filepath):
                return send_file(filepath, as_attachment=False, mimetype='application/pdf')
        return jsonify({'status': 'error', 'message': 'Berkas PDF tidak ditemukan atau belum dilampirkan.'}), 404
    finally:
        cursor.close(); conn.close()

# === API: MENGAMBIL DETAIL ANGGOTA YANG SEDANG LOGIN ===
@api_anggota_bp.route('/api/anggota/me/detail', methods=['GET'])
def get_my_detail():
    no_anggota = session.get('user_id')
    if not no_anggota or session.get('role') != 'Anggota':
        return jsonify({'status': 'error', 'message': 'Akses ditolak. Anda belum login sebagai anggota.'}), 401
    return get_anggota_detail(no_anggota)

# === API: MENGAMBIL DETAIL ANGGOTA LENGKAP ===
@api_anggota_bp.route('/api/anggota/<no_anggota>/detail', methods=['GET'])
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
        
        # Jika anggota belum punya buku simpanan, berikan nilai 0 agar Dashboard tidak error (Crash)
        if not simpanan:
            simpanan = {'simpanan_pokok': 0, 'simpanan_wajib': 0, 'total_simpanan': 0}

        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        # 3. Lampiran Tagihan Multiguna / Tempo
        cursor.execute("""
            SELECT * FROM angsuran_multiguna_tempo WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_utama = cursor.fetchall()
        today = datetime.now().date()
        for tag in tagihan_utama:
            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tgl_penggajian'), 'isoformat') and tag['tgl_penggajian']: tag['tgl_penggajian'] = str(tag['tgl_penggajian'])
            if hasattr(tag.get('jatuh_tempo'), 'isoformat') and tag['jatuh_tempo']: tag['jatuh_tempo'] = str(tag['jatuh_tempo'])
            
            # Kalkulasi Denda Tunggakan Real-time
            if tag['status'] == 'BELUM BAYAR' and tag.get('jatuh_tempo'):
                try:
                    jt_date = datetime.strptime(str(tag['jatuh_tempo'])[:10], '%Y-%m-%d').date()
                    last_pay = tag.get('tgl_bayar')
                    if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(str(last_pay)[:10], '%Y-%m-%d').date()
                    
                    base_date = jt_date
                    if last_pay and last_pay > jt_date: base_date = last_pay
                    
                    od_sisa = max((today - base_date).days, 0)
                    
                    sisa_p = float(tag['tagihan_pokok'] or 0) - float(tag['angsuran_pokok'] or 0)
                    sisa_m = float(tag['tagihan_margin'] or 0) - float(tag['angsuran_margin'] or 0)
                    if sisa_p <= 0.01 and sisa_m <= 0.01:
                        d_kalk = float(tag.get('tagihan_denda') or 0) - float(tag['angsuran_denda'] or 0)
                    else:
                        if tag.get('jenis_pinjaman') == 'Tempo':
                            add_denda = (sisa_p * sisa_m) * 0.007 * od_sisa
                        else:
                            add_denda = (sisa_p + sisa_m) * 0.005 * od_sisa
                        d_kalk = float(tag.get('tagihan_denda') or 0) - float(tag['angsuran_denda'] or 0) + add_denda
                    tag['tunggakan_denda'] = max(0, d_kalk) if denda_aktif else 0
                except ValueError: pass
        
        # 4. Lampiran Tagihan Dana Urgent
        cursor.execute("""
            SELECT * FROM angsuran_dana_urgent WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_urgent = cursor.fetchall()
        for tag in tagihan_urgent:
            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tanggal_jatuh_tempo'), 'isoformat') and tag['tanggal_jatuh_tempo']: tag['tanggal_jatuh_tempo'] = str(tag['tanggal_jatuh_tempo'])
            
            # Kalkulasi Denda Tunggakan Real-time
            if tag['status'] == 'BELUM BAYAR' and tag.get('tanggal_jatuh_tempo'):
                try:
                    jt_date = datetime.strptime(str(tag['tanggal_jatuh_tempo'])[:10], '%Y-%m-%d').date()
                    last_pay = tag.get('tgl_bayar')
                    if isinstance(last_pay, str) and last_pay: last_pay = datetime.strptime(str(last_pay)[:10], '%Y-%m-%d').date()
                    
                    base_date = jt_date
                    if last_pay and last_pay > jt_date: base_date = last_pay
                    
                    od_sisa = max((today - base_date).days, 0)
                    
                    sisa_p = float(tag['tagihan_pokok'] or 0) - float(tag['angsuran_pokok'] or 0)
                    sisa_m = float(tag['tagihan_margin'] or 0) - float(tag['angsuran_margin'] or 0)
                    if sisa_p <= 0.01 and sisa_m <= 0.01:
                        d_kalk = float(tag.get('tagihan_denda') or 0) - float(tag['angsuran_denda'] or 0)
                    else:
                        add_denda = (sisa_p * sisa_m) * 0.007 * od_sisa
                        d_kalk = float(tag.get('tagihan_denda') or 0) - float(tag['angsuran_denda'] or 0) + add_denda
                    tag['tunggakan_denda'] = max(0, d_kalk) if denda_aktif else 0
                except ValueError: pass

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
@api_anggota_bp.route('/api/update_jmo', methods=['POST'])
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