# 🏦 Koperasi Gabe Artha System (GAS)

Sistem Informasi Manajemen terpadu untuk **KSP Gabe Artha Nauli**. Aplikasi berbasis Web ini dibangun untuk mendigitalisasi proses bisnis operasional koperasi, mulai dari manajemen data anggota, proses pencairan pinjaman, pencatatan angsuran, manajemen simpanan, hingga pembukuan akuntansi yang tersinkronisasi secara otomatis.

---

## ✨ Fitur Utama

Aplikasi ini dirancang dengan berbagai modul utama, di antaranya:

- **👥 Manajemen Identitas Anggota**
  - Pendaftaran anggota baru dengan *Auto-Generate* Nomor Anggota cerdas (berdasarkan Cabang & Tanggal).
  - Penyimpanan berkas digital (KTP, KK, ID Card) dalam format PDF.
  - Rekam jejak lengkap anggota (Simpanan, Pinjaman, dan Histori Transaksi).
  - **Proteksi Akses (Cross-Session Prevention)** mencegah tabrakan sesi antara Hak Akses Anggota dan Admin.
- **💸 Manajemen Pinjaman & Angsuran**
  - Mendukung produk: **Multiguna / Tempo** dan **Dana Urgent (Gaji & THR)**.
  - Sistem *Auto-Generate* jadwal angsuran (Tenor).
  - Perhitungan otomatis denda keterlambatan (*Overdue Days*) secara *Real-time* (dengan fitur *Switch Denda Aktif/Migrasi*).
  - Fasilitas *Top-Up* Pinjaman dengan pemotongan otomatis pada piutang berjalan.
  - Penerimaan pembayaran *partial* (sebagian) dan input biaya **EDC / Admin Kasir**.
- **💰 Manajemen Simpanan**
  - Pencatatan Simpanan Pokok dan Simpanan Wajib.
  - Penarikan Simpanan yang langsung memotong saldo dan terhubung dengan kas.
- **📊 Sistem Akuntansi & Laporan (Multi-Cabang)**
  - **Dukungan Multi-Cabang**: Data difilter dan dilimitasi otomatis berdasarkan lokasi cabang admin.
  - **Jurnal Umum Otomatis**: Setiap transaksi (Pencairan, Angsuran, Pengeluaran) otomatis dicatat sebagai jurnal (Debit/Kredit).
  - **Buku Besar, Laba Rugi, Neraca, dan Arus Kas**.
  - Pencatatan Pengeluaran Operasional, **Manajemen Aset Operasional**, serta **Realisasi Anggaran**.
  - Dashboard Evaluasi & Laporan Harian otomatis (Format Tabel & PDF) untuk rekap aktivitas cabang.
- **🖨️ Cetak Dokumen Digital (PDF)**
  - Cetak Bukti Angsuran (Struk).
  - Cetak Surat Perjanjian Kredit (Akad Pinjaman).
  - Cetak Surat Pernyataan Anggota.
- **🔐 Sistem Approval Hierarki & Keamanan**
  - Setiap transaksi krusial (seperti Pencairan Kas atau Pengeluaran Operasional) yang diinput oleh Admin akan masuk ke antrean (*Queue*).
  - Wajib mendapatkan persetujuan (*Approval*) dari **Manager** sebelum dibukukan.
  - **Pembatalan Transaksi (Void)** dilindungi oleh **Audit Logs** untuk rekam jejak.
- **🔄 Modul Migrasi Sistem (Import Excel/CSV)**
  - Impor data *Identitas, Multiguna, dan Urgent* secara massal dari sistem lama menggunakan CSV.

---

## 💻 Teknologi yang Digunakan

- **Backend Framework**: Python (Flask)
- **Database**: MySQL (`mysql-connector-python`)
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5, FontAwesome
- **Library Tambahan**: 
  - `fpdf` (Untuk menggambar/membuat dokumen PDF secara dinamis)
  - `werkzeug.security` (Untuk proses *hashing* password keamanan login)
  - `pandas` (Untuk manajemen data migrasi Excel/CSV)
  - `python-dotenv` (Untuk manajemen environment variables)

---

## 🚀 Panduan Instalasi & Menjalankan Aplikasi Lokal

Ikuti langkah-langkah di bawah ini untuk menjalankan aplikasi di komputer lokal Anda:

### 1. Persiapan Perangkat Lunak (Prerequisites)
- **Python** (Minimal versi 3.8+)
- **XAMPP / Laragon / MySQL Server** (Untuk menjalankan database MySQL)
- **Git**

### 2. Kloning Repository
```bash
git clone https://github.com/bhutahaean02/Gabe-Artha-System.git
cd Gabe-Artha-System
```

### 3. Persiapan Lingkungan Virtual (Virtual Environment)
Sangat disarankan menggunakan virtual environment agar *library* terisolasi.
```bash
python -m venv venv
# Jika Anda menggunakan Windows (Command Prompt / PowerShell):
venv\Scripts\activate
```

### 4. Instalasi Library (Dependencies)
Instal semua library yang dibutuhkan menggunakan pip:
```bash
pip install Flask mysql-connector-python fpdf werkzeug pandas python-dotenv
```

### 5. Konfigurasi Database
1. Buka aplikasi XAMPP dan jalankan modul **MySQL**.
2. Buat database baru bernama `koperasi_gabe_artha`.
3. Lakukan impor struktur tabel (MySQL Dump) Anda ke dalam database tersebut.
4. Buat file `.env` di folder *root* aplikasi dan isi dengan konfigurasi kredensial lokal Anda:
   ```env
   DB_HOST=localhost
   DB_USER=root
   DB_PASSWORD=
   DB_NAME=koperasi_gabe_artha
   SECRET_KEY=super_secret_key_anda
   ```
   *(Sistem menggunakan `config.py` yang otomatis membaca file `.env`)*

### 6. Menjalankan Server Aplikasi
```bash
python app.py
```
Aplikasi akan berjalan di server lokal. Buka browser dan akses alamat berikut:
**`http://localhost:5000`**

---

## 📁 Struktur Direktori Penting

- `app.py`: File utama (Entry point) untuk menjalankan server Flask.
- `routes_pages.py`: Konfigurasi rute (URL) antar halaman HTML (*Frontend*).
- `routes_api.py`, `api_*.py`: Kumpulan Blueprint API (*Backend*) sebagai pengendali logika transaksi, akuntansi, dan database.
- `api_helpers.py`: Fungsi-fungsi bantuan (seperti pembentukan auto-jurnal, generator nomor anggota, fungsi terbilang).
- `templates/`: Kumpulan file UI (*User Interface*) dengan ekstensi `.html`.
- `static/`: Folder untuk menyimpan logo, aset gambar, serta file statis CSS/JS bawaan jika ada.
- `uploads/`: Direktori untuk menyimpan hasil unggahan dokumen PDF milik anggota.

---
*© 2026 - Dikembangkan secara eksklusif untuk KSP Gabe Artha Nauli.*
