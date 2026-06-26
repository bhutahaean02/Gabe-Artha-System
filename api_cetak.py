from flask import Blueprint, request, jsonify, session, send_file
from datetime import datetime
import os
import json
import tempfile

from db import get_db_connection
from api_helpers import terbilang, hitung_denda_keterlambatan

api_cetak_bp = Blueprint('api_cetak', __name__)

def get_logo_path():
    # This function should return the path to your company's logo
    # A good default location is in the 'static/img' folder
    logo_path = os.path.join(os.getcwd(), 'static', 'img', 'logo.png')
    if os.path.exists(logo_path):
        return logo_path
    return None

def get_alamat_cabang(cabang_nama):
    cabang_upper = str(cabang_nama).upper() if cabang_nama else ""
    if 'TAMBAK' in cabang_upper:
        return "Jalan Raya Serang KM. 68. Kp. Gorda RT/RW : 006/005 Kel. Tambak, Kec. Kebin Kab. Serang Prov. Banten"
    return "Jl. Raya Pasar Kemis - Rajeg. Kp. Putat RT/RW 005/001 Ds. Sindang Panon Kec. Sindang Jaya - Tangerang"

def get_config_cabang(cabang_nama):
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_cabang.json')
    default_config = {"kota": "Tangerang", "manager": "N.SRI UTAMI"}
    if not os.path.exists(config_path):
        return default_config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except:
        return default_config
    cabang_upper = str(cabang_nama).upper() if cabang_nama else ""
    for key, val in config.items():
        if key != 'DEFAULT' and key in cabang_upper:
            return val
    return config.get('DEFAULT', default_config)

# =================================================================================
# === KELAS PDF DASAR DENGAN HEADER & WATERMARK OTOMATIS ==========================
# =================================================================================

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

class PDF(FPDF):
    def __init__(self, orientation='P', unit='mm', format='A4', cabang='GAS'):
        if FPDF is None:
            raise ImportError("FPDF library not found. Please install it with: pip install fpdf")
        super().__init__(orientation, unit, format)
        self.cabang_nama = str(cabang).upper()
        self.title_doc = ""
        self.periode_doc = ""

    def set_document_title(self, title, periode=""):
        self.title_doc = title
        self.periode_doc = periode

    def header(self):
        logo_path = get_logo_path()
        if logo_path:
            self.image(logo_path, x=12, y=10, w=18)
        
        self.set_y(10)
        self.set_left_margin(32)
        self.set_font("Arial", 'B', 16); self.cell(0, 6, txt="KSP GABE ARTHA NAULI", ln=True, align='C')
        self.set_font("Arial", 'B', 11); self.cell(0, 5, txt=f"GABE ARTHA NAULI CABANG : {self.cabang_nama}", ln=True, align='C')
        self.set_font("Arial", '', 9); self.cell(0, 4, txt="Badan Hukum : AHU.0002217.AH.01.26 TAHUN 2020", ln=True, align='C')
        alamat_cabang = get_alamat_cabang(self.cabang_nama)
        self.set_font("Arial", 'I', 9); self.cell(0, 4, txt=alamat_cabang, ln=True, align='C')
        
        self.set_left_margin(12)
        self.ln(2); self.line(12, self.get_y(), self.w - 12, self.get_y()); self.line(12, self.get_y()+0.6, self.w - 12, self.get_y()+0.6); self.ln(3)

        if self.title_doc:
            self.set_font('Arial', 'B', 12); self.cell(0, 6, self.title_doc, ln=True, align='C')
        if self.periode_doc:
            self.set_font('Arial', '', 10); self.cell(0, 5, self.periode_doc, ln=True, align='C')
        self.ln(2)

    def add_watermark(self):
        logo_path = get_logo_path()
        if not logo_path: return
        try:
            self.set_alpha(0.15)
            img_w = 100
            img_x = (self.w - img_w) / 2
            img_y = (self.h - img_w) / 2
            self.image(logo_path, x=img_x, y=img_y, w=img_w)
            self.set_alpha(1.0)
        except AttributeError:
            self.set_font("Arial", 'B', 45)
            self.set_text_color(235, 235, 235)
            self.text(20, 150, "GABE ARTHA NAULI")
            self.set_text_color(0, 0, 0)

# =================================================================================
# === MODUL CETAK STRUK & DOKUMEN =================================================
# =================================================================================

def _get_data_tagihan_for_struk(cursor, jenis, id_tagihan):
    """Helper function to fetch invoice data from the database."""
    if jenis == 'utama':
        query = """
            SELECT a.*, i.pt_instansi, i.cabang, i.nama_anggota as nama_anggota_terkini, p.id as id_pencairan, a.jenis_pinjaman as jenis_pinjaman_final
            FROM angsuran_multiguna_tempo a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            LEFT JOIN pencairan_multiguna_tempo p ON a.no_anggota = p.no_anggota AND a.tgl_pencairan = p.tanggal_cair
            WHERE a.id = %s LIMIT 1
        """
    else: # urgent
        query = """
            SELECT a.*, i.pt_instansi, i.cabang, i.nama_anggota as nama_anggota_terkini, p.id as id_pencairan, a.jenis_dana_urgent as jenis_pinjaman_final
            FROM angsuran_dana_urgent a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            LEFT JOIN pencairan_dana_urgent p ON a.no_anggota = p.no_anggota AND a.tgl_pencairan = p.tanggal_pencairan_dana_urgent
            WHERE a.id = %s LIMIT 1
        """
    cursor.execute(query, (id_tagihan,))
    return cursor.fetchone()

@api_cetak_bp.route('/api/cetak_struk/<jenis>/<id_tagihan>', methods=['GET'])
def cetak_struk(jenis, id_tagihan):
    if not jenis or not id_tagihan:
        return "<h3>Error: Parameter cetak tidak lengkap!</h3>", 400
    if FPDF is None:
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
        gaji_awal_val = 0
        sisa_gaji_val = 0
        edc = "-"
        tgl_str = "(Otomatis Tgl Bayar)"
        def f_rp(val): return "(Otomatis Nominal)"
        terbilang_text = "* (otomatis terbilang rupiah) *"
        cabang_nama = "(OTOMATIS CABANG)"
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            data = _get_data_tagihan_for_struk(cursor, jenis, id_tagihan)
            if not data: return f"<h3>Error: Data tagihan tidak ditemukan!</h3>", 404
            
            jenis_pinjaman = data.get('jenis_pinjaman_final') if data else ''
            cabang_nama = str(data.get('cabang') or session.get('cabang', 'GAS')).upper()
    
            nama = data.get('nama_anggota_terkini') or data.get('nama_anggota')
            no_anggota = data['no_anggota']
            no_kontrak = f"104.{data['id_pencairan']:07d}" if data.get('id_pencairan') else "-"
            instansi = data.get('pt_instansi') or "-"
            
            angsuran_ke = data.get('angsuran_ke', 1)
            tenor = data.get('tenor', 1)
            sisa_angsuran = max(0, tenor - angsuran_ke)
            
            pokok = float(data.get('angsuran_pokok') or 0)
            margin = float(data.get('angsuran_margin') or 0)
            denda = float(data.get('angsuran_denda') or 0)
            gaji_awal_val = float(data.get('gaji_awal') or 0)
            sisa_gaji_val = float(data.get('sisa_gaji') or 0)
            edc = data.get('edc') or "-"
            try:
                edc_num = float(edc)
            except (ValueError, TypeError):
                edc_num = 0
            edc_str_view = f"Rp {edc_num:,.0f}".replace(',', '.') if edc_num > 0 else "-"
            
            tgl_bayar_obj = data.get('tgl_bayar')
            if isinstance(tgl_bayar_obj, str):
                try: tgl_bayar_obj = datetime.strptime(tgl_bayar_obj, '%Y-%m-%d').date()
                except: tgl_bayar_obj = datetime.now().date()
            if not tgl_bayar_obj: tgl_bayar_obj = datetime.now().date()
            
            # Mengambil data simpanan wajib langsung dari tabel angsuran, bukan dari jurnal
            simpanan_wajib_val = float(data.get('simpanan_wajib_bayar') or 0)
            total = pokok + margin + denda + edc_num + simpanan_wajib_val
            
            months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
            tgl_str = f"{tgl_bayar_obj.day} {months[tgl_bayar_obj.month]} {tgl_bayar_obj.year}"
            
            def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
            terbilang_text = f"* {terbilang(total).lower()} rupiah *"
        except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()

    try:
        pdf = PDF(orientation='L', format='A5', cabang=cabang_nama)
        pdf.set_document_title("BUKTI ANGSURAN", "SLIP PEMBAYARAN ANGGOTA")
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=5)
        
        w1, w2, w3, w4 = 30, 3, 100, 40
        def print_row(l1, v1):
            pdf.cell(w1, 4.5, txt=l1); pdf.cell(w2, 4.5, txt=":"); pdf.cell(w3, 4.5, txt=str(v1)); pdf.ln(4.5)

        pdf.cell(w1, 4.5, "Jenis Transaksi"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"ANGSURAN KE - {angsuran_ke}    SISA : {sisa_angsuran}")
        pdf.cell(w4, 4.5, "Sisa Gaji di ATM", ln=True)
        pdf.cell(w1, 4.5, "Nama Anggota"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, nama)
        if jenis == 'TEMPLATE': pdf.cell(w4, 4.5, "Rp. (Otomatis)", ln=True)
        else: pdf.cell(w4, 4.5, f"Rp. {f_rp(sisa_gaji_val)}" if sisa_gaji_val > 0 else "-", ln=True)

        print_row("Kode Anggota", no_anggota)
        print_row("No Kontrak", no_kontrak)
        
        pdf.cell(w1, 4.5, "Gaji Awal"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"Rp {f_rp(gaji_awal_val)}" if jenis != 'TEMPLATE' else "(Otomatis)")
        pdf.cell(w4, 4.5, "", ln=True)
        
        print_row("Instansi", instansi)
        
        pdf.cell(w1, 4.5, "Jenis Pinjaman"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, jenis_pinjaman)
        pdf.cell(w4, 4.5, "Kurang Bayar", ln=True)
        pdf.cell(w1, 4.5, "Angsuran"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"Rp {f_rp(pokok+margin)}" if jenis != 'TEMPLATE' else "(Otomatis)")
        pdf.cell(w4, 4.5, "-", ln=True)
        
        print_row("Biaya EDC", edc_str_view)
        print_row("Simpanan Wajib", f"Rp {f_rp(simpanan_wajib_val)}" if simpanan_wajib_val > 0 and jenis != 'TEMPLATE' else ("-" if jenis != 'TEMPLATE' else "(Otomatis)"))
        print_row("Admin", "-")
        print_row("Biaya Denda", f"Rp {f_rp(denda)}" if denda > 0 and jenis != 'TEMPLATE' else ("-" if jenis != 'TEMPLATE' else "(Otomatis)"))
        print_row("Jumlah Bayar", f"Rp {f_rp(total)}" if jenis != 'TEMPLATE' else "(Otomatis)")
        print_row("Terbilang", terbilang_text)
        
        config_cabang = get_config_cabang(cabang_nama)
        kota_cabang = config_cabang.get('kota', 'Tangerang')
        manager_nama = config_cabang.get('manager', 'N.SRI UTAMI')

        pdf.ln(3)
        pdf.cell(90, 4.5, "Yang menyetor", align='C')
        pdf.cell(100, 4.5, f"{kota_cabang}, {tgl_str}", align='C', ln=True)
        pdf.cell(90, 4.5, "", align='C')
        pdf.cell(100, 4.5, "MANAGER", align='C', ln=True)
        pdf.ln(12)
        
        pdf.set_font("Arial", 'U', 9)
        pdf.cell(90, 4.5, nama, align='C')
        pdf.cell(100, 4.5, manager_nama, align='C', ln=True)
        
        pdf.set_font("Arial", '', 7)
        pdf.ln(3)
        pdf.cell(0, 4, "-- SIMPANLAH BUKTI PEMBAYARAN INI SEBAGAI BUKTI TRANSAKSI ANDA --", align='C', ln=True)

        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"Struk_{jenis}_{id_tagihan}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_akad/', defaults={'no_anggota': None, 'tgl_pencairan': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_akad/<no_anggota>/<tgl_pencairan>', methods=['GET'], endpoint='api_cetak_akad_baru')
