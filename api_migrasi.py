from flask import Blueprint, request, jsonify, session
from db import get_db_connection
from api_helpers import generate_nomor_anggota_logic, tambah_bulan
from werkzeug.security import generate_password_hash
import pandas as pd
import io
from datetime import datetime

api_migrasi_bp = Blueprint('api_migrasi', __name__)

def catat_jurnal_migrasi(cursor, tanggal, account_code, keterangan, debit, kredit, cabang):
    if debit == 0 and kredit == 0: return
    cursor.execute("SELECT id FROM coa WHERE account_code = %s", (account_code,))
    coa = cursor.fetchone()
    if coa:
        coa_id = coa['id']
        cursor.execute("""
            INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (tanggal, coa_id, keterangan, debit, kredit, cabang))

@api_migrasi_bp.route('/api/import_migrasi_excel', methods=['POST'])
def import_migrasi_excel():
    if 'file_identitas' not in request.files:
        return jsonify({'status': 'error', 'message': 'File Template 1 (Identitas) wajib di-upload.'}), 400

    file_identitas = request.files['file_identitas']
    file_multiguna = request.files.get('file_multiguna')
    file_urgent = request.files.get('file_urgent')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        df_identitas = pd.read_csv(io.StringIO(file_identitas.stream.read().decode("UTF8")), sep=',')
        df_multiguna = pd.read_csv(io.StringIO(file_multiguna.stream.read().decode("UTF8")), sep=',') if file_multiguna else pd.DataFrame()
        df_urgent = pd.read_csv(io.StringIO(file_urgent.stream.read().decode("UTF8")), sep=',') if file_urgent else pd.DataFrame()

        df_identitas = df_identitas.where(pd.notnull(df_identitas), None)
        if not df_multiguna.empty: df_multiguna = df_multiguna.where(pd.notnull(df_multiguna), None)
        if not df_urgent.empty: df_urgent = df_urgent.where(pd.notnull(df_urgent), None)

        conn.start_transaction()
        
        ref_to_new_id_map = {}
        processed_members_count = 0
        migration_date = datetime.now().date()

        # TAHAP 1: PROSES IDENTITAS & SIMPANAN
        for _, row in df_identitas.iterrows():
            no_ref = str(row['no_referensi_excel'])
            nama_anggota = row['nama_anggota']
            cabang = row['cabang']
            
            new_no_anggota = generate_nomor_anggota_logic(cursor, cabang)
            ref_to_new_id_map[no_ref] = new_no_anggota
            processed_members_count += 1

            # Hapus data lama untuk idempotensi
            cursor.execute("DELETE FROM identitas WHERE nama_anggota = %s AND cabang = %s", (nama_anggota, cabang))
            cursor.execute("DELETE FROM simpanan WHERE nomor_anggota = %s", (new_no_anggota,))
            cursor.execute("DELETE FROM angsuran_multiguna_tempo WHERE no_anggota = %s", (new_no_anggota,))
            cursor.execute("DELETE FROM angsuran_dana_urgent WHERE no_anggota = %s", (new_no_anggota,))
            cursor.execute("DELETE FROM pencairan_multiguna_tempo WHERE no_anggota = %s", (new_no_anggota,))
            cursor.execute("DELETE FROM pencairan_dana_urgent WHERE no_anggota = %s", (new_no_anggota,))
            
            password_hashed = generate_password_hash(str(row['password'])) if row.get('password') else None
            
            status_pernikahan_val = row.get('status_pernikahan') or row.get('status')
            alamat_pj_val = row.get('alamat_penanggung_jawab') or row.get('alamat_pj')

            query_identitas = """INSERT INTO identitas (no_anggota, nama_anggota, cabang, tgl_lahir, no_telp, nik_ktp, nik_kk, alamat_ktp, alamat_tagih, status_tempat_tinggal, email, password, pt_instansi, status_karyawan, jabatan, awal_bekerja, lama_kerja, akhir_bekerja, no_jmo, status_jmo, bank, no_rek, nama_penanggung_jawab, no_telp_penanggung_jawab, bank_penanggung_jawab, no_rek_penanggung_jawab, kol, kriteria, marketing, status_pernikahan, alamat_penanggung_jawab) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            values_identitas = (new_no_anggota, nama_anggota, cabang, row.get('tgl_lahir'), row.get('no_telp'), row.get('nik_ktp'), row.get('nik_kk'), row.get('alamat_ktp'), row.get('alamat_tagih'), row.get('status_tempat_tinggal'), row.get('email'), password_hashed, row.get('pt_instansi'), row.get('status_karyawan'), row.get('jabatan'), row.get('awal_bekerja'), row.get('lama_kerja'), row.get('akhir_bekerja'), row.get('no_jmo'), row.get('status_jmo'), row.get('bank'), row.get('no_rek'), row.get('nama_penanggung_jawab'), row.get('no_telp_penanggung_jawab'), row.get('bank_penanggung_jawab'), row.get('no_rek_penanggung_jawab'), row.get('kol'), row.get('kriteria'), row.get('marketing'), status_pernikahan_val, alamat_pj_val)
            cursor.execute(query_identitas, values_identitas)

            sim_pokok = float(row.get('simpanan_pokok') or 0)
            sim_wajib = float(row.get('simpanan_wajib') or 0)
            if sim_pokok > 0 or sim_wajib > 0:
                cursor.execute("INSERT INTO simpanan (nomor_anggota, nama_anggota, simpanan_pokok, simpanan_wajib, total_simpanan) VALUES (%s, %s, %s, %s, %s)", (new_no_anggota, nama_anggota, sim_pokok, sim_wajib, sim_pokok + sim_wajib))
                catat_jurnal_migrasi(cursor, migration_date, '1101', f"Kas Masuk Migrasi Simpanan - {nama_anggota}", sim_pokok + sim_wajib, 0, cabang)
                if sim_pokok > 0: catat_jurnal_migrasi(cursor, migration_date, '3101', f"Migrasi Simpanan Pokok - {nama_anggota}", 0, sim_pokok, cabang)
                if sim_wajib > 0: catat_jurnal_migrasi(cursor, migration_date, '3102', f"Migrasi Simpanan Wajib - {nama_anggota}", 0, sim_wajib, cabang)

        # TAHAP 2: PROSES PINJAMAN MULTIGUNA
        if not df_multiguna.empty:
            for _, row in df_multiguna.iterrows():
                no_ref = str(row['no_referensi_excel'])
                if no_ref not in ref_to_new_id_map: continue
                
                no_anggota = ref_to_new_id_map[no_ref]
                nama_anggota = row['nama_anggota']
                jenis_pinjaman = row['jenis_pinjaman']
                tgl_cair_awal = row['tgl_pencairan_awal']
                besar_pinjaman = float(row['besar_pinjaman_awal'])
                tenor = int(row['tenor_bulan'])
                bunga_persen = float(row['bunga_persen_perbulan'])
                jml_lunas = int(row.get('jml_angsuran_lunas') or 0)
                tgl_jatuh_tempo_berikutnya = row['tgl_jatuh_tempo_berikutnya']
                pokok_perbulan = float(row['angsuran_pokok_perbulan'])
                margin_perbulan = float(row['angsuran_margin_perbulan'])

                cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
                cabang = cursor.fetchone()['cabang']

                cursor.execute("INSERT INTO pencairan_multiguna_tempo (no_anggota, nama_anggota, jenis_pencairan, tanggal_cair, besar_pinjaman, tenor) VALUES (%s, %s, %s, %s, %s, %s)", (no_anggota, nama_anggota, jenis_pinjaman, tgl_cair_awal, besar_pinjaman, tenor))
                
                akun_piutang = '1201' if jenis_pinjaman == 'Multiguna' else '1202'
                akun_pendapatan = '4101' if jenis_pinjaman == 'Multiguna' else '4102'
                catat_jurnal_migrasi(cursor, tgl_cair_awal, akun_piutang, f"Migrasi Pencairan {jenis_pinjaman} - {nama_anggota}", besar_pinjaman, 0, cabang)
                catat_jurnal_migrasi(cursor, tgl_cair_awal, '1101', f"Kas Keluar Migrasi Pencairan - {nama_anggota}", 0, besar_pinjaman, cabang)

                tgl_cair_obj = datetime.strptime(tgl_cair_awal, '%Y-%m-%d').date()
                
                # Generate riwayat angsuran LUNAS
                for i in range(1, jml_lunas + 1):
                    tgl_bayar_histori = tambah_bulan(tgl_cair_obj, i)
                    cursor.execute("""
                        INSERT INTO angsuran_multiguna_tempo (no_anggota, nama_anggota, jenis_pinjaman, tgl_pencairan, jatuh_tempo, tgl_bayar, besar_pinjaman, tenor, bunga_persen, angsuran_ke, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, status) 
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'LUNAS')
                    """, (no_anggota, nama_anggota, jenis_pinjaman, tgl_cair_awal, tgl_bayar_histori, tgl_bayar_histori, besar_pinjaman, tenor, bunga_persen, i, pokok_perbulan, margin_perbulan, pokok_perbulan, margin_perbulan))
                    
                    catat_jurnal_migrasi(cursor, tgl_bayar_histori, '1101', f"Kas Masuk Migrasi Angsuran Ke-{i} - {nama_anggota}", pokok_perbulan + margin_perbulan, 0, cabang)
                    catat_jurnal_migrasi(cursor, tgl_bayar_histori, akun_piutang, f"Pelunasan Pokok Migrasi Ke-{i} - {nama_anggota}", 0, pokok_perbulan, cabang)
                    catat_jurnal_migrasi(cursor, tgl_bayar_histori, akun_pendapatan, f"Pendapatan Margin Migrasi Ke-{i} - {nama_anggota}", 0, margin_perbulan, cabang)

                # Generate jadwal angsuran BELUM BAYAR
                tgl_jatuh_tempo_berikutnya_obj = datetime.strptime(tgl_jatuh_tempo_berikutnya, '%Y-%m-%d').date()
                for i in range(jml_lunas + 1, tenor + 1):
                    offset = i - (jml_lunas + 1)
                    jatuh_tempo = tambah_bulan(tgl_jatuh_tempo_berikutnya_obj, offset)
                    cursor.execute("""
                        INSERT INTO angsuran_multiguna_tempo (no_anggota, nama_anggota, jenis_pinjaman, tgl_pencairan, jatuh_tempo, besar_pinjaman, tenor, bunga_persen, angsuran_ke, tagihan_pokok, tagihan_margin, status) 
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BELUM BAYAR')
                    """, (no_anggota, nama_anggota, jenis_pinjaman, tgl_cair_awal, jatuh_tempo, besar_pinjaman, tenor, bunga_persen, i, pokok_perbulan, margin_perbulan))

        # TAHAP 3: PROSES DANA URGENT
        if not df_urgent.empty:
            for _, row in df_urgent.iterrows():
                no_ref = str(row['no_referensi_excel'])
                if no_ref not in ref_to_new_id_map: continue

                no_anggota = ref_to_new_id_map[no_ref]
                nama_anggota = row['nama_anggota']
                jenis_urgent = row['jenis_urgent']
                tgl_cair_awal = row['tgl_pencairan_awal']
                tgl_jatuh_tempo = row['tgl_jatuh_tempo']
                pokok = float(row['jumlah_dana_urgent'])
                margin = float(row['margin_nominal'])
                status = row['status_pembayaran']

                cursor.execute("SELECT cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
                cabang = cursor.fetchone()['cabang']

                cursor.execute("INSERT INTO pencairan_dana_urgent (no_anggota, nama_anggota, jenis_dana_urgent, tanggal_pencairan_dana_urgent, tanggal_pembayaran_dana_urgent, jumlah_dana_urgent, margin_dana_urgent) VALUES (%s,%s,%s,%s,%s,%s,%s)", (no_anggota, nama_anggota, jenis_urgent, tgl_cair_awal, tgl_jatuh_tempo, pokok, margin))
                
                akun_piutang = '1203' if jenis_urgent == 'Gaji' else '1204'
                akun_pendapatan = '4103' if jenis_urgent == 'Gaji' else '4104'
                
                catat_jurnal_migrasi(cursor, tgl_cair_awal, akun_piutang, f"Migrasi Pencairan Urgent {jenis_urgent} - {nama_anggota}", pokok, 0, cabang)
                catat_jurnal_migrasi(cursor, tgl_cair_awal, '1101', f"Kas Keluar Migrasi Urgent {jenis_urgent} - {nama_anggota}", 0, pokok, cabang)

                if status == 'LUNAS':
                    cursor.execute("""
                        INSERT INTO angsuran_dana_urgent (no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tanggal_jatuh_tempo, tgl_bayar, tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, status) 
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'LUNAS')
                    """, (no_anggota, nama_anggota, jenis_urgent, tgl_cair_awal, tgl_jatuh_tempo, tgl_jatuh_tempo, pokok, margin, pokok, margin))
                    
                    catat_jurnal_migrasi(cursor, tgl_jatuh_tempo, '1101', f"Kas Masuk Migrasi Urgent {jenis_urgent} - {nama_anggota}", pokok + margin, 0, cabang)
                    catat_jurnal_migrasi(cursor, tgl_jatuh_tempo, akun_piutang, f"Pelunasan Pokok Migrasi Urgent {jenis_urgent} - {nama_anggota}", 0, pokok, cabang)
                    catat_jurnal_migrasi(cursor, tgl_jatuh_tempo, akun_pendapatan, f"Pendapatan Margin Migrasi Urgent {jenis_urgent} - {nama_anggota}", 0, margin, cabang)
                else: # BELUM BAYAR
                    cursor.execute("""
                        INSERT INTO angsuran_dana_urgent (no_anggota, nama_anggota, jenis_dana_urgent, tgl_pencairan, tanggal_jatuh_tempo, tagihan_pokok, tagihan_margin, status) 
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'BELUM BAYAR')
                    """, (no_anggota, nama_anggota, jenis_urgent, tgl_cair_awal, tgl_jatuh_tempo, pokok, margin))

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Migrasi data berhasil! {processed_members_count} anggota diproses dan dijurnalkan.'}), 200

    except Exception as e:
        if conn: conn.rollback()
        # Berikan pesan error yang lebih detail ke frontend
        import traceback
        error_details = traceback.format_exc()
        return jsonify({'status': 'error', 'message': f'Terjadi kesalahan: {str(e)}', 'details': error_details}), 500
    finally:
        cursor.close()
        conn.close()