from flask import Blueprint, request, jsonify, send_file, session
import mysql.connector
import os
from datetime import datetime
import json
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from db import get_db_connection
from api_helpers import generate_nomor_anggota_logic, hitung_denda_keterlambatan, extract_gmaps_coordinates

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

# === API: DAFTAR ANGGOTA LUNAS (SUDAH TIDAK PUNYA PINJAMAN AKTIF) ===
@api_anggota_bp.route('/api/anggota_lunas', methods=['GET'])
def get_anggota_lunas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    role = session.get('role')
    filter_cabang = request.args.get('cabang')
    try:
        # Anggota lunas = punya history pinjaman (pencairan) tapi tidak ada yang status = 'BELUM BAYAR'
        query = """
            SELECT DISTINCT i.no_anggota, i.nama_anggota, i.cabang, i.pt_instansi, i.no_telp
            FROM identitas i
            JOIN (
                SELECT no_anggota FROM pencairan_multiguna_tempo
                UNION
                SELECT no_anggota FROM pencairan_dana_urgent
            ) p ON i.no_anggota = p.no_anggota
            WHERE NOT EXISTS (
                SELECT 1 FROM angsuran_multiguna_tempo a WHERE a.no_anggota = i.no_anggota AND a.status = 'BELUM BAYAR'
            )
            AND NOT EXISTS (
                SELECT 1 FROM angsuran_dana_urgent u WHERE u.no_anggota = i.no_anggota AND u.status = 'BELUM BAYAR'
            )
        """
        params = []
        if role != 'Super Admin':
            query += " AND i.cabang = %s"; params.append(cabang)
        elif filter_cabang and filter_cabang != 'ALL':
            query += " AND i.cabang = %s"; params.append(filter_cabang)
            
        query += " ORDER BY i.nama_anggota ASC"
        
        cursor.execute(query, tuple(params))
        return jsonify({'status': 'success', 'data': cursor.fetchall()}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

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
        if request.method == 'GET':
            cabang = session.get('cabang', 'GAS')
            kol_status_filter = request.args.get('kol_status')

            query = """
                SELECT
                    i.no_anggota, i.nama_anggota, i.pt_instansi, i.no_telp, i.marketing, i.status_pernikahan, i.alamat_penanggung_jawab,
                    COUNT(a.no_anggota) AS kol_count
                FROM
                    identitas i
                LEFT JOIN (
                    SELECT no_anggota, jatuh_tempo FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR' AND jatuh_tempo < CURDATE()
                    UNION ALL
                    SELECT no_anggota, tanggal_jatuh_tempo as jatuh_tempo FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR' AND tanggal_jatuh_tempo < CURDATE()
                ) a ON i.no_anggota = a.no_anggota
                WHERE
                    i.cabang = %s
                GROUP BY
                    i.no_anggota, i.nama_anggota, i.pt_instansi, i.no_telp, i.marketing, i.status_pernikahan, i.alamat_penanggung_jawab
            """
            params = [cabang]

            # Menambahkan klausa HAVING secara dinamis untuk filter status
            if kol_status_filter and kol_status_filter != 'SEMUA':
                if kol_status_filter == 'LANCAR':
                    query += " HAVING kol_count = 0"
                elif kol_status_filter == 'Kurang Lancar':
                    query += " HAVING kol_count BETWEEN 1 AND 6"
                elif kol_status_filter == 'Macet':
                    query += " HAVING kol_count BETWEEN 7 AND 12"
                elif kol_status_filter == 'WO':
                    query += " HAVING kol_count > 12"
            
            query += " ORDER BY i.no_anggota DESC"

            cursor.execute(query, tuple(params))
            data = cursor.fetchall()

            # Proses data untuk menambahkan status 'kol' dan 'kol_class'
            for row in data:
                kol_count = int(row.pop('kol_count', 0) or 0) # Ambil dan hapus kol_count
                
                # 1. Atur kolom 'kol' menjadi "KOL X" atau "LANCAR"
                if kol_count == 0:
                    row['kol'] = "LANCAR"
                else:
                    row['kol'] = f"KOL {kol_count}"

                # 2. Atur kolom 'kriteria' dan kelas warnanya
                if kol_count == 0:
                    row['kriteria'] = "LANCAR"
                    row['kriteria_class'] = "success"
                elif 1 <= kol_count <= 6:
                    row['kriteria'] = "Kurang Lancar"
                    row['kriteria_class'] = "warning"
                elif 7 <= kol_count <= 12:
                    row['kriteria'] = "Macet"
                    row['kriteria_class'] = "danger"
                else:
                    row['kriteria'] = "WO"
                    row['kriteria_class'] = "dark"
            return jsonify({'status': 'success', 'data': data}), 200
            
        elif request.method == 'POST':
            cabang = session.get('cabang', 'GAS')
            data = request.form if request.form else request.json
            no_anggota_final = data.get('no_anggota')
            if not no_anggota_final or no_anggota_final == "":
                no_anggota_final = generate_nomor_anggota_logic(cursor, cabang)
                
            # --- START: Ekstraksi Koordinat Otomatis ---
            lat, lng = None, None
            gmaps_url = data.get('alamat_tagih') # Alamat tagih seringkali berisi URL Gmaps
            if gmaps_url and ('google.com/maps' in gmaps_url or 'goo.gl/maps' in gmaps_url):
                coord_result = extract_gmaps_coordinates(gmaps_url)
                if coord_result['status'] == 'success':
                    lat = coord_result['lat']
                    lng = coord_result['lng']
            # --- END: Ekstraksi Koordinat Otomatis ---
            
            status_pernikahan_val = data.get('status_pernikahan') or data.get('status_perkawinan') or data.get('status')
            alamat_pj_val = data.get('alamat_penanggung_jawab') or data.get('alamat_pj') or data.get('alamat_penanggungjawab')
            
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
                    bank_penanggung_jawab, marketing, berkas_pdf, cabang, berkas_jaminan,
                    status_pernikahan, alamat_penanggung_jawab
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
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
                data.get('marketing'), berkas_path, cabang, data.get('berkas_jaminan'),
                status_pernikahan_val, alamat_pj_val
            )
            cursor.execute(query, values)
            conn.commit()
            return jsonify({'status': 'success', 'message': f"Data berhasil disimpan! No Anggota: {no_anggota_final}"}), 201
            
        elif request.method == 'PUT':
            data = request.form if request.form else request.json
            no_anggota = data.get('no_anggota')
            if not no_anggota:
                return jsonify({'status': 'error', 'message': 'Nomor Anggota wajib disertakan!'}), 400
                
            is_approval = data.get('is_approval_execution')
            if isinstance(is_approval, str):
                is_approval = is_approval.lower() == 'true'
            else:
                is_approval = bool(is_approval)
                
            approval_id = data.get('approval_id')
            
            status_pernikahan_val = data.get('status_pernikahan') or data.get('status_perkawinan') or data.get('status')
            alamat_pj_val = data.get('alamat_penanggung_jawab') or data.get('alamat_pj') or data.get('alamat_penanggungjawab')
            
            # --- START: Ekstraksi Koordinat Otomatis ---
            lat, lng = None, None
            gmaps_url = data.get('alamat_tagih')
            if gmaps_url and ('google.com/maps' in gmaps_url or 'goo.gl/maps' in gmaps_url):
                coord_result = extract_gmaps_coordinates(gmaps_url)
                if coord_result['status'] == 'success':
                    lat = coord_result['lat']
                    lng = coord_result['lng']
            # --- END: Ekstraksi Koordinat Otomatis ---
            
            # --- START INTERCEPT APPROVAL ---
            if session.get('role') not in ['Manager', 'Super Admin'] and not is_approval:
                payload_dict = dict(data)
                
                # Simpan berkas sementara untuk dieksekusi nanti saat di-approve
                berkas_pdf = request.files.get('berkas_pdf')
                if berkas_pdf and berkas_pdf.filename != '':
                    if not berkas_pdf.filename.lower().endswith('.pdf'):
                        return jsonify({'status': 'error', 'message': 'Berkas harus berformat PDF!'}), 400
                    upload_folder = os.path.join(os.getcwd(), 'uploads', 'berkas_anggota')
                    if not os.path.exists(upload_folder): os.makedirs(upload_folder)
                    filename = secure_filename(f"{no_anggota}_{berkas_pdf.filename}")
                    berkas_path_temp = os.path.join('uploads', 'berkas_anggota', filename)
                    berkas_pdf.save(os.path.join(upload_folder, filename))
                    payload_dict['berkas_path_saved'] = berkas_path_temp
                
                if lat is not None and lng is not None:
                    payload_dict['lat'] = lat
                    payload_dict['lng'] = lng

                cursor.execute("INSERT INTO approval_queue (tipe_transaksi, data_payload, diajukan_oleh, cabang) VALUES (%s, %s, %s, %s)",
                               ('Edit Data Anggota', json.dumps(payload_dict), session.get('nama_lengkap', session.get('nama', 'Admin')), session.get('cabang') or 'GAS'))
                try:
                    conn.commit()
                    return jsonify({'status': 'success', 'message': 'Perubahan data diajukan! Menunggu Approval dari Manager.'}), 202
                except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
            # --- END INTERCEPT APPROVAL ---

            # Jika dieksekusi dari approval, ambil lat/lng dari payload
            if is_approval:
                lat = data.get('lat', lat)
                lng = data.get('lng', lng)

            berkas_path = data.get('berkas_path_saved')
            if not berkas_path:
                berkas_pdf = request.files.get('berkas_pdf')
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
                    bank_penanggung_jawab=%s, marketing=%s, berkas_jaminan=%s,
                    status_pernikahan=%s, alamat_penanggung_jawab=%s
            """
            values = [
                data.get('nama_anggota'), data.get('tgl_lahir') or None, data.get('no_telp'), data.get('nik_ktp'), data.get('nik_kk'),
                data.get('alamat_ktp'), data.get('alamat_tagih'), data.get('status_tempat_tinggal'), data.get('pt_instansi'), 
                data.get('status_karyawan'), data.get('awal_bekerja') or None, data.get('lama_kerja'), data.get('akhir_bekerja') or None, 
                data.get('jabatan'), data.get('no_jmo'), data.get('status_jmo'), data.get('email'), data.get('no_rek'), data.get('bank'),
                data.get('nama_penanggung_jawab'), data.get('no_telp_penanggung_jawab'), data.get('no_rek_penanggung_jawab'), 
                data.get('bank_penanggung_jawab'), data.get('marketing'), data.get('berkas_jaminan'),
                status_pernikahan_val, alamat_pj_val
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
            
            if is_approval and approval_id:
                cursor.execute("UPDATE approval_queue SET status = 'APPROVED' WHERE id = %s", (approval_id,))
                
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
        # 1. OPTIMASI: Menggabungkan query Identitas dan Simpanan dengan LEFT JOIN
        cursor.execute("""
            SELECT i.*, s.simpanan_pokok, s.simpanan_wajib, s.total_simpanan
            FROM identitas i
            LEFT JOIN simpanan s ON i.no_anggota = s.nomor_anggota
            WHERE i.no_anggota = %s
        """, (no_anggota,))
        identitas = cursor.fetchone()
        if not identitas:
            return jsonify({'status': 'error', 'message': 'Anggota tidak ditemukan.'}), 404

        for key, val in identitas.items():
            if hasattr(val, 'isoformat'): identitas[key] = str(val)
                
        # Alias fallback for frontend (Mencegah Modal Edit Kosong)
        identitas['status'] = identitas.get('status_pernikahan')
        identitas['alamat_pj'] = identitas.get('alamat_penanggung_jawab')
        
        # 2. Data simpanan sudah tergabung dalam query identitas
        simpanan = {
            'simpanan_pokok': identitas.get('simpanan_pokok') or 0,
            'simpanan_wajib': identitas.get('simpanan_wajib') or 0,
            'total_simpanan': identitas.get('total_simpanan') or 0
        }

        # 3. Lampiran Tagihan Multiguna / Tempo
        cursor.execute("""
            SELECT * FROM angsuran_multiguna_tempo WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_utama = cursor.fetchall()
        today = datetime.now().date()

        # Ambil status denda dari DB satu kali saja di luar loop untuk performa
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True

        for tag in tagihan_utama:

            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tgl_penggajian'), 'isoformat') and tag['tgl_penggajian']: tag['tgl_penggajian'] = str(tag['tgl_penggajian'])
            if hasattr(tag.get('jatuh_tempo'), 'isoformat') and tag['jatuh_tempo']: tag['jatuh_tempo'] = str(tag['jatuh_tempo'])
            
            # Reset default tunggakan ke 0
            tag['tunggakan_pokok'] = "0"
            tag['tunggakan_margin'] = "0"
            tag['tunggakan_denda'] = "0"

            jt_raw = tag.get('jatuh_tempo')
            status = tag.get('status')
            jt_date = datetime.strptime(jt_raw, '%Y-%m-%d').date() if isinstance(jt_raw, str) else jt_raw
            if jt_raw:
                try:
                    sisa_p = max(0.0, float(tag['tagihan_pokok'] or 0) - float(tag['angsuran_pokok'] or 0))
                    sisa_m = max(0.0, float(tag['tagihan_margin'] or 0) - float(tag['angsuran_margin'] or 0))

                    d_kalk = 0.0
                    if status not in ['LUNAS', 'LUNAS TOP-UP']:
                        d_kalk, _ = hitung_denda_keterlambatan(
                            jatuh_tempo=jt_raw, tgl_bayar=tag.get('tgl_bayar'), tagihan_pokok=tag.get('tagihan_pokok'),
                            tagihan_margin=tag.get('tagihan_margin'), angsuran_pokok=tag.get('angsuran_pokok'),
                            angsuran_margin=tag.get('angsuran_margin'), tagihan_denda_db=tag.get('tagihan_denda'),
                            angsuran_denda=tag.get('angsuran_denda'), denda_aktif=denda_aktif,
                            jenis_pinjaman=tag.get('jenis_pinjaman', 'Multiguna'), tgl_referensi=today
                        ) # Unpack tuple, ambil nilai denda saja
                    
                    if jt_date < today and (sisa_p > 0.01 or sisa_m > 0.01 or d_kalk > 0.01):
                        tag['tunggakan_pokok'] = sisa_p if sisa_p > 0.01 else "0"
                        tag['tunggakan_margin'] = sisa_m if sisa_m > 0.01 else "0"
                        tag['tunggakan_denda'] = d_kalk if d_kalk > 0.01 else "0"
                    else:
                        tag['tunggakan_pokok'] = "0"
                        tag['tunggakan_margin'] = "0"
                        tag['tunggakan_denda'] = "0"

                    tag['tagihan_denda'] = d_kalk + float(tag['angsuran_denda'] or 0)
                except ValueError: pass
        
        # 4. Lampiran Tagihan Dana Urgent
        cursor.execute("""
            SELECT * FROM angsuran_dana_urgent WHERE no_anggota = %s ORDER BY id ASC
        """, (no_anggota,))
        tagihan_urgent = cursor.fetchall()
        for tag in tagihan_urgent:

            if hasattr(tag.get('tgl_pencairan'), 'isoformat') and tag['tgl_pencairan']: tag['tgl_pencairan'] = str(tag['tgl_pencairan'])
            if hasattr(tag.get('tanggal_jatuh_tempo'), 'isoformat') and tag['tanggal_jatuh_tempo']: tag['tanggal_jatuh_tempo'] = str(tag['tanggal_jatuh_tempo'])
            
            # Reset default tunggakan ke 0
            tag['tunggakan_pokok'] = "0"
            tag['tunggakan_margin'] = "0"
            tag['tunggakan_denda'] = "0"

            jt_raw = tag.get('tanggal_jatuh_tempo')
            status = tag.get('status')
            jt_date = datetime.strptime(jt_raw, '%Y-%m-%d').date() if isinstance(jt_raw, str) else jt_raw
            if jt_raw:
                try:
                    sisa_p = max(0.0, float(tag['tagihan_pokok'] or 0) - float(tag['angsuran_pokok'] or 0))
                    sisa_m = max(0.0, float(tag['tagihan_margin'] or 0) - float(tag['angsuran_margin'] or 0))

                    d_kalk = 0.0
                    if status not in ['LUNAS', 'LUNAS TOP-UP']:
                        d_kalk, _ = hitung_denda_keterlambatan(
                            jatuh_tempo=jt_raw, tgl_bayar=tag.get('tgl_bayar'), tagihan_pokok=tag.get('tagihan_pokok'),
                            tagihan_margin=tag.get('tagihan_margin'), angsuran_pokok=tag.get('angsuran_pokok'),
                            angsuran_margin=tag.get('angsuran_margin'), tagihan_denda_db=tag.get('tagihan_denda'),
                            angsuran_denda=tag.get('angsuran_denda'), denda_aktif=denda_aktif,
                            jenis_pinjaman=tag.get('jenis_dana_urgent', 'urgent'), tgl_referensi=today
                        ) # Unpack tuple, ambil nilai denda saja
                    
                    if jt_date < today and (sisa_p > 0.01 or sisa_m > 0.01 or d_kalk > 0.01):
                        tag['tunggakan_pokok'] = sisa_p if sisa_p > 0.01 else "0"
                        tag['tunggakan_margin'] = sisa_m if sisa_m > 0.01 else "0"
                        tag['tunggakan_denda'] = d_kalk if d_kalk > 0.01 else "0"
                        
                    tag['tagihan_denda'] = d_kalk + float(tag['angsuran_denda'] or 0)
                except ValueError: pass

        # 5. OPTIMASI: Mengambil semua histori sekali, lalu filter di Python
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
            
        # 6. Filter histori simpanan dari data yang sudah diambil (menghindari query baru)
        simpanan_account_names = ['Simpanan Pokok', 'Simpanan Wajib']
        histori_simpanan = [h for h in histori_transaksi if h['account_name'] in simpanan_account_names]

        # --- Kalkulasi Ulang KOL & Kriteria untuk Detail View ---
        kol_count = 0
        for tag in tagihan_utama:
            if float(tag.get('tunggakan_pokok', 0)) > 0 or float(tag.get('tunggakan_margin', 0)) > 0:
                kol_count += 1
        for tag in tagihan_urgent:
            if float(tag.get('tunggakan_pokok', 0)) > 0 or float(tag.get('tunggakan_margin', 0)) > 0:
                kol_count += 1

        identitas['kol'] = f"KOL {kol_count}" if kol_count > 0 else "LANCAR"
        if kol_count == 0:
            identitas['kriteria'] = "LANCAR"
        elif 1 <= kol_count <= 6:
            identitas['kriteria'] = "Kurang Lancar"
        elif 7 <= kol_count <= 12:
            identitas['kriteria'] = "Macet"
        else:
            identitas['kriteria'] = "WO"

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