def cetak_akad(no_anggota, tgl_pencairan):
    if not no_anggota or not tgl_pencairan:
        return "<h3>Error: Parameter cetak akad tidak lengkap!</h3>", 400
    if FPDF is None:
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
        pdf = PDF(cabang=cabang_nama)
        pdf.add_page()
        pdf.set_margins(12, 10, 12)
        pdf.set_auto_page_break(auto=True, margin=10)
        
        pdf.add_watermark()

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
        alamat_cabang = get_alamat_cabang(cabang_nama)
        pdf.multi_cell(0, 4.5, txt=f"Pimpinan KSP GABE ARTHA NAULI, dalam hal ini bertindak untuk dan atas nama KSP GABE ARTHA NAULI, yang beralamat di {alamat_cabang}.")
        pdf.ln(2); pdf.cell(0, 4.5, txt="Selanjutnya disebut sebagai Pihak ke 2 (dua) (KSP GABE ARTHA NAULI).", ln=True); pdf.ln(2)
        pdf.cell(0, 4.5, txt="Kedua belah pihak telah sepakat dengan perjanjian sebagai berikut:", ln=True); pdf.ln(1)
        
        for i, text in enumerate(terms, 1):
            pdf.set_left_margin(17); pdf.set_x(12)
            pdf.cell(5, 4.5, txt=f"{i}.", ln=False)
            pdf.multi_cell(0, 4.5, txt=str(text).replace('\r', ''))
            pdf.set_left_margin(12); pdf.ln(0.5)
            
        pdf.ln(2); pdf.multi_cell(0, 4.5, txt="Demikian surat perjanjian ini dibuat dengan pikiran tenang, sehat jasmani dan rohani tanpa ada unsur paksaan dari pihak manapun.")
        
        if pdf.get_y() > 255: pdf.add_page()
        
        config_cabang = get_config_cabang(cabang_nama)
        kota_cabang = config_cabang.get('kota', 'Tangerang')
        manager_nama = config_cabang.get('manager', 'N.SRI UTAMI')

        pdf.ln(5)
        pdf.cell(85, 4.5, txt="PIHAK KEDUA", ln=False, align='C'); pdf.cell(90, 4.5, txt=f"{kota_cabang}, {tgl_str}", ln=True, align='C')
        pdf.cell(85, 4.5, txt="KSP GABE ARTHA NAULI", ln=False, align='C'); pdf.cell(90, 4.5, txt="PIHAK PERTAMA", ln=True, align='C')
        pdf.ln(16)
        pdf.cell(85, 4.5, txt=f"( {manager_nama} )", ln=False, align='C'); pdf.set_font("Arial", 'BU', 9); pdf.cell(90, 4.5, txt=f"{nama}", ln=True, align='C')

        file_path = os.path.join(tempfile.gettempdir(), f"Akad_Pinjaman_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan Internal Saat Menggambar PDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_pernyataan/', defaults={'no_anggota': None, 'tgl_pencairan': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_pernyataan/<no_anggota>/<tgl_pencairan>', methods=['GET'], endpoint='api_cetak_pernyataan_baru')
def cetak_pernyataan(no_anggota, tgl_pencairan):
    if not no_anggota or not tgl_pencairan:
        return "<h3>Error: Parameter cetak pernyataan tidak lengkap!</h3>", 400
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

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
        pdf = PDF(cabang=cabang_nama)
        pdf.set_document_title("SURAT PERNYATAAN PINJAMAN ANGGOTA")
        pdf.add_page()
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_watermark()
        
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
        
        alamat_cabang = get_alamat_cabang(cabang_nama)
        terms = [
            f"Saya secara benar dan Sadar telah meminjam uang sebesar Rp. {besar_pinjaman_rp} dengan jangka waktu {tenor} Bulan kepada pihak Koperasi Simpan Pinjam KSP GABE ARTHA NAULI. Pinjaman tersebut adalah benar atas pinjaman atas nama saya sendiri tanpa ada unsur paksaan, Pembagian hasil pinjaman, tarikan patokan fee oleh pihak ke-tiga atau tanpa pihak manapun.",
            f"Saya selaku Nasabah KSP GABE ARTHA NAULI telah menerima uang sebagai pinjaman, adapun angsuran nya di ambil dari Rekening Buku Tabungan Bank {bank} Dengan No Rekening {no_rek} Nomor ATM ..............................",
            "Saya berjanji tidak akan memblokir rekening, mengganti rekening, mengalihkan gaji, dan tidak akan mempergunakan fasilitas M-banking, Sms Banking, I-Banking dari rekening gaji, dan tidak akan membuat kembali buku tabungan yang telah saya jaminkan di KSP GABE ARTHA NAULI.",
            f"Dan apabila gaji saya suatu saat nanti turun ke Bank lain maka saya akan mengantarkan langsung ke kantor KSP GABE ARTHA NAULI CABANG {cabang_nama} yang beralamat di {alamat_cabang} tanpa harus disusul atau dijemput."
        ]
        
        for i, text in enumerate(terms, 1):
            pdf.set_left_margin(22); pdf.set_x(15)
            pdf.cell(7, 6, txt=f"{i}.", ln=False)
            pdf.multi_cell(0, 6, txt=text)
            pdf.set_left_margin(15); pdf.ln(2)
            
        pdf.ln(3)
        pdf.multi_cell(0, 6, txt="Demikian Surat Pernyataan ini saya buat dalam keadaan sehat jasmani dan rohani tanpa ada unsur paksaan dari pihak manapun, dan apabila saya melanggar surat pernyataan ini maka saya bersedia di tuntut melalui jalur hukum yang berlaku di Negara Republik Indonesia.")
        
        config_cabang = get_config_cabang(cabang_nama)
        kota_cabang = config_cabang.get('kota', 'Tangerang')
        
        pdf.ln(15)
        pdf.cell(100, 6, txt="", ln=False)
        pdf.cell(90, 6, txt=f"{kota_cabang}, {tgl_str}", ln=True, align='C')
        pdf.ln(25)
        pdf.cell(100, 6, txt="", ln=False)
        pdf.set_font("Arial", 'U', 10)
        pdf.cell(90, 6, txt=f"{nama}", ln=True, align='C')

        file_path = os.path.join(tempfile.gettempdir(), f"Pernyataan_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_pelunasan/', defaults={'no_anggota': None, 'tanggal_bayar': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_pelunasan/<no_anggota>/<tanggal_bayar>', methods=['GET'])
def cetak_pelunasan(no_anggota, tanggal_bayar):
    if not no_anggota or not tanggal_bayar:
        return "<h3>Error: Parameter cetak pelunasan tidak lengkap!</h3>", 400
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM identitas WHERE no_anggota = %s", (no_anggota,))
        anggota = cursor.fetchone()
        if not anggota: return "<h3>Error: Anggota tidak ditemukan.</h3>", 404
            
        nama = anggota['nama_anggota']
        cabang_nama = str(anggota.get('cabang') or session.get('cabang', 'GAS')).upper()
        
        instansi = anggota['pt_instansi'] or "-"
        
        cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, edc FROM angsuran_multiguna_tempo WHERE no_anggota = %s AND tgl_bayar = %s AND status = 'LUNAS'", (no_anggota, tanggal_bayar))
        mg_rows = cursor.fetchall()
        
        cursor.execute("SELECT angsuran_pokok, angsuran_margin, angsuran_denda, edc FROM angsuran_dana_urgent WHERE no_anggota = %s AND tgl_bayar = %s AND status = 'LUNAS'", (no_anggota, tanggal_bayar))
        urg_rows = cursor.fetchall()
        
        mg_pokok = sum(float(r['angsuran_pokok'] or 0) for r in mg_rows)
        mg_margin = sum(float(r['angsuran_margin'] or 0) for r in mg_rows)
        mg_denda = sum(float(r['angsuran_denda'] or 0) for r in mg_rows)
        mg_edc = sum(float(r['edc'] or 0) for r in mg_rows)

        urg_pokok = sum(float(r['angsuran_pokok'] or 0) for r in urg_rows)
        urg_margin = sum(float(r['angsuran_margin'] or 0) for r in urg_rows)
        urg_denda = sum(float(r['angsuran_denda'] or 0) for r in urg_rows)
        urg_edc = sum(float(r['edc'] or 0) for r in urg_rows)
            
        total_pokok = mg_pokok + urg_pokok
        total_margin = mg_margin + urg_margin
        total_denda = mg_denda + urg_denda
        total_edc = mg_edc + urg_edc
        
        grand_total = total_pokok + total_margin + total_denda + total_edc
        if grand_total <= 0: return "<h3>Error: Tidak ada data pelunasan pada tanggal tersebut.</h3>", 404
            
        try: tgl_bayar_obj = datetime.strptime(tanggal_bayar[:10], '%Y-%m-%d').date()
        except: tgl_bayar_obj = datetime.now().date()
            
        months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
        tgl_str = f"{tgl_bayar_obj.day} {months[tgl_bayar_obj.month]} {tgl_bayar_obj.year}"
        
        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
        terbilang_text = f"* {terbilang(grand_total).lower()} rupiah *"
    except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally: cursor.close(); conn.close()

    try:
        pdf = PDF(orientation='L', format='A5', cabang=cabang_nama)
        pdf.set_document_title("BUKTI PELUNASAN PINJAMAN", "SLIP PELUNASAN KESELURUHAN (DIPERCEPAT)")
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=5)
        
        w1, w2, w3, w4 = 30, 3, 100, 40
        def print_row(l1, v1):
            pdf.cell(w1, 4.5, txt=l1); pdf.cell(w2, 4.5, txt=":"); pdf.cell(w3, 4.5, txt=str(v1)); pdf.ln(4.5)

        pdf.cell(w1, 4.5, "Kode Anggota"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, no_anggota); pdf.cell(w4, 4.5, "Rincian Pelunasan", ln=True)
        pdf.cell(w1, 4.5, "Nama Anggota"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, nama); pdf.cell(w4, 4.5, f"Pokok : Rp {f_rp(total_pokok)}", ln=True)
        pdf.cell(w1, 4.5, "Instansi"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, instansi); pdf.cell(w4, 4.5, f"Margin : Rp {f_rp(total_margin)}", ln=True)
        pdf.cell(w1, 4.5, "Keterangan"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, "PELUNASAN DIPERCEPAT"); pdf.cell(w4, 4.5, f"Denda : Rp {f_rp(total_denda)}", ln=True)
        pdf.cell(w1, 4.5, "Total Tagihan"); pdf.cell(w2, 4.5, ":"); pdf.cell(w3, 4.5, f"Rp {f_rp(grand_total)}"); pdf.cell(w4, 4.5, f"EDC/Adm : Rp {f_rp(total_edc)}", ln=True)
        print_row("Terbilang", terbilang_text)
        
        config_cabang = get_config_cabang(cabang_nama)
        kota_cabang = config_cabang.get('kota', 'Tangerang')
        manager_nama = config_cabang.get('manager', 'N.SRI UTAMI')

        pdf.ln(5)
        pdf.cell(90, 4.5, "Yang Menyetor", align='C'); pdf.cell(100, 4.5, f"{kota_cabang}, {tgl_str}", align='C', ln=True)
        pdf.cell(90, 4.5, "", align='C'); pdf.cell(100, 4.5, "KASIR / MANAGER", align='C', ln=True)
        pdf.ln(12)
        
        pdf.set_font("Arial", 'U', 9)
        pdf.cell(90, 4.5, nama, align='C'); pdf.cell(100, 4.5, manager_nama.upper(), align='C', ln=True)
        pdf.set_font("Arial", '', 7); pdf.ln(3); pdf.cell(0, 4, "-- SIMPANLAH BUKTI INI SEBAGAI TANDA PELUNASAN YANG SAH --", align='C', ln=True)

        file_path = os.path.join(tempfile.gettempdir(), f"Pelunasan_{no_anggota}_{tanggal_bayar}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan Internal:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_setoran_berkas/', defaults={'no_anggota': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_setoran_berkas/<no_anggota>', methods=['GET'])
def cetak_setoran_berkas(no_anggota):
    if not no_anggota:
        return "<h3>Error: Nomor anggota tidak diberikan!</h3>", 400
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT no_anggota, nama_anggota, pt_instansi, berkas_jaminan, cabang FROM identitas WHERE no_anggota = %s", (no_anggota,))
        anggota = cursor.fetchone()
        if not anggota:
            return "<h3>Error: Anggota tidak ditemukan.</h3>", 404
            
        nama_anggota = anggota['nama_anggota']
        cabang_nama = str(anggota.get('cabang') or 'GAS').upper()
        pt_instansi = anggota.get('pt_instansi') or '-'
        
        berkas_jaminan = []
        if anggota.get('berkas_jaminan'):
            try:
                berkas_jaminan = json.loads(anggota['berkas_jaminan'])
            except:
                pass
                
        daftar_berkas = [
            "1. KTP Pinjaman", "2. KTP Penanggung jawab", "3. KTP Saudara", "4. Kartu Keluarga", 
            "5. Buku Tabungan", "6. Ijazah", "7. Kartu Jamsostek", "8. Akta Lahir", "9. Surat Kontrak", 
            "10. Rekening Koran", "11. Buku Nikah", "12. ID Card", "13. Surat Pengangkatan"
        ]
        
    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        pdf = PDF(orientation='L', format='A5', cabang=cabang_nama)
        pdf.set_document_title("TANDA TERIMA BERKAS JAMINAN")
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(auto=True, margin=10)
        
        tgl_str = datetime.now().strftime('%d-%m-%Y')
        
        pdf.set_font("Arial", '', 8)
        pdf.cell(20, 4, "No Anggota", ln=False); pdf.cell(3, 4, ":"); pdf.cell(80, 4, no_anggota, ln=False)
        pdf.cell(20, 4, "Tgl Terima", ln=False); pdf.cell(3, 4, ":"); pdf.cell(0, 4, tgl_str, ln=True)
        pdf.cell(20, 4, "Nama", ln=False); pdf.cell(3, 4, ":"); pdf.cell(80, 4, nama_anggota, ln=False)
        pdf.cell(20, 4, "Instansi", ln=False); pdf.cell(3, 4, ":"); pdf.cell(0, 4, pt_instansi, ln=True)
        pdf.ln(3)
        
        pdf.set_font("Arial", 'B', 8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(10, 5, "Ada", 1, 0, 'C', True)
        pdf.cell(60, 5, "Nama Jaminan", 1, 0, 'C', True)
        pdf.cell(30, 5, "Jenis", 1, 0, 'C', True)
        pdf.cell(0, 5, "Keterangan", 1, 1, 'C', True)
        
        pdf.set_font("Arial", '', 8)
        
        for item in daftar_berkas:
            found = next((b for b in berkas_jaminan if b['nama'] == item), None)
            
            ada = "V" if found else ""
            jenis = found['jenis'] if found else ""
            keterangan = found['keterangan'] if found else ""
            
            # Hilangkan angka di depan nama berkas untuk tampilan agar lebih rapi
            nama_tampil = item.split('. ', 1)[1] if '. ' in item else item
            
            pdf.cell(10, 5, ada, 1, 0, 'C')
            pdf.cell(60, 5, nama_tampil, 1, 0, 'L')
            pdf.cell(30, 5, jenis, 1, 0, 'C')
            pdf.cell(0, 5, keterangan[:50], 1, 1, 'L')
            
        pdf.ln(5)
        
        pdf.cell(95, 4, "Yang Menyerahkan,", align='C')
        pdf.cell(95, 4, "Diterima Oleh,", align='C', ln=True)
        pdf.ln(10)
        pdf.set_font("Arial", 'U', 8)
        config_cabang = get_config_cabang(cabang_nama)
        manager_nama = config_cabang.get('manager', 'N.SRI UTAMI')
        pdf.cell(95, 4, f"{nama_anggota}", align='C')
        pdf.cell(95, 4, f"{session.get('nama_lengkap', manager_nama).upper()}", align='C', ln=True)
        
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"Setoran_Berkas_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e:
        return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_rekening_koran/', defaults={'no_anggota': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_rekening_koran/<no_anggota>', methods=['GET'])
def cetak_rekening_koran(no_anggota):
    if not no_anggota:
        return "<h3>Error: Nomor anggota tidak diberikan!</h3>", 400
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM identitas WHERE no_anggota = %s", (no_anggota,))
        anggota = cursor.fetchone()
        if not anggota:
            return "<h3>Error: Anggota tidak ditemukan.</h3>", 404
        
        nama_anggota = anggota['nama_anggota']
        cabang_nama = str(anggota.get('cabang') or 'GAS').upper()
        
        cursor.execute("SELECT simpanan_pokok, simpanan_wajib, total_simpanan FROM simpanan WHERE nomor_anggota = %s", (no_anggota,))
        simpanan = cursor.fetchone()
        sim_pokok = float(simpanan['simpanan_pokok']) if simpanan else 0
        sim_wajib = float(simpanan['simpanan_wajib']) if simpanan else 0
        sim_total = float(simpanan['total_simpanan']) if simpanan else 0

        # Get Multiguna Loans grouped by pencairan
        cursor.execute("""
            SELECT tgl_pencairan, jenis_pinjaman, besar_pinjaman, tenor, bunga_persen, 
                   SUM(tagihan_pokok) as total_tagihan_pokok, 
                   SUM(tagihan_margin) as total_tagihan_margin,
                   SUM(angsuran_pokok) as total_dibayar_pokok,
                   SUM(angsuran_margin) as total_dibayar_margin
            FROM angsuran_multiguna_tempo
            WHERE no_anggota = %s
            GROUP BY tgl_pencairan, jenis_pinjaman, besar_pinjaman, tenor, bunga_persen
            ORDER BY tgl_pencairan DESC
        """, (no_anggota,))
        pinjaman_utama_summary = cursor.fetchall()
        
        # We also want the schedule/history for each loan
        cursor.execute("""
            SELECT tgl_pencairan, angsuran_ke, jatuh_tempo, tgl_bayar, status, 
                   tagihan_pokok, tagihan_margin, angsuran_pokok, angsuran_margin, angsuran_denda
            FROM angsuran_multiguna_tempo
            WHERE no_anggota = %s
            ORDER BY tgl_pencairan DESC, angsuran_ke ASC
        """, (no_anggota,))
        pinjaman_utama_detail = cursor.fetchall()

        cursor.execute("""
            SELECT tgl_pencairan, jenis_dana_urgent, tagihan_pokok as besar_pinjaman, tagihan_margin, angsuran_pokok, angsuran_margin, tanggal_jatuh_tempo, tgl_bayar, status, angsuran_denda
            FROM angsuran_dana_urgent
            WHERE no_anggota = %s
            ORDER BY tgl_pencairan DESC
        """, (no_anggota,))
        pinjaman_urgent = cursor.fetchall()
        
    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()
        
    try:
        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else "0"
        
        bca_blue = (0, 81, 162)
        bca_light_blue = (230, 240, 255)
        text_dark = (50, 50, 50)
        
        pdf = PDF(format='A4', cabang=cabang_nama)
        pdf.set_document_title("RINGKASAN REKENING", "Account Statement")
        pdf.add_page()
        pdf.set_margins(12, 10, 12)
        pdf.set_auto_page_break(auto=True, margin=15)
        
        pdf.set_text_color(*text_dark)
        pdf.set_draw_color(*bca_blue)
        pdf.set_line_width(0.5)
        pdf.line(12, pdf.get_y(), 198, pdf.get_y())
        pdf.set_line_width(0.2)
        pdf.ln(5)
        
        # 1. INFORMASI NASABAH & SIMPANAN
        pdf.set_fill_color(*bca_blue)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 7, txt="  INFORMASI NASABAH & SIMPANAN", border=0, ln=True, fill=True)
        pdf.ln(3)
        
        pdf.set_text_color(*text_dark)
        pdf.set_font("Arial", '', 9)
        
        pdf.set_xy(12, pdf.get_y())
        pdf.cell(30, 5, "No. Anggota", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(75, 5, no_anggota, 0, 0)
        
        pdf.set_font("Arial", '', 9)
        pdf.cell(35, 5, "Simpanan Pokok", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(0, 5, f"Rp {f_rp(sim_pokok)}", 0, 1)
        
        pdf.set_font("Arial", '', 9)
        pdf.cell(30, 5, "Nama", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(75, 5, nama_anggota, 0, 0)
        
        pdf.set_font("Arial", '', 9)
        pdf.cell(35, 5, "Simpanan Wajib", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(0, 5, f"Rp {f_rp(sim_wajib)}", 0, 1)

        pdf.set_font("Arial", '', 9)
        pdf.cell(30, 5, "Instansi", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.cell(75, 5, str(anggota.get('pt_instansi') or '-'), 0, 0)

        pdf.set_font("Arial", '', 9)
        pdf.cell(35, 5, "Total Simpanan", 0, 0)
        pdf.cell(5, 5, ":", 0, 0)
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(*bca_blue)
        pdf.cell(0, 5, f"Rp {f_rp(sim_total)}", 0, 1)
        pdf.set_text_color(*text_dark)
        
        pdf.ln(5)
        
        # 2. RIWAYAT PINJAMAN MULTIGUNA / TEMPO
        pdf.set_fill_color(*bca_blue)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 7, txt="  FASILITAS PINJAMAN (MULTIGUNA / TEMPO)", border=0, ln=True, fill=True)
        pdf.ln(3)
        
        if not pinjaman_utama_summary:
            pdf.set_text_color(*text_dark)
            pdf.set_font("Arial", 'I', 9)
            pdf.cell(0, 6, "Tidak ada data pinjaman Multiguna/Tempo.", 0, 1)
            pdf.ln(2)
        else:
            for sum_idx, p in enumerate(pinjaman_utama_summary):
                pdf.set_text_color(*bca_blue)
                pdf.set_fill_color(*bca_light_blue)
                pdf.set_font("Arial", 'B', 9)
                
                tgl_cair_str = p['tgl_pencairan'].strftime('%d-%m-%Y') if hasattr(p['tgl_pencairan'], 'strftime') else str(p['tgl_pencairan'])[:10]
                pdf.cell(0, 6, f"  KONTRAK {sum_idx+1} - {str(p['jenis_pinjaman']).upper()} (Cair: {tgl_cair_str})", 0, 1, fill=True)
                
                pdf.set_text_color(*text_dark)
                pdf.set_font("Arial", '', 8)
                pdf.cell(25, 5, "Plafon", 0, 0)
                pdf.cell(3, 5, ":", 0, 0)
                pdf.cell(45, 5, f"Rp {f_rp(p['besar_pinjaman'])}", 0, 0)
                
                sisa_pokok = float(p['total_tagihan_pokok'] or 0) - float(p['total_dibayar_pokok'] or 0)
                sisa_margin = float(p['total_tagihan_margin'] or 0) - float(p['total_dibayar_margin'] or 0)
                
                pdf.cell(22, 5, "Sisa Pokok", 0, 0)
                pdf.cell(3, 5, ":", 0, 0)
                pdf.cell(45, 5, f"Rp {f_rp(max(0, sisa_pokok))}", 0, 0)
        
                pdf.set_font("Arial", 'B', 8)
                sisa_total = sisa_pokok + sisa_margin
                status_kontrak = "LUNAS" if sisa_total <= 0.01 else "AKTIF"
                pdf.cell(20, 5, "Status", 0, 0)
                pdf.cell(3, 5, ":", 0, 0)
                pdf.set_text_color(0, 128, 0) if status_kontrak == 'LUNAS' else pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 5, status_kontrak, 0, 1)
                pdf.set_text_color(*text_dark)

                pdf.set_font("Arial", '', 8)
                pdf.cell(25, 5, "Tenor/Bunga", 0, 0)
                pdf.cell(3, 5, ":", 0, 0)
                pdf.cell(45, 5, f"{p['tenor']} Bulan / {p['bunga_persen']}%", 0, 0)
                
                pdf.cell(22, 5, "Sisa Margin", 0, 0)
                pdf.cell(3, 5, ":", 0, 0)
                pdf.cell(0, 5, f"Rp {f_rp(max(0, sisa_margin))}", 0, 1)

                pdf.ln(2)
                pdf.set_draw_color(200, 200, 200)
                pdf.set_fill_color(240, 240, 240)
                pdf.set_font("Arial", 'B', 8)
                pdf.cell(10, 6, "Ke", 1, 0, 'C', True)
                pdf.cell(24, 6, "Jatuh Tempo", 1, 0, 'C', True)
                pdf.cell(24, 6, "Tgl Bayar", 1, 0, 'C', True)
                pdf.cell(30, 6, "Tagihan", 1, 0, 'C', True)
                pdf.cell(30, 6, "Realisasi Bayar", 1, 0, 'C', True)
                pdf.cell(25, 6, "Denda", 1, 0, 'C', True)
                pdf.cell(0, 6, "Status", 1, 1, 'C', True)

                pdf.set_font("Arial", '', 8)
                details = [d for d in pinjaman_utama_detail if d['tgl_pencairan'] == p['tgl_pencairan']]
                for d in details:
                    jt = d['jatuh_tempo'].strftime('%d-%m-%Y') if hasattr(d['jatuh_tempo'], 'strftime') else str(d['jatuh_tempo'])[:10]
                    tb = d['tgl_bayar'].strftime('%d-%m-%Y') if hasattr(d['tgl_bayar'], 'strftime') else (str(d['tgl_bayar'])[:10] if d['tgl_bayar'] else '-')
                    tagihan = float(d['tagihan_pokok'] or 0) + float(d['tagihan_margin'] or 0)
                    dibayar = float(d['angsuran_pokok'] or 0) + float(d['angsuran_margin'] or 0)
                    denda = float(d['angsuran_denda'] or 0)
                    
                    pdf.cell(10, 5, str(d['angsuran_ke']), 1, 0, 'C')
                    pdf.cell(24, 5, jt, 1, 0, 'C')
                    pdf.cell(24, 5, tb, 1, 0, 'C')
                    pdf.cell(30, 5, f_rp(tagihan), 1, 0, 'R')
                    pdf.cell(30, 5, f_rp(dibayar), 1, 0, 'R')
                    pdf.cell(25, 5, f_rp(denda), 1, 0, 'R')
                    
                    status = d['status']
                    if status == 'LUNAS': pdf.set_text_color(0, 128, 0)
                    elif status == 'BELUM BAYAR': pdf.set_text_color(200, 0, 0)
                    elif status == 'LUNAS TOP-UP': pdf.set_text_color(0, 0, 200)
                    
                    pdf.cell(0, 5, status, 1, 1, 'C')
                    pdf.set_text_color(*text_dark)

                pdf.ln(5)

        # 3. RIWAYAT DANA URGENT
        if pdf.get_y() > 240: pdf.add_page()
        pdf.set_fill_color(*bca_blue)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 7, txt="  FASILITAS DANA URGENT (GAJI / THR)", border=0, ln=True, fill=True)
        pdf.ln(3)

        if not pinjaman_urgent:
            pdf.set_text_color(*text_dark)
            pdf.set_font("Arial", 'I', 9)
            pdf.cell(0, 6, "Tidak ada data pinjaman Dana Urgent.", 0, 1)
        else:
            pdf.set_text_color(*text_dark)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(25, 6, "Tgl Cair", 1, 0, 'C', True)
            pdf.cell(25, 6, "Jenis", 1, 0, 'C', True)
            pdf.cell(25, 6, "Jatuh Tempo", 1, 0, 'C', True)
            pdf.cell(30, 6, "Plafon + Margin", 1, 0, 'C', True)
            pdf.cell(30, 6, "Realisasi Bayar", 1, 0, 'C', True)
            pdf.cell(25, 6, "Tgl Bayar", 1, 0, 'C', True)
            pdf.cell(0, 6, "Status", 1, 1, 'C', True)
            
            pdf.set_font("Arial", '', 8)
            for u in pinjaman_urgent:
                tc = u['tgl_pencairan'].strftime('%d-%m-%Y') if hasattr(u['tgl_pencairan'], 'strftime') else str(u['tgl_pencairan'])[:10]
                jt = u['tanggal_jatuh_tempo'].strftime('%d-%m-%Y') if hasattr(u['tanggal_jatuh_tempo'], 'strftime') else str(u['tanggal_jatuh_tempo'])[:10]
                tb = u['tgl_bayar'].strftime('%d-%m-%Y') if hasattr(u['tgl_bayar'], 'strftime') else (str(u['tgl_bayar'])[:10] if u['tgl_bayar'] else '-')
                tagihan = float(u['besar_pinjaman'] or 0) + float(u['tagihan_margin'] or 0)
                dibayar = float(u['angsuran_pokok'] or 0) + float(u['angsuran_margin'] or 0)
                
                pdf.cell(25, 5, tc, 1, 0, 'C')
                pdf.cell(25, 5, str(u['jenis_dana_urgent']), 1, 0, 'C')
                pdf.cell(25, 5, jt, 1, 0, 'C')
                pdf.cell(30, 5, f_rp(tagihan), 1, 0, 'R')
                pdf.cell(30, 5, f_rp(dibayar), 1, 0, 'R')
                pdf.cell(25, 5, tb, 1, 0, 'C')
                
                status = u['status']
                if status == 'LUNAS': pdf.set_text_color(0, 128, 0)
                elif status == 'BELUM BAYAR': pdf.set_text_color(200, 0, 0)
                elif status == 'LUNAS TOP-UP': pdf.set_text_color(0, 0, 200)
                
                pdf.cell(0, 5, status, 1, 1, 'C')
                pdf.set_text_color(*text_dark)
            pdf.ln(5)

        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, f"Dicetak pada: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} oleh {session.get('nama_lengkap', 'Sistem')}", 0, 1, 'R')
        
        file_path = os.path.join(tempfile.gettempdir(), f"Rekening_Koran_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e:
        return f"<h3>Terjadi Kesalahan Internal Saat Menggambar PDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_mutasi_pinjaman', defaults={'jenis': None, 'no_anggota': None, 'tgl_pencairan': None}, methods=['GET', 'POST'], strict_slashes=False)
@api_cetak_bp.route('/api/cetak_mutasi_pinjaman/<jenis>', defaults={'no_anggota': None, 'tgl_pencairan': None}, methods=['GET', 'POST'], strict_slashes=False)
@api_cetak_bp.route('/api/cetak_mutasi_pinjaman/<jenis>/<no_anggota>', defaults={'tgl_pencairan': None}, methods=['GET', 'POST'], strict_slashes=False)
@api_cetak_bp.route('/api/cetak_mutasi_pinjaman/<jenis>/<no_anggota>/<tgl_pencairan>', methods=['GET', 'POST'], strict_slashes=False)
def cetak_mutasi_pinjaman(jenis, no_anggota, tgl_pencairan):
    if not jenis: jenis = request.args.get('jenis')
    if not no_anggota: no_anggota = request.args.get('no_anggota')
    if not tgl_pencairan: tgl_pencairan = request.args.get('tgl_pencairan')
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        if not jenis: jenis = data.get('jenis')
        if not no_anggota: no_anggota = data.get('no_anggota')
        if not tgl_pencairan: tgl_pencairan = data.get('tgl_pencairan')
        
    if not jenis or not no_anggota or not tgl_pencairan:
        return "<h3>Error: Parameter cetak mutasi pinjaman tidak lengkap!</h3>", 400
        
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM identitas WHERE no_anggota = %s", (no_anggota,))
        anggota = cursor.fetchone()
        if not anggota: return "<h3>Error: Anggota tidak ditemukan.</h3>", 404
        
        cabang_nama = str(anggota.get('cabang') or session.get('cabang', 'GAS')).upper()
        nama_anggota = anggota['nama_anggota']
        
        if jenis == 'utama':
            cursor.execute("""
                SELECT tgl_pencairan, jenis_pinjaman, besar_pinjaman, tenor, bunga_persen
                FROM angsuran_multiguna_tempo
                WHERE no_anggota = %s AND tgl_pencairan = %s LIMIT 1
            """, (no_anggota, tgl_pencairan))
            pinjaman = cursor.fetchone()
            if not pinjaman: return "<h3>Error: Data pinjaman tidak ditemukan.</h3>", 404
            
            cursor.execute("""
                SELECT angsuran_ke, jatuh_tempo, tgl_bayar, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, edc
                FROM angsuran_multiguna_tempo
                WHERE no_anggota = %s AND tgl_pencairan = %s
                ORDER BY angsuran_ke ASC
            """, (no_anggota, tgl_pencairan))
            detail = cursor.fetchall()
        elif jenis == 'urgent':
            cursor.execute("""
                SELECT tgl_pencairan, jenis_dana_urgent as jenis_pinjaman, tagihan_pokok as besar_pinjaman, 1 as tenor, 0 as bunga_persen
                FROM angsuran_dana_urgent
                WHERE no_anggota = %s AND tgl_pencairan = %s LIMIT 1
            """, (no_anggota, tgl_pencairan))
            pinjaman = cursor.fetchone()
            if not pinjaman: return "<h3>Error: Data pinjaman tidak ditemukan.</h3>", 404
            
            cursor.execute("""
                SELECT 1 as angsuran_ke, tanggal_jatuh_tempo as jatuh_tempo, tgl_bayar, status, tagihan_pokok, tagihan_margin, tagihan_denda, angsuran_pokok, angsuran_margin, angsuran_denda, edc
                FROM angsuran_dana_urgent
                WHERE no_anggota = %s AND tgl_pencairan = %s
            """, (no_anggota, tgl_pencairan))
            detail = cursor.fetchall()
        else:
            return "<h3>Error: Jenis pinjaman tidak valid.</h3>", 400
            
        cursor.execute("CREATE TABLE IF NOT EXISTS pengaturan (kunci VARCHAR(50) PRIMARY KEY, nilai VARCHAR(50))")
        cursor.execute("SELECT nilai FROM pengaturan WHERE kunci = 'denda_aktif'")
        p_row = cursor.fetchone()
        denda_aktif = (p_row['nilai'] == '1') if p_row else True
            
    except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally: cursor.close(); conn.close()
    
    try:
        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else "0"
        
        bca_blue = (0, 81, 162)
        bca_light_blue = (230, 240, 255)
        text_dark = (50, 50, 50)
        
        pdf = PDF(orientation='L', format='A4', cabang=cabang_nama)
        pdf.set_document_title("MUTASI PINJAMAN ANGGOTA")
        pdf.add_page()
        pdf.set_margins(12, 10, 12)
        pdf.set_auto_page_break(auto=True, margin=15)
        
        pdf.set_text_color(*text_dark)
        
        pdf.set_text_color(*text_dark)
        pdf.set_font("Arial", '', 9)
        
        pdf.cell(25, 5, "No. Anggota", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.set_font("Arial", 'B', 9); pdf.cell(70, 5, str(no_anggota), 0, 0); pdf.set_font("Arial", '', 9)
        pdf.cell(25, 5, "Plafon", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.set_font("Arial", 'B', 9); pdf.cell(60, 5, f"Rp {f_rp(pinjaman['besar_pinjaman'])}", 0, 0); pdf.set_font("Arial", '', 9)
        pdf.cell(25, 5, "Tenor/Bunga", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.cell(0, 5, f"{pinjaman['tenor']} Bln / {pinjaman['bunga_persen']}%", 0, 1)
        
        pdf.cell(25, 5, "Nama", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.set_font("Arial", 'B', 9); pdf.cell(70, 5, str(nama_anggota), 0, 0); pdf.set_font("Arial", '', 9)
        t_cair = pinjaman['tgl_pencairan'].strftime('%d-%m-%Y') if hasattr(pinjaman['tgl_pencairan'], 'strftime') else str(pinjaman['tgl_pencairan'])[:10]
        pdf.cell(25, 5, "Tgl Cair", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.cell(60, 5, t_cair, 0, 0)
        pdf.cell(25, 5, "Jenis Pnj.", 0, 0); pdf.cell(3, 5, ":", 0, 0); pdf.cell(0, 5, str(pinjaman['jenis_pinjaman']).upper(), 0, 1)
        pdf.ln(4)

        pdf.set_text_color(*text_dark)
        pdf.set_draw_color(150, 150, 150)
        pdf.set_fill_color(230, 240, 255)
        pdf.set_font("Arial", 'B', 7)
        
        y_t = pdf.get_y()
        x_t = pdf.get_x()
        
        pdf.cell(7, 10, "No", 1, 0, 'C', True)
        pdf.cell(18, 10, "Tgl Trans", 1, 0, 'C', True)
        pdf.cell(44, 10, "Uraian", 1, 0, 'C', True)
        pdf.cell(22, 10, "Realisasi", 1, 0, 'C', True)
        pdf.cell(8, 10, "Bunga", 1, 0, 'C', True)
        
        x_tag = pdf.get_x()
        pdf.cell(49, 5, "Tagihan / Jadwal Angsuran", 1, 0, 'C', True)
        pdf.cell(60, 5, "Angsuran Dibayar", 1, 0, 'C', True)
        
        x_bak = pdf.get_x()
        pdf.cell(22, 10, "Baki Debet", 1, 0, 'C', True)
        
        pdf.set_xy(x_bak + 22, y_t)
        pdf.cell(47, 5, "Tunggakan", 1, 1, 'C', True)
        
        pdf.set_xy(x_tag, y_t + 5)
        pdf.cell(19, 5, "Pokok", 1, 0, 'C', True)
        pdf.cell(17, 5, "Margin", 1, 0, 'C', True)
        pdf.cell(13, 5, "Denda", 1, 0, 'C', True)
        
        pdf.cell(19, 5, "Pokok", 1, 0, 'C', True)
        pdf.cell(17, 5, "Margin", 1, 0, 'C', True)
        pdf.cell(13, 5, "Denda", 1, 0, 'C', True)
        pdf.cell(11, 5, "EDC", 1, 0, 'C', True)
        
        pdf.set_xy(x_bak + 22, y_t + 5)
        pdf.cell(17, 5, "Pokok", 1, 0, 'C', True)
        pdf.cell(16, 5, "Margin", 1, 0, 'C', True)
        pdf.cell(14, 5, "Denda", 1, 1, 'C', True)
        
        pdf.set_font("Arial", '', 7)
        def c(w, txt, align='C'): pdf.cell(w, 5, txt, 1, 0, align)
        def f_n(val): return f"{val:,.0f}".replace(',', '.') if val and float(val) > 0.01 else "-"
        def f_rp_sum(val): return f"Rp {val:,.0f}".replace(',', '.') if val and float(val) > 0.01 else "Rp 0"
        
        baki_debet = float(pinjaman['besar_pinjaman'] or 0)
        sum_tag_p = sum_tag_m = sum_tag_d = 0.0
        sum_byr_p = sum_byr_m = sum_byr_d = sum_byr_e = 0.0
        no_counter = 1
        
        today = datetime.now().date()
        
        c(7, str(no_counter))
        c(18, t_cair)
        uraian_pencairan = f" PENCAIRAN A.N {str(nama_anggota).upper()}"
        if len(uraian_pencairan) > 30: uraian_pencairan = uraian_pencairan[:28] + ".."
        c(44, uraian_pencairan, 'L')
        c(22, f_n(baki_debet), 'R')
        c(8, f"{pinjaman['bunga_persen']:g}%")
        c(19, "-", 'R'); c(17, "-", 'R'); c(13, "-", 'R')
        c(19, "-", 'R'); c(17, "-", 'R'); c(13, "-", 'R'); c(11, "-", 'R')
        c(22, f_n(baki_debet), 'R')
        c(17, "-", 'R'); c(16, "-", 'R'); c(14, "-", 'R')
        pdf.ln()

        for d in detail:
            jt_date = d['jatuh_tempo']
            if isinstance(jt_date, str): jt_date = datetime.strptime(jt_date[:10], '%Y-%m-%d').date()
            elif hasattr(jt_date, 'date'): jt_date = jt_date.date()
            jt = jt_date.strftime('%d-%m-%Y')
            
            tag_p = float(d['tagihan_pokok'] or 0)
            tag_m = float(d['tagihan_margin'] or 0)

            byr_p = float(d['angsuran_pokok'] or 0)
            byr_m = float(d['angsuran_margin'] or 0)
            byr_d = float(d['angsuran_denda'] or 0)
            byr_e = float(d.get('edc') or 0)
            tag_d_db = float(d.get('tagihan_denda') or 0)
            
            sisa_p_curr = max(0, tag_p - byr_p)
            sisa_m_curr = max(0, tag_m - byr_m)

            tunggakan_d_tag = 0.0
            is_overdue = (jt_date and jt_date < today)
            
            if d['status'] not in ['LUNAS', 'LUNAS TOP-UP'] and denda_aktif and is_overdue:
                tunggakan_d_tag, _ = hitung_denda_keterlambatan(
                    jatuh_tempo=jt_date,
                    tgl_bayar=d.get('tgl_bayar'),
                    tagihan_pokok=tag_p,
                    tagihan_margin=tag_m,
                    angsuran_pokok=byr_p,
                    angsuran_margin=byr_m,
                    tagihan_denda_db=tag_d_db,
                    angsuran_denda=byr_d,
                    denda_aktif=denda_aktif,
                    jenis_pinjaman=pinjaman.get('jenis_pinjaman', 'Multiguna'),
                    tgl_referensi=today
                )
            else:
                # Jika tidak telat atau denda non-aktif, tunggakan adalah sisa dari yang sudah ditagih di DB
                tunggakan_d_tag = max(0, tag_d_db - byr_d)

            # Total denda yang ditagihkan adalah jumlah yang sudah dibayar + sisa tunggakan saat ini
            tag_d = byr_d + tunggakan_d_tag

            sum_tag_p += tag_p; sum_tag_m += tag_m; sum_tag_d += tag_d
            sum_byr_p += byr_p; sum_byr_m += byr_m; sum_byr_d += byr_d; sum_byr_e += byr_e
            
            no_counter += 1
            
            # Baris Tagihan (Jadwal)
            c(7, str(no_counter))
            c(18, jt)
            c(44, f" Tagihan ke-{d['angsuran_ke']}", 'L')
            c(22, "-", 'R'); c(8, "-", 'C')
            c(19, f_n(tag_p), 'R'); c(17, f_n(tag_m), 'R'); c(13, f_n(tag_d), 'R')
            c(19, "-", 'R'); c(17, "-", 'R'); c(13, "-", 'R'); c(11, "-", 'R')
            c(22, f_n(baki_debet), 'R')
            c(17, f_n(sisa_p_curr), 'R'); c(16, f_n(sisa_m_curr), 'R'); c(14, f_n(tunggakan_d_tag), 'R')
            pdf.ln()
            
            # Baris Pembayaran (Jika ada progress)
            has_payment = (byr_p > 0 or byr_m > 0 or byr_d > 0 or d['status'] in ['LUNAS', 'LUNAS TOP-UP'])
            if has_payment:
                baki_debet -= byr_p
                
                tb = d['tgl_bayar'].strftime('%d-%m-%Y') if hasattr(d['tgl_bayar'], 'strftime') else (str(d['tgl_bayar'])[:10] if d['tgl_bayar'] else '-')
                
                c(7, "")
                c(18, tb)
                uraian_byr = f" Pembayaran ke-{d['angsuran_ke']}"
                if d['status'] == 'LUNAS TOP-UP': uraian_byr += " (TOP-UP)"
                elif d['status'] == 'BELUM BAYAR': uraian_byr += " (Sebagian)"
                c(44, uraian_byr, 'L')
                c(22, "-", 'R'); c(8, "-", 'C')
                c(19, "-", 'R'); c(17, "-", 'R'); c(13, "-", 'R')
                c(19, f_n(byr_p), 'R'); c(17, f_n(byr_m), 'R'); c(13, f_n(byr_d), 'R'); c(11, f_n(byr_e), 'R')
                c(22, f_n(baki_debet), 'R')
                c(17, "-", 'R'); c(16, "-", 'R'); c(14, "-", 'R')
                pdf.ln()
                

        pdf.ln(5)
        pdf.set_font("Arial", 'B', 8)
        y_start = pdf.get_y()
        
        pdf.cell(35, 5, "Total Tagihan Pokok", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_tag_p), 0, 1)
        pdf.cell(35, 5, "Total Tagihan Margin", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_tag_m), 0, 1)
        pdf.cell(35, 5, "Total Tagihan Denda", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_tag_d), 0, 1)
        
        pdf.set_xy(80, y_start)
        pdf.cell(35, 5, "Total Angsuran Pokok", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_byr_p), 0, 1)
        pdf.set_xy(80, pdf.get_y())
        pdf.cell(35, 5, "Total Angsuran Margin", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_byr_m), 0, 1)
        pdf.set_xy(80, pdf.get_y())
        pdf.cell(35, 5, "Total Angsuran Denda", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_byr_d), 0, 1)
        pdf.set_xy(80, pdf.get_y())
        pdf.cell(35, 5, "Total Angsuran EDC", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_byr_e), 0, 1)
        
        pdf.set_xy(160, y_start)
        pdf.cell(35, 5, "Total Sisa Pokok", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_tag_p - sum_byr_p), 0, 1)
        pdf.set_xy(160, pdf.get_y())
        pdf.cell(35, 5, "Total Sisa Margin", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(sum_tag_m - sum_byr_m), 0, 1)
        pdf.set_xy(160, pdf.get_y())
        pdf.cell(35, 5, "Total Sisa Denda", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum(max(0, sum_tag_d - sum_byr_d)), 0, 1)
        pdf.set_xy(160, pdf.get_y())
        pdf.cell(35, 5, "Total Sisa Hutang", 0, 0); pdf.cell(5, 5, ":", 0, 0); pdf.cell(30, 5, f_rp_sum((sum_tag_p - sum_byr_p) + (sum_tag_m - sum_byr_m) + max(0, sum_tag_d - sum_byr_d)), 0, 1)
        
        pdf.ln(8)
        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, f"Dicetak pada: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} oleh {session.get('nama_lengkap', 'Sistem')}", 0, 1, 'R')
        
        file_path = os.path.join(tempfile.gettempdir(), f"Mutasi_Pinjaman_{no_anggota}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan Internal Saat Menggambar PDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/daftar_cetak_akad', methods=['GET'], endpoint='api_daftar_akad_baru')
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

@api_cetak_bp.route('/api/daftar_cetak_struk', methods=['GET'], endpoint='api_daftar_struk_baru')
def get_daftar_cetak_struk():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
        # OPTIMALISASI: Menggabungkan 2 query menjadi 1 dengan UNION ALL dan membiarkan DB yang melakukan sorting & limit.
        query = """
            SELECT id, no_anggota, nama_anggota, jenis, angsuran_ke, tgl_bayar, kategori
            FROM (
                SELECT a.id, a.no_anggota, a.nama_anggota, a.jenis_pinjaman as jenis, a.angsuran_ke, a.tgl_bayar, 'utama' as kategori 
                FROM angsuran_multiguna_tempo a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.status = 'LUNAS' AND i.cabang = %s
                
                UNION ALL
                
                SELECT a.id, a.no_anggota, a.nama_anggota, a.jenis_dana_urgent as jenis, 1 as angsuran_ke, a.tgl_bayar, 'urgent' as kategori 
                FROM angsuran_dana_urgent a
                JOIN identitas i ON a.no_anggota = i.no_anggota
                WHERE a.status = 'LUNAS' AND i.cabang = %s
            ) as combined_struk
            ORDER BY tgl_bayar DESC, id DESC 
            LIMIT 200
        """
        cursor.execute(query, (cabang, cabang))
        data = cursor.fetchall()
        for row in data:
            if hasattr(row['tgl_bayar'], 'isoformat'): row['tgl_bayar'] = str(row['tgl_bayar'])
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)}), 500
    finally: cursor.close(); conn.close()

