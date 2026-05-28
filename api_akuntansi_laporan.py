# --- Modul Terintegrasi Akuntansi & Laporan (Dibersihkan) ---
from flask import Blueprint, request, jsonify, send_file, session
from datetime import datetime, timedelta
import calendar
import os
import tempfile
import json
from db import get_db_connection
from api_helpers import parse_float, catat_jurnal, terbilang

api_akuntansi_laporan_bp = Blueprint('api_akuntansi_laporan', __name__)

# === FUNGSI MIGRASI AMAN UNTUK MULTI CABANG ===
def safe_migrate_cabang(cursor):
    try: cursor.execute("ALTER TABLE jurnal_umum ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
    except: pass
    try: cursor.execute("ALTER TABLE pengeluaran_operasional ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
    except: pass

# === API: JURNAL & LABA RUGI ===
@api_akuntansi_laporan_bp.route('/api/jurnal', methods=['GET'])
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
        safe_migrate_cabang(cursor)
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

@api_akuntansi_laporan_bp.route('/api/laba_rugi', methods=['GET'])
def get_laba_rugi():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        safe_migrate_cabang(cursor)
        # Menggunakan LEFT JOIN agar COA dengan saldo 0 tetap tampil di laporan
        cursor.execute("""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.kredit - j.debit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s
            WHERE c.kategori = 'PENDAPATAN' 
            GROUP BY c.id
            ORDER BY c.account_code ASC
        """, (cabang,))
        pendapatan = cursor.fetchall()
        
        cursor.execute("""
            SELECT c.account_code, c.account_name, IFNULL(SUM(j.debit - j.kredit), 0) as saldo 
            FROM coa c 
            LEFT JOIN jurnal_umum j ON c.id = j.coa_id AND j.cabang = %s
            WHERE c.kategori = 'BEBAN' 
            GROUP BY c.id
            ORDER BY c.account_code ASC
        """, (cabang,))
        beban = cursor.fetchall()
        
        total_pendapatan = sum(item['saldo'] for item in pendapatan)
        total_beban = sum(item['saldo'] for item in beban)
        return jsonify({'status': 'success', 'data': {'pendapatan': pendapatan, 'beban': beban, 'total_pendapatan': float(total_pendapatan), 'total_beban': float(total_beban), 'laba_bersih': float(total_pendapatan - total_beban)}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@api_akuntansi_laporan_bp.route('/api/neraca', methods=['GET'])
def get_neraca():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')

    try:
        safe_migrate_cabang(cursor)
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
            'laba_berjalan': float(laba_berjalan), 'total_aktiva': float(total_aktiva), 
            'total_pasiva': float(total_pasiva)
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# =================================================================================
# === MODUL CETAK STRUK & DOKUMEN =================================================
# =================================================================================

@api_akuntansi_laporan_bp.route('/api/cetak_struk/<jenis>/<id_tagihan>/<format_file>', methods=['GET'], endpoint='api_cetak_struk_baru')
def cetak_struk(jenis, id_tagihan, format_file):
    try:
        from fpdf import FPDF
    except ImportError:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
        
    if jenis == 'TEMPLATE':
        nama = "(Otomatis Nama Anggota)"
        no_anggota = "(Otomatis No Anggota)"
        no_kontrak = "(Otomatis No Kontrak)"
        instansi = "(Otomatis Instansi)"
        jenis_pinjaman = "(Otomatis Jenis Pinjaman)"
        angsuran_ke = "(Ke-X)"
        sisa_angsuran = "(Sisa-Y)"
        pokok = 0; margin = 0; denda = 0; total = 0
        sisa_gaji_val = 0
        edc = "-"
        tgl_str = "(Otomatis Tgl Bayar)"
        def f_rp(val): return "(Otomatis Nominal)"
        terbilang_text = "* (otomatis terbilang rupiah) *"
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            if jenis == 'utama':
                cursor.execute("""
                    SELECT a.*, i.pt_instansi, p.id as id_pencairan
                    FROM angsuran_multiguna_tempo a
                    JOIN identitas i ON a.no_anggota = i.no_anggota
                    LEFT JOIN pencairan_multiguna_tempo p ON a.no_anggota = p.no_anggota AND a.tgl_pencairan = p.tanggal_cair
                    WHERE a.id = %s LIMIT 1
                """, (id_tagihan,))
                data = cursor.fetchone()
                jenis_pinjaman = data.get('jenis_pinjaman') if data else ''
            else:
                cursor.execute("""
                    SELECT a.*, i.pt_instansi, p.id as id_pencairan
                    FROM angsuran_dana_urgent a
                    JOIN identitas i ON a.no_anggota = i.no_anggota
                    LEFT JOIN pencairan_dana_urgent p ON a.no_anggota = p.no_anggota AND a.tgl_pencairan = p.tanggal_pencairan_dana_urgent
                    WHERE a.id = %s LIMIT 1
                """, (id_tagihan,))
                data = cursor.fetchone()
                jenis_pinjaman = data.get('jenis_dana_urgent') if data else ''
            
            if not data: return f"<h3>Error: Data tagihan tidak ditemukan!</h3>", 404
    
            nama = data['nama_anggota']
            no_anggota = data['no_anggota']
            no_kontrak = f"104.{data['id_pencairan']:07d}" if data.get('id_pencairan') else "-"
            instansi = data.get('pt_instansi') or "-"
            
            angsuran_ke = data.get('angsuran_ke', 1)
            tenor = data.get('tenor', 1)
            sisa_angsuran = max(0, tenor - angsuran_ke)
            
            pokok = float(data.get('angsuran_pokok') or 0)
            margin = float(data.get('angsuran_margin') or 0)
            denda = float(data.get('angsuran_denda') or 0)
            sisa_gaji_val = float(data.get('sisa_gaji') or 0)
            edc = data.get('edc') or "-"
            try: 
                edc_num = float(edc)
                edc_str_view = f"Rp {edc_num:,.0f}".replace(',', '.')
            except: 
                edc_num = 0
                edc_str_view = edc
            total = pokok + margin + denda + edc_num
            
            tgl_bayar_obj = data.get('tgl_bayar')
            if isinstance(tgl_bayar_obj, str):
                try: tgl_bayar_obj = datetime.strptime(tgl_bayar_obj, '%Y-%m-%d').date()
                except: tgl_bayar_obj = datetime.now().date()
            if not tgl_bayar_obj: tgl_bayar_obj = datetime.now().date()
            
            months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
            tgl_str = f"{tgl_bayar_obj.day} {months[tgl_bayar_obj.month]} {tgl_bayar_obj.year}"
            
            def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
            terbilang_text = f"* {terbilang(total).lower()} rupiah *"
        except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()

    try:
        # Menggunakan format A5 Landscape (Setengah A4 Mendatar) untuk 1 slip utuh
        pdf = FPDF(orientation='L', format='A5')
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=5)
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 5, txt="KSP GABE ARTHA NAULI", ln=True, align='L')
        pdf.set_font("Arial", '', 8)
        pdf.cell(0, 4, txt="Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten", ln=True, align='L')
        
        pdf.ln(2)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(0, 5, txt="BUKTI ANGSURAN", ln=True, align='C')
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(1)
        pdf.set_font("Arial", '', 9)
        pdf.cell(0, 4, txt="SLIP PEMBAYARAN ANGGOTA", ln=True, align='C')
        pdf.ln(3)
        
        w1, w2, w3, w4 = 30, 3, 100, 40
        def print_row(l1, v1):
            pdf.cell(w1, 4.5, txt=l1); pdf.cell(w2, 4.5, txt=":"); pdf.cell(w3, 4.5, txt=str(v1)); pdf.ln(4.5)

        pdf.cell(w1, 4.5, "Jenis Transaksi"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"ANGSURAN KE - {angsuran_ke}    SISA : {sisa_angsuran}")
        pdf.cell(w4, 4.5, "Jumlah Sisa Gaji", ln=True)
        pdf.cell(w1, 4.5, "Nama Anggota"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, nama)
        if jenis == 'TEMPLATE': pdf.cell(w4, 4.5, f"Rp. (Otomatis)", ln=True)
        else: pdf.cell(w4, 4.5, f"Rp. {f_rp(sisa_gaji_val)}", ln=True)

        print_row("Kode Anggota", no_anggota)
        print_row("No Kontrak", no_kontrak)
        print_row("Instansi", instansi)
        
        pdf.cell(w1, 4.5, "Jenis Pinjaman"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, jenis_pinjaman)
        pdf.cell(w4, 4.5, "Kurang Bayar", ln=True)
        pdf.cell(w1, 4.5, "Angsuran"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"Rp {f_rp(pokok+margin)}" if jenis != 'TEMPLATE' else "(Otomatis)")
        pdf.cell(w4, 4.5, "-", ln=True)
        
        print_row("Biaya EDC", edc_str_view)
        print_row("Simpanan Wajib", "-")
        print_row("Admin", "-")
        print_row("Biaya Denda", f"Rp {f_rp(denda)}" if denda > 0 and jenis != 'TEMPLATE' else ("-" if jenis != 'TEMPLATE' else "(Otomatis)"))
        print_row("Jumlah Bayar", f"Rp {f_rp(total)}" if jenis != 'TEMPLATE' else "(Otomatis)")
        print_row("Terbilang", terbilang_text)
        
        pdf.ln(3)
        pdf.cell(90, 4.5, "Yang menyetor", align='C')
        pdf.cell(100, 4.5, f"Tangerang, {tgl_str}", align='C', ln=True)
        pdf.cell(90, 4.5, "", align='C')
        pdf.cell(100, 4.5, "MANAGER", align='C', ln=True)
        pdf.ln(12)
        
        pdf.set_font("Arial", 'U', 9)
        pdf.cell(90, 4.5, nama, align='C')
        pdf.cell(100, 4.5, "N.SRI UTAMI", align='C', ln=True)
        
        pdf.set_font("Arial", '', 7)
        pdf.ln(3)
        pdf.cell(0, 4, "-- SIMPANLAH BUKTI PEMBAYARAN INI SEBAGAI BUKTI TRANSAKSI ANDA --", align='C', ln=True)

        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"Struk_{jenis}_{id_tagihan}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

# === API: CETAK AKAD PINJAMAN (SESUAI FORMAT RESMI) ===
@api_akuntansi_laporan_bp.route('/api/cetak_akad/<no_anggota>/<tgl_pencairan>', methods=['GET'], endpoint='api_cetak_akad_baru')
def cetak_akad(no_anggota, tgl_pencairan):
    try:
        from fpdf import FPDF
    except ImportError:
        return "<h3>Error: Library FPDF belum diinstall!</h3><p>Buka terminal & jalankan: <b>pip install fpdf</b></p>", 500

    if no_anggota == 'TEMPLATE':
        no_pinjaman = "(Otomatis No Pencairan)"
        no_anggota_pdf = "(Otomatis No Anggota)"
        nama = "(Otomatis Nama Anggota)"
        nik = "(Otomatis NIK)"
        pekerjaan = "(Otomatis Pekerjaan)"
        alamat = "(Otomatis Alamat Lengkap)"
        rekening = "(Otomatis Bank / No Rekening)"
        cabang_nama = "(OTOMATIS CABANG)"
        tgl_str = "(Otomatis Tanggal Cair)"

        terms = [
            "Pihak ke 1(satu) telah mengaku meminjam uang dari pihak ke 2(dua) sebesar (Otomatis Nominal Pinjaman) dengan jasa atau suku bunga (Otomatis Bunga%) /bulan dan flat selama angsuran.",
            "Pihak ke 1(satu) menyerahkan jaminan/berkas persyaratan pinjaman ke pihak ke 2(dua) yang tertera di serah terima berkas dan Pihak ke 1(satu) tidak dibenarkan menggandakan berkas yang sudah dijaminkan kepada Pihak ke 2(dua).",
            "Pihak ke 1(satu) menyetujui potongan simpanan pokok (Otomatis Simpanan Pokok). Dan biaya administrasi (Otomatis Adm%) dari pinjaman yang diberikan.",
            f"Pihak ke 1(satu) menyetujui pemotongan dari ATM GAJI, dan pengalihan angsuran dari nomor rekening: {rekening}. Apabila ada pergantian ATM, buku tabungan, atau rekening gaji dari perusahaan, maka Pihak ke 1(satu) harus bersedia memberikannya kepada Pihak ke 2(dua). Dan Pihak ke 1(satu) tidak akan menggunakan fasilitas m-banking, SMS banking, internet banking, mengalihkan gaji ke rekening lain, atau mengambil gaji tunai di perusahaan tempat bekerja.",
            "Untuk pembayaran pinjaman ini, Pihak ke 1(satu) bersedia dipotong angsuran oleh Pihak ke 2(dua) sebesar (Otomatis Angsuran Per Bulan) x (Otomatis Tenor), dan Pihak ke 1(satu) wajib menabung sebesar 0 (Nol Rupiah) setiap bulannya.",
            "Jika angsuran menunggak, maka Pihak ke 1(satu) akan dibebankan denda sebesar 0.5% per hari dari total tunggakan dan dihitung dari jatuh tempo pembayaran.",
            "Apabila Pihak ke 1(satu) berhenti atau PHK dari perusahaan tempat bekerja, maka Pihak ke 1(satu) harus melunasi pinjamannya dari Pesangon atau dari Saldo Jamsostek/JHT (Jaminan Hari Tua).",
            "Pihak ke 1(satu) wajib terdaftar dalam Asuransi BPJS Ketenagakerjaan BPU dan disepakati oleh Pihak ke 1(satu) dan Pihak ke 2(dua) dengan biaya potongan awal sebesar (Otomatis Biaya Jamsostek) untuk 3 program:\n- JKM (Jaminan Kematian)\n- JKK (Jaminan Kecelakaan Kerja)\n- JHT (Jaminan Hari Tua)",
            "Apabila Pihak ke 1(satu) mengajukan pinjaman atau kredit ke pihak lain, maka Pihak ke 1(satu) harus melunasi pinjaman kepada Pihak ke 2(dua) (KSP GABE ARTHA NAULI).",
            "Dan apabila Pihak ke 1(satu) melanggar surat perjanjian ini, maka bersedia dituntut ke Pengadilan Negeri Tigaraksa dan biaya perkara pengadilan dibebankan sepenuhnya kepada Pihak ke 1(satu)."
        ]
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT p.*, i.nik_ktp, i.pt_instansi, i.status_karyawan, i.jabatan, 
                       i.alamat_ktp, i.no_rek, i.bank, i.nama_penanggung_jawab, i.cabang
                FROM pencairan_multiguna_tempo p JOIN identitas i ON p.no_anggota = i.no_anggota
                WHERE p.no_anggota = %s AND DATE(p.tanggal_cair) = %s LIMIT 1
            """
            cursor.execute(query, (no_anggota, tgl_pencairan))
            data = cursor.fetchone()
            if not data: return f"<h3>Error: Data pencairan tidak ditemukan untuk Anggota {no_anggota} pada tanggal {tgl_pencairan}</h3><p>Pastikan data ini adalah pinjaman Multiguna/Tempo.</p>", 404

            cursor.execute("SELECT bunga_persen, tagihan_pokok, tagihan_margin FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND tgl_pencairan = %s LIMIT 1", (no_anggota, tgl_pencairan))
            angsuran = cursor.fetchone()
            
            if angsuran:
                bunga_persen = float(angsuran['bunga_persen'] or 0)
                angsuran_perbulan = float(angsuran['tagihan_pokok'] or 0) + float(angsuran['tagihan_margin'] or 0)
            else:
                bunga_persen = 0
                angsuran_perbulan = 0

            no_pinjaman = f"104.{data['id']:07d}"
            no_anggota_pdf = data['no_anggota']
            nama = data['nama_anggota']
            nik = data['nik_ktp'] or '-'
            pekerjaan = f"{data['status_karyawan'] or 'Karyawan'} - {data['pt_instansi'] or '-'}"
            alamat = data['alamat_ktp'] or '-'
            cabang_nama = str(data.get('cabang') or 'PUTAT').upper()
            rekening = f"{data['bank'] or '-'} / {data['no_rek'] or '-'} A.N {nama}"
            
            besar_pinjaman = float(data.get('besar_pinjaman') or 0)
            simpanan_pokok = float(data.get('potongan_simpanan_pokok') or 0)
            biaya_adm = float(data.get('potongan_adm') or 0)
            biaya_adm_persen = (biaya_adm / besar_pinjaman * 100) if besar_pinjaman > 0 else 0
            biaya_jamsostek = float(data.get('biaya_jamsostek') or 0)
            tenor = data.get('tenor') or 1
            
            tgl = data['tanggal_cair']
            if isinstance(tgl, str):
                try: tgl = datetime.strptime(tgl, '%Y-%m-%d').date()
                except: tgl = datetime.now().date()
                
            months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
            tgl_str = f"{tgl.day} {months[tgl.month]} {tgl.year}" if hasattr(tgl, 'strftime') else str(tgl)
                
            def f_rp(val): return f"{val:,.0f}".replace(',', '.')

            terms = [
                f"Pihak ke 1(satu) telah mengaku meminjam uang dari pihak ke 2(dua) sebesar {f_rp(besar_pinjaman)} ({terbilang(besar_pinjaman)} Rupiah) dengan jasa atau suku bunga {bunga_persen:g}% ({terbilang(bunga_persen)} persen) /bulan dan flat selama angsuran.",
                "Pihak ke 1(satu) menyerahkan jaminan/berkas persyaratan pinjaman ke pihak ke 2(dua) yang tertera di serah terima berkas dan Pihak ke 1(satu) tidak dibenarkan menggandakan berkas yang sudah dijaminkan kepada Pihak ke 2(dua).",
                f"Pihak ke 1(satu) menyetujui potongan simpanan pokok {f_rp(simpanan_pokok)} ({terbilang(simpanan_pokok)} Rupiah). Dan biaya administrasi {biaya_adm_persen:g}% dari pinjaman yang diberikan.",
                f"Pihak ke 1(satu) menyetujui pemotongan dari ATM GAJI, dan pengalihan angsuran dari nomor rekening: {rekening}. Apabila ada pergantian ATM, buku tabungan, atau rekening gaji dari perusahaan, maka Pihak ke 1(satu) harus bersedia memberikannya kepada Pihak ke 2(dua). Dan Pihak ke 1(satu) tidak akan menggunakan fasilitas m-banking, SMS banking, internet banking, mengalihkan gaji ke rekening lain, atau mengambil gaji tunai di perusahaan tempat bekerja.",
                f"Untuk pembayaran pinjaman ini, Pihak ke 1(satu) bersedia dipotong angsuran oleh Pihak ke 2(dua) sebesar {f_rp(angsuran_perbulan)} ({terbilang(angsuran_perbulan)} Rupiah) x {tenor}, dan Pihak ke 1(satu) wajib menabung sebesar 0 (Nol Rupiah) setiap bulannya.",
                "Jika angsuran menunggak, maka Pihak ke 1(satu) akan dibebankan denda sebesar 0.5% per hari dari total tunggakan dan dihitung dari jatuh tempo pembayaran.",
                "Apabila Pihak ke 1(satu) berhenti atau PHK dari perusahaan tempat bekerja, maka Pihak ke 1(satu) harus melunasi pinjamannya dari Pesangon atau dari Saldo Jamsostek/JHT (Jaminan Hari Tua).",
                f"Pihak ke 1(satu) wajib terdaftar dalam Asuransi BPJS Ketenagakerjaan BPU dan disepakati oleh Pihak ke 1(satu) dan Pihak ke 2(dua) dengan biaya potongan awal sebesar {f_rp(biaya_jamsostek)} ({terbilang(biaya_jamsostek)} Rupiah) untuk 3 program:\n- JKM (Jaminan Kematian)\n- JKK (Jaminan Kecelakaan Kerja)\n- JHT (Jaminan Hari Tua)",
                "Apabila Pihak ke 1(satu) mengajukan pinjaman atau kredit ke pihak lain, maka Pihak ke 1(satu) harus melunasi pinjaman kepada Pihak ke 2(dua) (KSP GABE ARTHA NAULI).",
                "Dan apabila Pihak ke 1(satu) melanggar surat perjanjian ini, maka bersedia dituntut ke Pengadilan Negeri Tigaraksa dan biaya perkara pengadilan dibebankan sepenuhnya kepada Pihak ke 1(satu)."
            ]
        except Exception as e: return f"<h3>Terjadi Kesalahan Internal Saat Menggambar PDF:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()

    try:
        pdf = FPDF(format='A4')
        pdf.add_page()
        pdf.set_margins(12, 10, 12)
        pdf.set_auto_page_break(auto=True, margin=10)
        
        logo_path = os.path.join(os.getcwd(), 'static', 'img', 'logo.png')
        if os.path.exists(logo_path): pdf.image(logo_path, x=12, y=10, w=20)
            
        pdf.set_font("Arial", 'B', 12); pdf.cell(0, 5, txt="KSP GABE ARTHA NAULI", ln=True, align='C')
        pdf.set_font("Arial", 'B', 11); pdf.cell(0, 5, txt=f"GABE ARTHA NAULI CABANG : {cabang_nama}", ln=True, align='C')
        pdf.set_font("Arial", '', 9); pdf.cell(0, 4, txt="Badan Hukum : AHU.0002217.AH.01.26 TAHUN 2020", ln=True, align='C')
        pdf.set_font("Arial", 'I', 8); pdf.cell(0, 4, txt="Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten", ln=True, align='C')
        
        pdf.ln(2); pdf.line(12, pdf.get_y(), 198, pdf.get_y()); pdf.line(12, pdf.get_y()+0.6, 198, pdf.get_y()+0.6); pdf.ln(3)
        
        pdf.set_font("Arial", '', 9)
        pdf.cell(25, 4.5, txt="No. Pinjaman", ln=False); pdf.cell(0, 4.5, txt=f": {no_pinjaman}", ln=True)
        pdf.cell(25, 4.5, txt="No. Anggota", ln=False); pdf.cell(0, 4.5, txt=f": {no_anggota_pdf}", ln=True); pdf.ln(3)
        
        pdf.set_font("Arial", 'BU', 11); pdf.cell(0, 5, txt="SURAT PENGAKUAN HUTANG / PERJANJIAN KREDIT", ln=True, align='C'); pdf.ln(3)
        pdf.set_font("Arial", '', 9); pdf.cell(0, 4.5, txt="Yang bertanda tangan di bawah ini :", ln=True); pdf.ln(1)
        
        pdf.cell(25, 4.5, txt="Nama", ln=False); pdf.cell(3, 4.5, txt=":"); pdf.cell(0, 4.5, txt=f"{nama}", ln=True)
        pdf.cell(25, 4.5, txt="NIK", ln=False); pdf.cell(3, 4.5, txt=":"); pdf.cell(0, 4.5, txt=f"{nik}", ln=True)
        pdf.cell(25, 4.5, txt="Pekerjaan", ln=False); pdf.cell(3, 4.5, txt=":"); pdf.cell(0, 4.5, txt=f"{pekerjaan}", ln=True)
        pdf.cell(25, 4.5, txt="Alamat", ln=False); pdf.cell(3, 4.5, txt=":"); pdf.multi_cell(0, 4.5, txt=f"{alamat}")
        pdf.set_x(12)
        pdf.cell(25, 4.5, txt="No. Rekening", ln=False); pdf.cell(3, 4.5, txt=":"); pdf.cell(0, 4.5, txt=f"{rekening}", ln=True)
        
        pdf.ln(2); pdf.cell(0, 4.5, txt="Selanjutnya disebut pihak ke 1 (satu) (yang berhutang).", ln=True); pdf.ln(2)
        pdf.multi_cell(0, 4.5, txt="Pimpinan KSP GABE ARTHA NAULI, dalam hal ini bertindak untuk dan atas nama KSP GABE ARTHA NAULI, yang beralamat di Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten.")
        pdf.ln(2); pdf.cell(0, 4.5, txt="Selanjutnya disebut sebagai Pihak ke 2 (dua) (KSP GABE ARTHA NAULI).", ln=True); pdf.ln(2)
        pdf.cell(0, 4.5, txt="Kedua belah pihak telah sepakat dengan perjanjian sebagai berikut:", ln=True); pdf.ln(1)
        
        for i, text in enumerate(terms, 1):
            pdf.set_left_margin(17); pdf.set_x(12)
            pdf.cell(5, 4.5, txt=f"{i}.", ln=False)
            pdf.multi_cell(0, 4.5, txt=str(text).replace('\r', ''))
            pdf.set_left_margin(12); pdf.ln(0.5)
            
        pdf.ln(2); pdf.multi_cell(0, 4.5, txt="Demikian surat perjanjian ini dibuat dengan pikiran tenang, sehat jasmani dan rohani tanpa ada unsur paksaan dari pihak manapun.")
        
        if pdf.get_y() > 255: pdf.add_page()
        pdf.ln(5)
        pdf.cell(85, 4.5, txt="PIHAK KEDUA", ln=False, align='C'); pdf.cell(90, 4.5, txt=f"Tangerang, {tgl_str}", ln=True, align='C')
        pdf.cell(85, 4.5, txt="KSP GABE ARTHA NAULI", ln=False, align='C'); pdf.cell(90, 4.5, txt="PIHAK PERTAMA", ln=True, align='C')
        pdf.ln(16)
        pdf.cell(85, 4.5, txt="(------------------------------)", ln=False, align='C'); pdf.set_font("Arial", 'BU', 9); pdf.cell(90, 4.5, txt=f"{nama}", ln=True, align='C')

        file_path = os.path.join(tempfile.gettempdir(), f"Akad_Pinjaman_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan Internal Saat Menggambar PDF:</h3><p>{str(e)}</p>", 500

# === API: CETAK SURAT PERNYATAAN PINJAMAN ===
@api_akuntansi_laporan_bp.route('/api/cetak_pernyataan/<no_anggota>/<tgl_pencairan>', methods=['GET'], endpoint='api_cetak_pernyataan_baru')
def cetak_pernyataan(no_anggota, tgl_pencairan):
    try: from fpdf import FPDF
    except ImportError: return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

    if no_anggota == 'TEMPLATE':
        nama = "(Otomatis Nama Anggota)"
        no_rek = "(Otomatis No Rekening)"
        nik = "(Otomatis NIK)"
        alamat = "(Otomatis Alamat)"
        pekerjaan = "(Otomatis Pekerjaan)"
        bank = "(Otomatis Bank)"
        besar_pinjaman_rp = "(Otomatis Nominal)"
        cabang_nama = "(OTOMATIS CABANG)"
        tenor = "(X)"
        tgl_str = "(Otomatis Tanggal Cair)"
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT p.*, i.nik_ktp, i.pt_instansi, i.status_karyawan, i.jabatan, 
                       i.alamat_ktp, i.no_rek, i.bank, i.cabang
                FROM pencairan_multiguna_tempo p JOIN identitas i ON p.no_anggota = i.no_anggota
                WHERE p.no_anggota = %s AND DATE(p.tanggal_cair) = %s LIMIT 1
            """
            cursor.execute(query, (no_anggota, tgl_pencairan))
            data = cursor.fetchone()
            if not data: return f"<h3>Error: Data pencairan tidak ditemukan.</h3>", 404
            
            nama = data['nama_anggota']
            no_rek = data['no_rek'] or "-------------------"
            nik = data['nik_ktp'] or "-"
            alamat = data['alamat_ktp'] or "-"
            pekerjaan = f"{data['status_karyawan'] or '-'} - {data['pt_instansi'] or '-'}"
            bank = data['bank'] or ".........."
            cabang_nama = str(data.get('cabang') or 'PUTAT').upper()
            
            besar_pinjaman = float(data.get('besar_pinjaman') or 0)
            def f_rp(val): return f"{val:,.0f}".replace(',', '.')
            besar_pinjaman_rp = f_rp(besar_pinjaman)
            tenor = data.get('tenor') or 1
            
            tgl = data['tanggal_cair']
            if isinstance(tgl, str):
                try: tgl = datetime.strptime(tgl, '%Y-%m-%d').date()
                except: tgl = datetime.now().date()
            months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
            tgl_str = f"{tgl.day} {months[tgl.month]} {tgl.year}" if hasattr(tgl, 'strftime') else str(tgl)
        except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()

    try:
        pdf = FPDF(format='A4')
        pdf.add_page(); pdf.set_margins(15, 15, 15); pdf.set_auto_page_break(auto=True, margin=15)
        
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 6, txt="KSP GABE ARTHA NAULI", ln=True, align='L')
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 5, txt="Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten", ln=True, align='L')
        pdf.ln(5)
        
        pdf.set_font("Arial", 'BU', 12)
        pdf.cell(0, 6, txt="SURAT PERNYATAAN PINJAMAN ANGGOTA", ln=True, align='C')
        pdf.ln(5)
        
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 6, txt="Yang bertanda tangan di bawah ini :", ln=True); pdf.ln(2)
        
        w1, w2 = 35, 5
        pdf.cell(w1, 6, txt="Nama", ln=False); pdf.cell(w2, 6, txt=":"); pdf.cell(0, 6, txt=nama, ln=True)
        pdf.cell(w1, 6, txt="NOREKENING", ln=False); pdf.cell(w2, 6, txt=":"); pdf.cell(0, 6, txt=no_rek, ln=True)
        pdf.cell(w1, 6, txt="NIK", ln=False); pdf.cell(w2, 6, txt=":"); pdf.cell(0, 6, txt=nik, ln=True)
        pdf.cell(w1, 6, txt="Alamat", ln=False); pdf.cell(w2, 6, txt=":"); pdf.multi_cell(0, 6, txt=alamat)
        pdf.set_x(15)
        pdf.cell(w1, 6, txt="Pekerjaan", ln=False); pdf.cell(w2, 6, txt=":"); pdf.cell(0, 6, txt=pekerjaan, ln=True)
        
        pdf.ln(4)
        pdf.cell(0, 6, txt="Dengan ini saya menyatakan,", ln=True); pdf.ln(2)
        
        terms = [
            f"Saya secara benar dan Sadar telah meminjam uang sebesar Rp. {besar_pinjaman_rp} dengan jangka waktu {tenor} Bulan kepada pihak Koperasi Simpan Pinjam KSP GABE ARTHA NAULI. Pinjaman tersebut adalah benar atas pinjaman atas nama saya sendiri tanpa ada unsur paksaan, Pembagian hasil pinjaman, tarikan patokan fee oleh pihak ke-tiga atau tanpa pihak manapun.",
            f"Saya selaku Nasabah KSP GABE ARTHA NAULI telah menerima uang sebagai pinjaman, adapun angsuran nya di ambil dari Rekening Buku Tabungan Bank {bank} Dengan No Rekening {no_rek} Nomor ATM ..............................",
            "Saya berjanji tidak akan memblokir rekening, mengganti rekening, mengalihkan gaji, dan tidak akan mempergunakan fasilitas M-banking, Sms Banking, I-Banking dari rekening gaji, dan tidak akan membuat kembali buku tabungan yang telah saya jaminkan di KSP GABE ARTHA NAULI.",
            f"Dan apabila gaji saya suatu saat nanti turun ke Bank lain maka saya akan mengantarkan langsung ke kantor KSP GABE ARTHA NAULI CABANG {cabang_nama} yang beralamat di Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten tanpa harus disusul atau dijemput."
        ]
        
        for i, text in enumerate(terms, 1):
            pdf.set_left_margin(22); pdf.set_x(15)
            pdf.cell(7, 6, txt=f"{i}.", ln=False)
            pdf.multi_cell(0, 6, txt=text)
            pdf.set_left_margin(15); pdf.ln(2)
            
        pdf.ln(3)
        pdf.multi_cell(0, 6, txt="Demikian Surat Pernyataan ini saya buat dalam keadaan sehat jasmani dan rohani tanpa ada unsur paksaan dari pihak manapun, dan apabila saya melanggar surat pernyataan ini maka saya bersedia di tuntut melalui jalur hukum yang berlaku di Negara Republik Indonesia.")
        
        pdf.ln(15)
        pdf.cell(100, 6, txt="", ln=False)
        pdf.cell(90, 6, txt=f"Tangerang, {tgl_str}", ln=True, align='C')
        pdf.ln(25)
        pdf.cell(100, 6, txt="", ln=False)
        pdf.set_font("Arial", 'U', 10)
        pdf.cell(90, 6, txt=f"{nama}", ln=True, align='C')

        file_path = os.path.join(tempfile.gettempdir(), f"Pernyataan_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

# === API: MENGAMBIL DAFTAR RIWAYAT PENCAIRAN (UNTUK MENU CETAK BERKAS) ===
@api_akuntansi_laporan_bp.route('/api/daftar_cetak_akad', methods=['GET'], endpoint='api_daftar_akad_baru')
def get_daftar_cetak_akad():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        cursor.execute("""
            SELECT p.id, p.no_anggota, p.nama_anggota, p.jenis_pencairan, p.tanggal_cair, p.besar_pinjaman, p.tenor 
            FROM pencairan_multiguna_tempo p
            JOIN identitas i ON p.no_anggota = i.no_anggota
            WHERE i.cabang = %s
            ORDER BY p.tanggal_cair DESC, p.id DESC
        """, (cabang,))
        data = cursor.fetchall()
        for row in data:
            if hasattr(row['tanggal_cair'], 'isoformat'): row['tanggal_cair'] = str(row['tanggal_cair'])
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: MENGAMBIL DAFTAR RIWAYAT PEMBAYARAN (UNTUK MENU CETAK BUKTI ANGSURAN) ===
@api_akuntansi_laporan_bp.route('/api/daftar_cetak_struk', methods=['GET'], endpoint='api_daftar_struk_baru')
def get_daftar_cetak_struk():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        cursor.execute("""
            SELECT a.id, a.no_anggota, a.nama_anggota, a.jenis_pinjaman as jenis, a.angsuran_ke, a.tgl_bayar, 'utama' as kategori 
            FROM angsuran_multiguna_tempo a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE a.status = 'LUNAS' AND i.cabang = %s
            ORDER BY a.tgl_bayar DESC, a.id DESC LIMIT 200
        """, (cabang,))
        utama = cursor.fetchall()
        cursor.execute("""
            SELECT a.id, a.no_anggota, a.nama_anggota, a.jenis_dana_urgent as jenis, 1 as angsuran_ke, a.tgl_bayar, 'urgent' as kategori 
            FROM angsuran_dana_urgent a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE a.status = 'LUNAS' AND i.cabang = %s
            ORDER BY a.tgl_bayar DESC, a.id DESC LIMIT 200
        """, (cabang,))
        urgent = cursor.fetchall()
        data = utama + urgent
        data.sort(key=lambda x: str(x['tgl_bayar']) if x['tgl_bayar'] else '', reverse=True)
        for row in data:
            if hasattr(row['tgl_bayar'], 'isoformat'): row['tgl_bayar'] = str(row['tgl_bayar'])
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: MENGAMBIL DAFTAR RIWAYAT SIMPANAN ===
@api_akuntansi_laporan_bp.route('/api/daftar_cetak_simpanan', methods=['GET'], endpoint='api_daftar_simpanan_baru')
def get_daftar_cetak_simpanan():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        safe_migrate_cabang(cursor)
        cursor.execute("""
            SELECT j.id, j.tanggal, c.account_name, j.keterangan, j.debit, j.kredit 
            FROM jurnal_umum j 
            JOIN coa c ON j.coa_id = c.id 
            WHERE c.account_code IN ('3101', '3102') AND j.cabang = %s
            ORDER BY j.tanggal DESC, j.id DESC LIMIT 200
        """, (cabang,))
        data = cursor.fetchall()
        for row in data:
            if hasattr(row['tanggal'], 'isoformat'): row['tanggal'] = str(row['tanggal'])
            row['jenis_transaksi'] = 'Penarikan' if row['debit'] > 0 else 'Setoran'
            row['nominal'] = row['debit'] if row['debit'] > 0 else row['kredit']
            try: row['nama_anggota'] = row['keterangan'].split(' - ')[1]
            except: row['nama_anggota'] = 'Anggota'
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: CETAK BUKTI SIMPANAN ===
@api_akuntansi_laporan_bp.route('/api/cetak_simpanan/<tipe>/<id_jurnal>', methods=['GET'], endpoint='api_cetak_simpanan_baru')
def cetak_simpanan(tipe, id_jurnal):
    try: from fpdf import FPDF
    except ImportError: return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

    if id_jurnal == 'TEMPLATE':
        tanggal = "(Otomatis Tanggal)"
        keterangan = "(Otomatis Keterangan)"
        jenis_transaksi = "SETORAN SIMPANAN" if tipe == 'setoran' else "PENARIKAN SIMPANAN"
        nominal = 0
        nama_anggota = "(Otomatis Nama Anggota)"
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT j.tanggal, c.account_name, j.keterangan, j.debit, j.kredit FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE j.id = %s", (id_jurnal,))
            data = cursor.fetchone()
            if not data: return "<h3>Data transaksi tidak ditemukan!</h3>", 404
            
            tgl_obj = data['tanggal']
            if isinstance(tgl_obj, str):
                try: tgl_obj = datetime.strptime(tgl_obj, '%Y-%m-%d').date()
                except: tgl_obj = datetime.now().date()
            if not tgl_obj: tgl_obj = datetime.now().date()
            months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
            tanggal = f"{tgl_obj.day} {months[tgl_obj.month]} {tgl_obj.year}"
            
            keterangan = data['keterangan']
            try: nama_anggota = keterangan.split(' - ')[1]
            except: nama_anggota = "Anggota"
            
            if float(data['debit']) > 0: jenis_transaksi = "PENARIKAN SIMPANAN"; nominal = float(data['debit'])
            else: jenis_transaksi = "SETORAN SIMPANAN"; nominal = float(data['kredit'])
        except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()
        
    try:
        pdf = FPDF(orientation='L', format='A5')
        pdf.add_page(); pdf.set_margins(10, 10, 10)
        
        pdf.set_font("Arial", 'B', 12); pdf.cell(0, 5, txt="KSP GABE ARTHA NAULI", ln=True, align='L')
        pdf.set_font("Arial", '', 8); pdf.cell(0, 4, txt="Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya-Tangerang-Banten", ln=True, align='L')
        
        pdf.ln(3); pdf.set_font("Arial", 'B', 11); pdf.cell(0, 5, txt=f"BUKTI TRANSAKSI {jenis_transaksi}", ln=True, align='C')
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(4)
        
        pdf.set_font("Arial", '', 10)
        pdf.cell(35, 6, "Tanggal Transaksi", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, tanggal, ln=True)
        pdf.cell(35, 6, "Nama Anggota", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, nama_anggota, ln=True)
        pdf.cell(35, 6, "Keterangan", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, keterangan, ln=True)
        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
        from api_helpers import terbilang
        pdf.cell(35, 6, "Nominal", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, f"Rp {f_rp(nominal)}" if id_jurnal != 'TEMPLATE' else "(Otomatis Nominal)", ln=True)
        pdf.cell(35, 6, "Terbilang", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, f"* {terbilang(nominal).lower()} rupiah *" if id_jurnal != 'TEMPLATE' else "(Otomatis Terbilang)", ln=True)
        
        pdf.ln(12)
        pdf.cell(90, 5, "Penyetor / Penerima", align='C'); pdf.cell(100, 5, "Kasir / Teller", align='C', ln=True)
        pdf.ln(18)
        pdf.cell(90, 5, f"({nama_anggota})", align='C'); pdf.cell(100, 5, "(____________________)", align='C', ln=True)
        
        file_path = os.path.join(tempfile.gettempdir(), f"Simpanan_{id_jurnal}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500


@api_akuntansi_laporan_bp.route('/api/evaluasi_dashboard', methods=['GET'])
def evaluasi_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        safe_migrate_cabang(cursor)
        today = datetime.now().date()
        def get_totals(start, end):
            cursor.execute("SELECT SUM(j.kredit - j.debit) as total FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'PENDAPATAN' AND j.cabang = %s AND j.tanggal BETWEEN %s AND %s", (cabang, start, end))
            p = cursor.fetchone()['total'] or 0
            cursor.execute("SELECT SUM(j.debit - j.kredit) as total FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE c.kategori = 'BEBAN' AND j.cabang = %s AND j.tanggal BETWEEN %s AND %s", (cabang, start, end))
            b = cursor.fetchone()['total'] or 0
            return float(p), float(b)

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

        bulanan = []
        for month in range(1, today.month + 1):
            start_date = today.replace(month=month, day=1)
            last_day = calendar.monthrange(today.year, month)[1]
            end_date = today.replace(month=month, day=last_day)
            p, b = get_totals(start_date, end_date)
            bulanan.append({'bulan': start_date.strftime('%b'), 'pendapatan': p, 'beban': b})

        return jsonify({'status': 'success', 'data': {
            'harian': {'now': {'tanggal': str(today), 'pendapatan': harian_now_p, 'beban': harian_now_b}, 'prev': {'tanggal': str(bulan_lalu_hari_ini), 'pendapatan': harian_prev_p, 'beban': harian_prev_b}},
            'mingguan': {'now': {'start': str(start_of_week), 'end': str(end_of_week), 'pendapatan': mingguan_now_p, 'beban': mingguan_now_b}, 'prev': {'start': str(start_of_prev_week), 'end': str(end_of_prev_week), 'pendapatan': mingguan_prev_p, 'beban': mingguan_prev_b}},
            'bulanan': bulanan
        }}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# =================================================================================
# === MODUL REALISASI ANGGARAN (RAB) ==============================================
# =================================================================================

@api_akuntansi_laporan_bp.route('/api/realisasi_anggaran', methods=['GET'])
def get_realisasi_anggaran():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    bulan = request.args.get('bulan', datetime.now().strftime('%Y-%m'))
    cabang = session.get('cabang', 'GAS')
    try:
        safe_migrate_cabang(cursor)
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

@api_akuntansi_laporan_bp.route('/api/update_anggaran', methods=['POST'])
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

# === API: PENGELUARAN & ASET ===
@api_akuntansi_laporan_bp.route('/api/coa/dropdown', methods=['GET'])
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

@api_akuntansi_laporan_bp.route('/api/coa_all', methods=['GET'])
def get_all_coa():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT account_code, account_name FROM coa ORDER BY account_code ASC")
        return jsonify({'status': 'success', 'data': cursor.fetchall()})
    finally:
        cursor.close(); conn.close()

@api_akuntansi_laporan_bp.route('/api/expenses', methods=['POST'])
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
        safe_migrate_cabang(cursor)
        tanggal = data.get('tanggal')
        sumber_dana = data.get('coa_sumber_dana_id')
        beban_id = data.get('coa_beban_id')
        nominal = parse_float(data.get('nominal'), 'Nominal')
        keterangan = data.get('keterangan', '')
        cabang = session.get('cabang', 'GAS')
        cursor.execute("INSERT INTO pengeluaran_operasional (tanggal, coa_sumber_dana_id, coa_beban_id, nominal, keterangan, cabang) VALUES (%s, %s, %s, %s, %s, %s)", (tanggal, sumber_dana, beban_id, nominal, keterangan, cabang))
        
        query_jurnal = "INSERT INTO jurnal_umum (tanggal, coa_id, keterangan, debit, kredit, cabang) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(query_jurnal, (tanggal, beban_id, f"Beban Operasional: {keterangan}", nominal, 0, cabang))
        cursor.execute(query_jurnal, (tanggal, sumber_dana, f"Kas Keluar Operasional: {keterangan}", 0, nominal, cabang))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Berhasil dicatat!'}), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_akuntansi_laporan_bp.route('/api/aset', methods=['GET', 'POST', 'PUT'])
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
            cursor.execute("INSERT INTO aset_operasional (nama_aset, lokasi_cabang, tanggal_perolehan, nilai_aset, kondisi, keterangan) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (data.get('nama_aset'), cabang, data.get('tanggal_perolehan'), parse_float(data.get('nilai_aset'), 'Nilai'), data.get('kondisi'), data.get('keterangan', '')))
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

# === API: ARUS KAS ===
@api_akuntansi_laporan_bp.route('/api/arus_kas', methods=['GET'])
def get_arus_kas():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        safe_migrate_cabang(cursor)
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

# === API: MONITORING & LAPORAN HARIAN ===
@api_akuntansi_laporan_bp.route('/api/monitoring_pinjaman', methods=['GET'])
def monitoring_pinjaman_api():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
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
            
        query = """
            SELECT i.no_anggota, i.nama_anggota, i.pt_instansi, i.status_karyawan, i.akhir_bekerja, i.email, i.password, i.no_jmo, i.no_telp, i.nik_ktp, i.status_jmo, i.kol,
                a.tgl_penggajian, a.jatuh_tempo, a.tgl_bayar, a.edc, a.jenis_pinjaman, a.tgl_pencairan, a.besar_pinjaman, a.tenor, a.bunga_persen, a.angsuran_ke, a.status as status_pembayaran,
                a.tagihan_pokok, a.tagihan_margin, a.tagihan_denda, a.angsuran_pokok, a.angsuran_margin, a.angsuran_denda, a.tunggakan_pokok, a.tunggakan_margin, a.od_hari, a.tunggakan_denda, s.simpanan_wajib
            FROM identitas i INNER JOIN (
                SELECT * FROM (
                    SELECT no_anggota, tgl_penggajian, jatuh_tempo, tgl_bayar, edc, jenis_pinjaman, tgl_pencairan, besar_pinjaman, tenor, bunga_persen, angsuran_ke, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda, ROW_NUMBER() OVER (PARTITION BY no_anggota ORDER BY jatuh_tempo ASC) as rn
                    FROM (
                        SELECT no_anggota, tgl_penggajian, jatuh_tempo, tgl_bayar, edc, jenis_pinjaman, tgl_pencairan, besar_pinjaman, tenor, bunga_persen, angsuran_ke, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                        UNION ALL SELECT no_anggota, NULL as tgl_penggajian, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, edc, jenis_dana_urgent as jenis_pinjaman, tgl_pencairan, tagihan_pokok as besar_pinjaman, 1 as tenor, 0 as bunga_persen, 1 as angsuran_ke, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, tunggakan_pokok, tunggakan_margin, od_hari, tunggakan_denda FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
                    ) sub_union ) sub_rn WHERE rn = 1
            ) a ON i.no_anggota = a.no_anggota LEFT JOIN simpanan s ON i.no_anggota = s.nomor_anggota WHERE i.cabang = %s ORDER BY a.jatuh_tempo ASC
        """
        cursor.execute(query, (cabang,))
        data = cursor.fetchall()
        today = datetime.now().date()
        
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
        
        for d in data:
            if d['jatuh_tempo'] and d.get('status_pembayaran') == 'BELUM BAYAR':
                jt_date = datetime.strptime(str(d['jatuh_tempo']), '%Y-%m-%d').date() if isinstance(d['jatuh_tempo'], str) else d['jatuh_tempo']
                od = max((today - jt_date).days, 0)
                d['od_hari'] = od
                d['tunggakan_denda'] = ((float(d['tagihan_pokok'] or 0) + float(d['tagihan_margin'] or 0)) * 0.05 * od) if denda_aktif else 0
            else:
                d['od_hari'], d['tunggakan_denda'] = 0, 0
            for key, val in d.items():
                if hasattr(val, 'isoformat') and val is not None: d[key] = str(val)
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

# === API: CETAK LAPORAN HARIAN PDF ===
@api_akuntansi_laporan_bp.route('/api/cetak_laporan_harian_pdf', methods=['GET'])
def cetak_laporan_harian_pdf():
    try:
        from fpdf import FPDF
    except ImportError:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
    
    tanggal = request.args.get('tanggal', datetime.now().strftime('%Y-%m-%d'))
    cabang = session.get('cabang', 'GAS')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
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
            WHERE DATE(j.tanggal) = %s AND j.cabang = %s AND (c.account_code LIKE '11%%' OR c.kategori = 'KAS')
        """, (tanggal, cabang))
        cashflow = cursor.fetchall()
        
        query_macet = """
            SELECT a.no_anggota, i.nama_anggota, a.jatuh_tempo, 
                   (a.tagihan_pokok + a.tagihan_margin) as tagihan
            FROM (
                SELECT no_anggota, jatuh_tempo, tagihan_pokok, tagihan_margin
                FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT no_anggota, tanggal_jatuh_tempo as jatuh_tempo, tagihan_pokok, tagihan_margin
                FROM angsuran_dana_urgent WHERE status = 'BELUM BAYAR'
            ) a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE DATE(a.jatuh_tempo) < %s AND i.cabang = %s
        """
        cursor.execute(query_macet, (tanggal, cabang))
        data_macet = cursor.fetchall()
    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        class PDF(FPDF):
            def header(self):
                self.set_font('Arial', 'B', 14)
                self.cell(0, 8, f"LAPORAN HARIAN OPERASIONAL CABANG {str(cabang).upper()}", ln=True, align='C')
                self.set_font('Arial', '', 10)
                try: tgl_obj = datetime.strptime(tanggal, '%Y-%m-%d')
                except: tgl_obj = datetime.now()
                self.cell(0, 6, f"Periode Tanggal: {tgl_obj.strftime('%d-%m-%Y')}", ln=True, align='C')
                self.ln(5)

        pdf = PDF('P', 'mm', 'A4')
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        def f_rp(val): return f"Rp {val:,.0f}".replace(',', '.') if val else 'Rp 0'

        # 1. Pencairan
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 8, "1. Rincian Pencairan", ln=True)
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(200, 200, 200)
        w = [25, 55, 40, 35, 35]
        pdf.cell(w[0], 6, "No Anggota", 1, 0, 'C', True)
        pdf.cell(w[1], 6, "Nama Anggota", 1, 0, 'C', True)
        pdf.cell(w[2], 6, "Jenis Pinjaman", 1, 0, 'C', True)
        pdf.cell(w[3], 6, "Nominal Plafon", 1, 0, 'C', True)
        pdf.cell(w[4], 6, "Terima Bersih", 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        if not pencairan:
            pdf.cell(sum(w), 6, "Tidak ada data pencairan.", 1, 1, 'C')
        else:
            for row in pencairan:
                pdf.cell(w[0], 6, str(row['no_anggota']), 1, 0, 'C')
                pdf.cell(w[1], 6, str(row['nama_anggota'])[:30], 1, 0, 'L')
                pdf.cell(w[2], 6, str(row['jenis'])[:20], 1, 0, 'C')
                pdf.cell(w[3], 6, f_rp(float(row['nominal'] or 0)), 1, 0, 'R')
                pdf.cell(w[4], 6, f_rp(float(row['terima_bersih'] or 0)), 1, 1, 'R')
        pdf.ln(5)

        # 2. Angsuran
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 8, "2. Tagihan Jatuh Tempo (Kolektibilitas Hari Ini)", ln=True)
        pdf.set_font('Arial', 'B', 9)
        w2 = [25, 45, 35, 20, 35, 30]
        pdf.cell(w2[0], 6, "No Anggota", 1, 0, 'C', True)
        pdf.cell(w2[1], 6, "Nama Anggota", 1, 0, 'C', True)
        pdf.cell(w2[2], 6, "Jenis Pinjaman", 1, 0, 'C', True)
        pdf.cell(w2[3], 6, "Angsuran", 1, 0, 'C', True)
        pdf.cell(w2[4], 6, "Total Tagihan", 1, 0, 'C', True)
        pdf.cell(w2[5], 6, "Status", 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        if not angsuran:
            pdf.cell(sum(w2), 6, "Tidak ada tagihan jatuh tempo hari ini.", 1, 1, 'C')
        else:
            for row in angsuran:
                pdf.cell(w2[0], 6, str(row['no_anggota']), 1, 0, 'C')
                pdf.cell(w2[1], 6, str(row['nama_anggota'])[:20], 1, 0, 'L')
                pdf.cell(w2[2], 6, str(row['jenis'])[:15], 1, 0, 'C')
                pdf.cell(w2[3], 6, str(row['angsuran_ke']), 1, 0, 'C')
                pdf.cell(w2[4], 6, f_rp(float(row['total_tagihan'] or 0)), 1, 0, 'R')
                pdf.cell(w2[5], 6, str(row['status'])[:15], 1, 1, 'C')
        pdf.ln(5)

        # 3. Arus Kas
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 8, "3. Arus Kas (Cash Flow)", ln=True)
        pdf.set_font('Arial', 'B', 9)
        w3 = [40, 90, 30, 30]
        pdf.cell(w3[0], 6, "Akun Terlibat", 1, 0, 'C', True)
        pdf.cell(w3[1], 6, "Keterangan Transaksi", 1, 0, 'C', True)
        pdf.cell(w3[2], 6, "Masuk (Debit)", 1, 0, 'C', True)
        pdf.cell(w3[3], 6, "Keluar (Kredit)", 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        if not cashflow:
            pdf.cell(sum(w3), 6, "Tidak ada pergerakan kas.", 1, 1, 'C')
        else:
            for row in cashflow:
                pdf.cell(w3[0], 6, str(row['account_name'])[:20], 1, 0, 'L')
                pdf.cell(w3[1], 6, str(row['keterangan'])[:45], 1, 0, 'L')
                km = float(row['kas_masuk'] or 0)
                kk = float(row['kas_keluar'] or 0)
                pdf.cell(w3[2], 6, f_rp(km) if km > 0 else "-", 1, 0, 'R')
                pdf.cell(w3[3], 6, f_rp(kk) if kk > 0 else "-", 1, 1, 'R')
        pdf.ln(5)

        # 4. Macet Data processing
        target_date = datetime.strptime(tanggal, '%Y-%m-%d').date()
        macet_dict = {}
        for row in data_macet:
            jt = row['jatuh_tempo']
            if not jt: continue
            if isinstance(jt, str): jt = datetime.strptime(jt, '%Y-%m-%d').date()
            od_hari = (target_date - jt).days
            na = row['no_anggota']
            
            if na not in macet_dict:
                row['od_hari'] = od_hari
                row['tagihan'] = float(row['tagihan'] or 0)
                macet_dict[na] = row
            else:
                if od_hari > macet_dict[na]['od_hari']:
                    macet_dict[na]['od_hari'] = od_hari
                macet_dict[na]['tagihan'] += float(row['tagihan'] or 0)

        macet_1_6 = sorted([v for v in macet_dict.values() if 1 <= v['od_hari'] <= 180], key=lambda x: x['od_hari'], reverse=True)
        macet_lebih_6 = sorted([v for v in macet_dict.values() if v['od_hari'] > 180], key=lambda x: x['od_hari'], reverse=True)

        def render_macet_table(title, data_macet_list):
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 8, title, ln=True)
            pdf.set_font('Arial', 'B', 9)
            w4 = [30, 80, 40, 40]
            pdf.cell(w4[0], 6, "No Anggota", 1, 0, 'C', True)
            pdf.cell(w4[1], 6, "Nama Anggota", 1, 0, 'C', True)
            pdf.cell(w4[2], 6, "OD Hari", 1, 0, 'C', True)
            pdf.cell(w4[3], 6, "Sisa Tagihan", 1, 1, 'C', True)
            
            pdf.set_font('Arial', '', 9)
            if not data_macet_list:
                pdf.cell(sum(w4), 6, "Tidak ada anggota macet dalam kategori ini.", 1, 1, 'C')
            else:
                for row in data_macet_list:
                    pdf.cell(w4[0], 6, str(row['no_anggota']), 1, 0, 'C')
                    pdf.cell(w4[1], 6, str(row['nama_anggota'])[:40], 1, 0, 'L')
                    pdf.cell(w4[2], 6, f"{row['od_hari']} hari", 1, 0, 'C')
                    pdf.cell(w4[3], 6, f_rp(row['tagihan']), 1, 1, 'R')
            pdf.ln(5)

        render_macet_table("4. Anggota Macet (1 - 6 Bulan)", macet_1_6)
        render_macet_table("5. Anggota Macet (> 6 Bulan)", macet_lebih_6)

        file_path = os.path.join(tempfile.gettempdir(), f"Laporan_Harian_{tanggal}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_akuntansi_laporan_bp.route('/api/laporan_harian', methods=['GET'])
def get_laporan_harian():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    tanggal = request.args.get('tanggal', datetime.now().strftime('%Y-%m-%d'))
    cabang = session.get('cabang', 'GAS')
    try:
        cursor.execute("CREATE TABLE IF NOT EXISTS penanganan_macet (no_anggota VARCHAR(50) PRIMARY KEY, progres_marketing TEXT, solusi TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        
        # Auto-migrate: Tambahkan kolom cabang untuk mendukung multi-cabang jika belum ada
        try:
            cursor.execute("ALTER TABLE jurnal_umum ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
        except: pass
        
        try:
            cursor.execute("ALTER TABLE pengeluaran_operasional ADD COLUMN cabang VARCHAR(50) DEFAULT 'GAS'")
        except: pass
        
        conn.commit()
        
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
            WHERE DATE(j.tanggal) = %s AND j.cabang = %s AND (c.account_code LIKE '11%%' OR c.kategori = 'KAS')
        """, (tanggal, cabang))
        cashflow = cursor.fetchall()

        query_macet = """
            SELECT a.no_anggota, i.nama_anggota, a.jenis_pinjaman, a.jatuh_tempo, 
                   (a.tagihan_pokok + a.tagihan_margin) as tagihan,
                   p.progres_marketing, p.solusi
            FROM (
                SELECT no_anggota, jenis_pinjaman, jatuh_tempo, tagihan_pokok, tagihan_margin
                FROM angsuran_multiguna_tempo WHERE status = 'BELUM BAYAR'
                UNION ALL
                SELECT no_anggota, jenis_dana_urgent as jenis_pinjaman, tanggal_jatuh_tempo as jatuh_tempo, tagihan_pokok, tagihan_margin
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
            if isinstance(jt, str): jt = datetime.strptime(jt, '%Y-%m-%d').date()
            
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

@api_akuntansi_laporan_bp.route('/api/update_penanganan_macet', methods=['POST'])
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