# === API: DASHBOARD KOLEKTIBILITAS ===
@api_anggota_bp.route('/api/dashboard/kolektibilitas', methods=['GET'])
def get_dashboard_kolektibilitas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        query = """
            SELECT
                SUM(CASE WHEN kol_count = 0 THEN 1 ELSE 0 END) as lancar,
                SUM(CASE WHEN kol_count BETWEEN 1 AND 6 THEN 1 ELSE 0 END) as kurang_lancar,
                SUM(CASE WHEN kol_count BETWEEN 7 AND 12 THEN 1 ELSE 0 END) as macet,
                SUM(CASE WHEN kol_count > 12 THEN 1 ELSE 0 END) as wo
            FROM (
                SELECT
                    i.no_anggota,
                    -- Menghitung jumlah angsuran yang telah jatuh tempo
                    COUNT(a.no_anggota) AS kol_count
                FROM
                    identitas i
                LEFT JOIN (
                    -- Subquery 'a' untuk mendapatkan semua angsuran yang telah jatuh tempo
                    SELECT no_anggota FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR' AND jatuh_tempo < CURDATE()
                    UNION ALL
                    SELECT no_anggota FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR' AND tanggal_jatuh_tempo < CURDATE()
                ) a ON i.no_anggota = a.no_anggota
                WHERE 
                    i.cabang = %s
                    -- PERBAIKAN: Hanya sertakan anggota yang memiliki pinjaman aktif (status 'BELUM BAYAR')
                    AND i.no_anggota IN (
                        SELECT no_anggota FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                        UNION
                        SELECT no_anggota FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
                    )
                GROUP BY i.no_anggota
            ) as subquery
        """
        cursor.execute(query, (cabang,))
        data = cursor.fetchone()
        if data:
            for key in data:
                if data[key] is None: data[key] = 0
        else: data = {'lancar': 0, 'kurang_lancar': 0, 'macet': 0, 'wo': 0}
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# === API: UPDATE STATUS JMO DARI MONITORING ===
@api_anggota_bp.route('/api/update_jmo', methods=['POST'])
def update_jmo():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        no_anggota = data.get('no_anggota')
        status_baru = data.get('status_jmo')

        if not no_anggota or not status_baru:
            return jsonify({'status': 'error', 'message': 'Data tidak lengkap (no_anggota atau status_jmo kosong).'}), 400

        # --- Get old status and member info for audit log ---
        cursor.execute("SELECT nama_anggota, status_jmo, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        member_info = cursor.fetchone()
        if not member_info:
            return jsonify({'status': 'error', 'message': 'Anggota tidak ditemukan.'}), 404
        
        status_lama = member_info.get('status_jmo')
        nama_anggota = member_info.get('nama_anggota')
        cabang_member = member_info.get('cabang') or session.get('cabang', 'GAS')

        # --- Update the status ---
        cursor.execute("UPDATE identitas SET status_jmo = %s WHERE no_anggota = %s", (status_baru, no_anggota))
        
        # --- AUDIT LOG ---
        detail_log = json.dumps({
            'no_anggota': no_anggota, 
            'nama_anggota': nama_anggota,
            'perubahan': f"Status JMO diubah dari '{status_lama}' menjadi '{status_baru}'"
        })
        user_aktif = session.get('nama_lengkap', session.get('username', 'System'))
        role_aktif = session.get('role', 'System')
        cursor.execute("INSERT INTO audit_logs (username, role, cabang, aksi, detail) VALUES (%s, %s, %s, %s, %s)", 
                       (user_aktif, role_aktif, cabang_member, 'UPDATE_STATUS_JMO', detail_log))

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Status JMO berhasil diperbarui.'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()