@api_cetak_bp.route('/api/daftar_cetak_simpanan', methods=['GET'], endpoint='api_daftar_simpanan_baru')
def get_daftar_cetak_simpanan():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cabang = session.get('cabang', 'GAS')
    try:
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

@api_cetak_bp.route('/api/cetak_simpanan/', defaults={'tipe': None, 'id_jurnal': None}, methods=['GET'])
@api_cetak_bp.route('/api/cetak_simpanan/<tipe>/<id_jurnal>', methods=['GET'], endpoint='api_cetak_simpanan_baru')
def cetak_simpanan(tipe, id_jurnal):
    if not tipe or not id_jurnal:
        return "<h3>Error: Parameter cetak simpanan tidak lengkap!</h3>", 400
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

    if id_jurnal == 'TEMPLATE':
        tanggal = "(Otomatis Tanggal)"
        keterangan = "(Otomatis Keterangan)"
        jenis_transaksi = "SETORAN SIMPANAN" if tipe == 'setoran' else "PENARIKAN SIMPANAN"
        nominal = 0
        nama_anggota = "(Otomatis Nama Anggota)"
        cabang_nama = "(OTOMATIS CABANG)"
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT j.tanggal, c.account_name, j.keterangan, j.debit, j.kredit, j.cabang FROM jurnal_umum j JOIN coa c ON j.coa_id = c.id WHERE j.id = %s", (id_jurnal,))
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
            
            cabang_nama = str(data.get('cabang') or session.get('cabang', 'GAS')).upper()
        except Exception as e: return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
        finally: cursor.close(); conn.close()
        
    try:
        pdf = PDF(orientation='L', format='A5', cabang=cabang_nama)
        pdf.set_document_title(f"BUKTI TRANSAKSI {jenis_transaksi}")
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        
        pdf.set_font("Arial", '', 10)
        pdf.cell(35, 6, "Tanggal Transaksi", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, tanggal, ln=True)
        pdf.cell(35, 6, "Nama Anggota", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, nama_anggota, ln=True)
        pdf.cell(35, 6, "Keterangan", ln=False); pdf.cell(5, 6, ":"); pdf.cell(0, 6, keterangan, ln=True)
        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
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

