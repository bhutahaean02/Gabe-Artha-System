# 🏦 Koperasi Gabe Artha System (GAS)

Sistem Informasi Manajemen (SIM) terpadu untuk **KSP Gabe Artha Nauli**. Aplikasi berbasis web ini dibangun untuk mendigitalisasi dan mengotomatisasi proses bisnis operasional koperasi, mulai dari manajemen anggota, pinjaman, simpanan, hingga sistem akuntansi multi-cabang yang terintegrasi.

---

## ✨ Fitur Utama

Aplikasi ini dirancang dengan arsitektur modular yang mencakup berbagai fungsionalitas penting:

-   ** Manajemen Anggota & CRM**
    -   Pendaftaran anggota baru dengan *auto-generate* nomor anggota cerdas (berdasarkan cabang & tanggal).
    -   Penyimpanan dan manajemen berkas digital (KTP, KK, dll.) dalam format PDF.
    -   Rekam jejak lengkap anggota (profil, simpanan, histori pinjaman).
    -   **Monitoring Lokasi Anggota**: Ekstraksi koordinat dari Google Maps dengan akurasi tinggi untuk pemetaan alamat tagih.

-   **💸 Manajemen Pinjaman & Angsuran**
    -   Dukungan untuk berbagai produk pinjaman: **Multiguna/Tempo** dan **Dana Urgent (Gaji & THR)**.
    -   Sistem *auto-generate* jadwal angsuran (tenor) saat pencairan.
    -   Perhitungan denda keterlambatan (*overdue*) secara *real-time* dengan *switch* on/off untuk mode migrasi.
    -   Fasilitas **Top-Up** dan **Restrukturisasi** pinjaman.
    -   Pencatatan pembayaran parsial dan biaya tambahan (EDC/Admin).

-   **💰 Manajemen Simpanan**
    -   Pencatatan Simpanan Pokok dan Simpanan Wajib.
    -   Fungsi penarikan simpanan yang terintegrasi langsung dengan modul kas dan akuntansi.

-   **📊 Akuntansi & Pelaporan Terintegrasi**
    -   **Dukungan Multi-Cabang**: Data difilter otomatis berdasarkan hak akses dan lokasi cabang admin.
    -   **Jurnal Umum Otomatis**: Setiap transaksi (pencairan, angsuran, pengeluaran) otomatis dicatat sebagai jurnal debit/kredit.
    -   Laporan keuangan lengkap: **Buku Besar, Laba Rugi, Neraca, dan Arus Kas**.
    -   Manajemen Aset Operasional dan Realisasi Anggaran.
    -   Dashboard evaluasi performa dan laporan harian (PDF).

-   **🔐 Keamanan & Alur Persetujuan (Approval)**
    -   **Hierarki Approval**: Transaksi krusial (pencairan, pengeluaran) yang diinput oleh Admin memerlukan persetujuan dari **Manager**.
    -   **Audit Logs**: Pencatatan semua aktivitas penting seperti pembatalan transaksi (void) untuk rekam jejak dan akuntabilitas.
    -   **Proteksi Sesi**: Mencegah akses ilegal dan *crossed-session* antara role Admin dan Anggota.

-   **🖨️ Cetak Dokumen Digital (PDF)**
    -   Cetak Bukti Angsuran (Struk), Surat Perjanjian Kredit (Akad), Surat Pernyataan, dan dokumen lainnya secara dinamis.

-   **🔄 Modul Migrasi Data**
    -   Fasilitas impor data massal dari sistem lama menggunakan file Excel/CSV untuk data identitas dan pinjaman.

---

## 💻 Tumpukan Teknologi (Tech Stack)

-   **Backend**: Python dengan framework **Flask**.
-   **Frontend**: HTML5, CSS3, JavaScript, **Bootstrap 5**.
- **Database**: MySQL (`mysql-connector-python`)
-   **Library Utama Python**:
    -   `Flask`: Kerangka kerja web.
    -   `mysql-connector-python`: Konektor untuk database MySQL.
    -   `requests` & `BeautifulSoup4`: Untuk HTTP requests dan parsing HTML (digunakan pada ekstraksi koordinat Google Maps).
    -   `pandas`: Untuk pemrosesan data pada modul migrasi (Excel/CSV).
    -   `fpdf`: Untuk generasi dokumen PDF dinamis.
    -   `werkzeug`: Untuk hashing password dan utilitas web server.
    -   `python-dotenv`: Untuk manajemen variabel lingkungan (konfigurasi).

---

## 🚀 Panduan Instalasi & Menjalankan Aplikasi Lokal

Ikuti langkah-langkah di bawah ini untuk menjalankan aplikasi di komputer lokal Anda:

### 1. Persiapan Perangkat Lunak (Prerequisites)
-   **Python** (Minimal versi 3.8+)
-   **Server Database MySQL** (Contoh: XAMPP, Laragon, atau instalasi MySQL Server mandiri)
-   **Git** (Untuk kloning repositori)

### 2. Kloning Repository
Buka terminal atau command prompt, lalu jalankan perintah berikut:
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
pip install Flask mysql-connector-python fpdf werkzeug pandas python-dotenv requests beautifulsoup4
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