@api_cetak_bp.route('/api/cetak_mutasi', methods=['GET'])
@api_cetak_bp.route('/api/cetak_arus_kas', methods=['GET'])
def cetak_mutasi_kas():
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        date_filter = " AND j.cabang = %s"
        params = [cabang]
        
        periode_str = "Semua Waktu"
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
            periode_str = f"{start_date} s.d. {end_date}"
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
            periode_str = f"Mulai {start_date}"
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)
            periode_str = f"Hingga {end_date}"

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
        
    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        pdf = PDF('P', 'mm', 'A4', cabang=cabang)
        pdf.set_document_title("LAPORAN MUTASI ARUS KAS", f"Periode: {periode_str}")
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'

        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(200, 200, 200)
        
        pdf.cell(25, 6, "Tanggal", 1, 0, 'C', True)
        pdf.cell(75, 6, "Keterangan", 1, 0, 'C', True)
        pdf.cell(30, 6, "Masuk", 1, 0, 'C', True)
        pdf.cell(30, 6, "Keluar", 1, 0, 'C', True)
        pdf.cell(30, 6, "Saldo", 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        saldo_berjalan = float(saldo_awal)
        
        if start_date:
            pdf.cell(25, 6, "-", 1, 0, 'C')
            pdf.cell(75, 6, "Saldo Awal", 1, 0, 'L')
            pdf.cell(30, 6, "-", 1, 0, 'R')
            pdf.cell(30, 6, "-", 1, 0, 'R')
            pdf.cell(30, 6, f_rp(saldo_berjalan), 1, 1, 'R')
            
        if not mutasi:
            pdf.cell(190, 6, "Tidak ada data mutasi kas.", 1, 1, 'C')
        else:
            for row in mutasi:
                tgl = row['tanggal']
                if hasattr(tgl, 'strftime'): tgl = tgl.strftime('%d-%m-%Y')
                elif isinstance(tgl, str): tgl = tgl[:10]
                
                masuk = float(row['masuk'] or 0)
                keluar = float(row['keluar'] or 0)
                saldo_berjalan += (masuk - keluar)
                
                pdf.cell(25, 6, tgl, 1, 0, 'C')
                
                ket = str(row['keterangan'])
                if len(ket) > 40: ket = ket[:37] + "..."
                pdf.cell(75, 6, ket, 1, 0, 'L')
                
                pdf.cell(30, 6, f_rp(masuk) if masuk > 0 else "-", 1, 0, 'R')
                pdf.cell(30, 6, f_rp(keluar) if keluar > 0 else "-", 1, 0, 'R')
                pdf.cell(30, 6, f_rp(saldo_berjalan), 1, 1, 'R')

        pdf.ln(5)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(130, 6, "Saldo Akhir", 0, 0, 'R')
        pdf.cell(60, 6, f"Rp {f_rp(saldo_berjalan)}", 0, 1, 'R')

        file_path = os.path.join(tempfile.gettempdir(), f"Mutasi_Kas_{cabang}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_laporan_harian_pdf', methods=['GET', 'POST'], strict_slashes=False)
def cetak_laporan_harian_pdf():
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
    
    tanggal = request.args.get('tanggal', datetime.now().strftime('%Y-%m-%d'))
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        if data.get('tanggal'): tanggal = data.get('tanggal')
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

        # OPTIMALISASI: Memindahkan kalkulasi anggota macet dari Python ke SQL untuk performa tinggi.
        query_macet = """
            SELECT
                i.no_anggota,
                i.nama_anggota,
                SUM(a.sisa_tagihan) as total_sisa_tagihan,
                MAX(a.od_hari) as max_od_hari
            FROM (
                SELECT 
                    no_anggota,
                    (tagihan_pokok + tagihan_margin - angsuran_pokok - angsuran_margin) as sisa_tagihan,
                    DATEDIFF(%s, jatuh_tempo) as od_hari
                FROM angsuran_multiguna_tempo
                WHERE status = 'BELUM BAYAR' AND DATE(jatuh_tempo) < %s
                
                UNION ALL
                
                SELECT 
                    no_anggota,
                    (tagihan_pokok + tagihan_margin - angsuran_pokok - angsuran_margin) as sisa_tagihan,
                    DATEDIFF(%s, tanggal_jatuh_tempo) as od_hari
                FROM angsuran_dana_urgent
                WHERE status = 'BELUM BAYAR' AND DATE(tanggal_jatuh_tempo) < %s
            ) a
            JOIN identitas i ON a.no_anggota = i.no_anggota
            WHERE i.cabang = %s AND a.sisa_tagihan > 0.1
            GROUP BY i.no_anggota, i.nama_anggota
        """
        cursor.execute(query_macet, (tanggal, tanggal, tanggal, tanggal, cabang))
        data_macet = cursor.fetchall()
    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        try: tgl_obj = datetime.strptime(tanggal, '%Y-%m-%d')
        except: tgl_obj = datetime.now()
        periode_str = f"Periode Tanggal: {tgl_obj.strftime('%d-%m-%Y')}"

        pdf = PDF('P', 'mm', 'A4', cabang=cabang)
        pdf.set_document_title(f"LAPORAN HARIAN OPERASIONAL CABANG {str(cabang).upper()}", periode_str)
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

        # 4. Macet Data processing (sudah diolah oleh SQL)
        macet_1_6 = sorted([v for v in data_macet if 1 <= v['max_od_hari'] <= 180], key=lambda x: x['max_od_hari'], reverse=True)
        macet_lebih_6 = sorted([v for v in data_macet if v['max_od_hari'] > 180], key=lambda x: x['max_od_hari'], reverse=True)

        def render_macet_table(title, data_macet_list):
            if pdf.get_y() > 220: pdf.add_page()
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
                    pdf.cell(w4[2], 6, f"{row['max_od_hari']} hari", 1, 0, 'C')
                    pdf.cell(w4[3], 6, f_rp(row['total_sisa_tagihan']), 1, 1, 'R')
            pdf.ln(5)

        render_macet_table("4. Anggota Macet (1 - 6 Bulan)", macet_1_6)
        render_macet_table("5. Anggota Macet (> 6 Bulan)", macet_lebih_6)

        file_path = os.path.join(tempfile.gettempdir(), f"Laporan_Harian_{tanggal}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e: return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_laba_rugi_pdf', methods=['GET'])
def cetak_laba_rugi_pdf():
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Build date filter
        date_filter = ""
        params = [cabang]
        periode_str = "Semua Waktu"
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
            periode_str = f"{start_date} s.d. {end_date}"
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
            periode_str = f"Mulai {start_date}"
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)
            periode_str = f"Hingga {end_date}"

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

    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        pdf = PDF('P', 'mm', 'A4', cabang=cabang)
        pdf.set_document_title("LAPORAN LABA RUGI", f"Periode: {periode_str}")
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'

        # --- PENDAPATAN ---
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 8, "Pendapatan", ln=True)
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(30, 6, "Kode Akun", 1, 0, 'C', True)
        pdf.cell(120, 6, "Nama Akun", 1, 0, 'C', True)
        pdf.cell(40, 6, "Saldo", 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        if not pendapatan:
            pdf.cell(190, 6, "Tidak ada data pendapatan.", 1, 1, 'C')
        else:
            for row in pendapatan:
                pdf.cell(30, 6, str(row['account_code']), 1, 0, 'C')
                pdf.cell(120, 6, "  " + str(row['account_name']), 1, 0, 'L')
                pdf.cell(40, 6, f_rp(float(row['saldo'])), 1, 1, 'R')
        
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(150, 7, "Total Pendapatan", 1, 0, 'R')
        pdf.cell(40, 7, f_rp(total_pendapatan), 1, 1, 'R')
        pdf.ln(5)

        # --- BEBAN ---
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 8, "Beban Operasional", ln=True)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(30, 6, "Kode Akun", 1, 0, 'C', True)
        pdf.cell(120, 6, "Nama Akun", 1, 0, 'C', True)
        pdf.cell(40, 6, "Saldo", 1, 1, 'C', True)

        pdf.set_font('Arial', '', 9)
        if not beban:
            pdf.cell(190, 6, "Tidak ada data beban.", 1, 1, 'C')
        else:
            for row in beban:
                pdf.cell(30, 6, str(row['account_code']), 1, 0, 'C')
                pdf.cell(120, 6, "  " + str(row['account_name']), 1, 0, 'L')
                pdf.cell(40, 6, f_rp(float(row['saldo'])), 1, 1, 'R')

        pdf.set_font('Arial', 'B', 9)
        pdf.cell(150, 7, "Total Beban", 1, 0, 'R')
        pdf.cell(40, 7, f_rp(total_beban), 1, 1, 'R')
        pdf.ln(8)

        # --- LABA BERSIH ---
        pdf.set_font('Arial', 'B', 11)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(150, 8, "LABA BERSIH", 1, 0, 'R', True)
        pdf.cell(40, 8, f_rp(laba_bersih), 1, 1, 'R', True)

        file_path = os.path.join(tempfile.gettempdir(), f"Laba_Rugi_{cabang}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')

    except Exception as e:
        return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500

@api_cetak_bp.route('/api/cetak_neraca_pdf', methods=['GET'])
def cetak_neraca_pdf():
    if FPDF is None:
        return "<h3>Error: Library FPDF belum diinstall!</h3>", 500

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    cabang = session.get('cabang', 'GAS')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        date_filter = " AND j.cabang = %s"
        params = [cabang]
        periode_str = "Semua Waktu"
        if start_date and end_date:
            date_filter += " AND DATE(j.tanggal) BETWEEN %s AND %s"
            params.extend([start_date, end_date])
            periode_str = f"{start_date} s.d. {end_date}"
        elif start_date:
            date_filter += " AND DATE(j.tanggal) >= %s"
            params.append(start_date)
            periode_str = f"Mulai {start_date}"
        elif end_date:
            date_filter += " AND DATE(j.tanggal) <= %s"
            params.append(end_date)
            periode_str = f"Hingga {end_date}"

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

    except Exception as e:
        return f"<h3>Error Database:</h3><p>{str(e)}</p>", 500
    finally:
        cursor.close()
        conn.close()

    try:
        pdf = PDF('P', 'mm', 'A4', cabang=cabang)
        pdf.set_document_title("LAPORAN NERACA", f"Periode: {periode_str}")
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        def f_rp(val): return f"{val:,.0f}".replace(',', '.') if val else '0'
        
        w_kode, w_nama, w_saldo = 25, 125, 40
        
        def draw_table(title, data, total):
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 8, title, ln=True)
            pdf.set_font('Arial', 'B', 9)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(w_kode, 6, "Kode Akun", 1, 0, 'C', True)
            pdf.cell(w_nama, 6, "Nama Akun", 1, 0, 'C', True)
            pdf.cell(w_saldo, 6, "Saldo", 1, 1, 'C', True)
            
            pdf.set_font('Arial', '', 9)
            if not data:
                pdf.cell(w_kode + w_nama + w_saldo, 6, "Tidak ada data.", 1, 1, 'C')
            else:
                for row in data:
                    pdf.cell(w_kode, 6, str(row['account_code']), 1, 0, 'C')
                    pdf.cell(w_nama, 6, "  " + str(row['account_name']), 1, 0, 'L')
                    pdf.cell(w_saldo, 6, f_rp(float(row['saldo'])), 1, 1, 'R')
            
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(w_kode + w_nama, 7, f"Total {title}", 1, 0, 'R')
            pdf.cell(w_saldo, 7, f_rp(total), 1, 1, 'R')
            pdf.ln(5)

        draw_table("Aktiva", aktiva, total_aktiva)
        draw_table("Kewajiban", kewajiban, total_kewajiban)
        draw_table("Ekuitas", ekuitas, total_ekuitas)

        pdf.set_font('Arial', 'B', 9)
        pdf.cell(w_kode + w_nama, 7, "Laba/Rugi Berjalan", 1, 0, 'R')
        pdf.cell(w_saldo, 7, f_rp(laba_berjalan), 1, 1, 'R')
        pdf.ln(2)

        pdf.set_font('Arial', 'B', 11)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(w_kode + w_nama, 8, "TOTAL PASIVA (Kewajiban + Ekuitas + Laba)", 1, 0, 'R', True)
        pdf.cell(w_saldo, 8, f_rp(total_pasiva), 1, 1, 'R', True)

        file_path = os.path.join(tempfile.gettempdir(), f"Neraca_{cabang}.pdf")
        pdf.output(file_path)
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')

    except Exception as e:
        return f"<h3>Terjadi Kesalahan FPDF:</h3><p>{str(e)}</p>", 500