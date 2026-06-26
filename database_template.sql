-- ==========================================================
-- SQL Dump Template untuk Koperasi Gabe Artha System (GAS)
-- Versi Diperbarui - Mencakup Semua Tabel & Kolom
-- ==========================================================

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

-- --------------------------------------------------------
-- Struktur dari tabel `users` (Hak Akses Sistem)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `nama_lengkap` varchar(100) DEFAULT NULL,
  `role` enum('Super Admin','Manager','Admin') DEFAULT 'Admin',
  `cabang` varchar(50) DEFAULT 'GAS',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data Default: Password untuk admin adalah "admin" (Harap di-hash pada saat live)
INSERT IGNORE INTO `users` (`id`, `username`, `password`, `nama_lengkap`, `role`, `cabang`) VALUES
(1, 'admin', 'scrypt:32768:8:1$gZJ3gZJ3gZJ3gZJ3$c29e21bffd5c4bb4f2700358a2185834d1787383b08962b8a7409c21134a689b9861355a2978931b7f2b5b4a2cc5a8a7a8b9c0c1d2e3f4a5b6c7d8e9f0a1b2c3', 'Administrator Pusat', 'Super Admin', 'GAS');

-- --------------------------------------------------------
-- Struktur dari tabel `pengaturan`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `pengaturan` (
  `kunci` varchar(50) NOT NULL,
  `nilai` varchar(50) NOT NULL,
  PRIMARY KEY (`kunci`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT IGNORE INTO `pengaturan` (`kunci`, `nilai`) VALUES
('denda_aktif', '1') ON DUPLICATE KEY UPDATE `nilai`=`nilai`;

-- --------------------------------------------------------
-- Struktur dari tabel `coa` (Chart of Accounts / Akun Perkiraan)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `coa` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_code` varchar(20) NOT NULL,
  `account_name` varchar(100) NOT NULL,
  `kategori` enum('KAS','AKTIVA','KEWAJIBAN','EKUITAS','PENDAPATAN','BEBAN') NOT NULL,
  `anggaran_bulanan` decimal(15,2) DEFAULT '0.00',
  PRIMARY KEY (`id`),
  UNIQUE KEY `account_code` (`account_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Beberapa contoh data COA dasar
INSERT IGNORE INTO `coa` (`account_code`, `account_name`, `kategori`) VALUES
('1101', 'Kas Utama Cabang', 'KAS'), ('1102', 'Bank Cabang', 'KAS'),
('1201', 'Piutang Pinjaman Multiguna', 'AKTIVA'), ('1202', 'Piutang Pinjaman Tempo', 'AKTIVA'),
('1203', 'Piutang Pinjaman Gaji', 'AKTIVA'), ('1204', 'Piutang Pinjaman THR', 'AKTIVA'),
('2101', 'Titipan Dana Kematian', 'KEWAJIBAN'), ('2102', 'Titipan Jamsostek', 'KEWAJIBAN'),
('2103', 'Jaminan PPAP', 'KEWAJIBAN'),
('3101', 'Simpanan Pokok', 'EKUITAS'), ('3102', 'Simpanan Wajib', 'EKUITAS'),
('4101', 'Pendapatan Margin Multiguna', 'PENDAPATAN'), ('4102', 'Pendapatan Margin Tempo', 'PENDAPATAN'),
('4103', 'Pendapatan Margin Gaji', 'PENDAPATAN'), ('4104', 'Pendapatan Margin THR', 'PENDAPATAN'),
('4105', 'Pendapatan Adm/EDC', 'PENDAPATAN'), ('4106', 'Pendapatan Denda Multiguna/Tempo', 'PENDAPATAN'),
('4107', 'Pendapatan Denda Urgent', 'PENDAPATAN'),
('5101', 'Beban Gaji Karyawan', 'BEBAN'), ('5102', 'Beban Operasional Kantor', 'BEBAN');

-- --------------------------------------------------------
-- Struktur dari tabel `identitas` (Data Anggota)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `identitas` (
  `no_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `cabang` varchar(50) DEFAULT 'GAS',
  `tgl_lahir` date DEFAULT NULL,
  `no_telp` varchar(20) DEFAULT NULL,
  `nik_ktp` varchar(50) DEFAULT NULL,
  `nik_kk` varchar(50) DEFAULT NULL,
  `alamat_ktp` text DEFAULT NULL,
  `alamat_tagih` text DEFAULT NULL,
  `status_tempat_tinggal` varchar(50) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `password` varchar(255) DEFAULT NULL,
  `pt_instansi` varchar(100) DEFAULT NULL,
  `status_karyawan` varchar(50) DEFAULT NULL,
  `awal_bekerja` date DEFAULT NULL,
  `lama_kerja` varchar(50) DEFAULT NULL,
  `akhir_bekerja` date DEFAULT NULL,
  `jabatan` varchar(100) DEFAULT NULL,
  `no_jmo` varchar(50) DEFAULT NULL,
  `status_jmo` varchar(50) DEFAULT NULL,
  `no_rek` varchar(50) DEFAULT NULL,
  `bank` varchar(50) DEFAULT NULL,
  `nama_penanggung_jawab` varchar(100) DEFAULT NULL,
  `no_telp_penanggung_jawab` varchar(20) DEFAULT NULL,
  `no_rek_penanggung_jawab` varchar(50) DEFAULT NULL,
  `bank_penanggung_jawab` varchar(50) DEFAULT NULL,
  `kol` varchar(50) DEFAULT NULL,
  `kriteria` varchar(50) DEFAULT NULL,
  `marketing` varchar(100) DEFAULT NULL,
  `berkas_pdf` varchar(255) DEFAULT NULL,
  `berkas_jaminan` text DEFAULT NULL,
  `status_pernikahan` varchar(50) DEFAULT NULL,
  `alamat_penanggung_jawab` text DEFAULT NULL,
  `link_gmaps` text DEFAULT NULL,
  `lat` decimal(10,8) DEFAULT NULL,
  `lng` decimal(11,8) DEFAULT NULL,
  PRIMARY KEY (`no_anggota`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur dari tabel `simpanan`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `simpanan` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `nomor_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `simpanan_pokok` decimal(15,2) DEFAULT '0.00',
  `simpanan_wajib` decimal(15,2) DEFAULT '0.00',
  `total_simpanan` decimal(15,2) DEFAULT '0.00',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_nomor_anggota` (`nomor_anggota`),
  CONSTRAINT `fk_simpanan_anggota` FOREIGN KEY (`nomor_anggota`) REFERENCES `identitas` (`no_anggota`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur dari tabel `jurnal_umum` (Akuntansi)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `jurnal_umum` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tanggal` date NOT NULL,
  `coa_id` int(11) NOT NULL,
  `keterangan` varchar(255) NOT NULL,
  `debit` decimal(15,2) DEFAULT '0.00',
  `kredit` decimal(15,2) DEFAULT '0.00',
  `cabang` varchar(50) DEFAULT 'GAS',
  PRIMARY KEY (`id`),
  KEY `idx_coa_id` (`coa_id`),
  CONSTRAINT `fk_jurnal_coa` FOREIGN KEY (`coa_id`) REFERENCES `coa` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `pencairan_multiguna_tempo`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `pencairan_multiguna_tempo` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `no_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `jenis_pencairan` varchar(50) DEFAULT NULL,
  `tanggal_cair` date DEFAULT NULL,
  `tanggal_gajian` date DEFAULT NULL,
  `besar_pinjaman` decimal(15,2) DEFAULT 0.00,
  `potongan_angsuran` decimal(15,2) DEFAULT 0.00,
  `potongan_dana_urgent` decimal(15,2) DEFAULT 0.00,
  `biaya_jamsostek` decimal(15,2) DEFAULT 0.00,
  `potongan_simpanan_pokok` decimal(15,2) DEFAULT 0.00,
  `potongan_adm` decimal(15,2) DEFAULT 0.00,
  `potongan_dana_kematian` decimal(15,2) DEFAULT 0.00,
  `potongan_ppap` decimal(15,2) DEFAULT 0.00,
  `terima_bersih` decimal(15,2) DEFAULT 0.00,
  `tenor` int(11) DEFAULT 0,
  `is_restruktur` tinyint(1) DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `no_anggota` (`no_anggota`),
  CONSTRAINT `fk_pencairan_mt_anggota` FOREIGN KEY (`no_anggota`) REFERENCES `identitas` (`no_anggota`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `angsuran_multiguna_tempo`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `angsuran_multiguna_tempo` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `no_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `jenis_pinjaman` varchar(50) DEFAULT NULL,
  `tgl_pencairan` date DEFAULT NULL,
  `tgl_penggajian` date DEFAULT NULL,
  `jatuh_tempo` date DEFAULT NULL,
  `tgl_bayar` date DEFAULT NULL,
  `terima_bersih` decimal(15,2) DEFAULT 0.00,
  `besar_pinjaman` decimal(15,2) DEFAULT 0.00,
  `tenor` int(11) DEFAULT 0,
  `bunga_persen` decimal(5,2) DEFAULT 0.00,
  `margin` decimal(15,2) DEFAULT 0.00,
  `total_margin` decimal(15,2) DEFAULT 0.00,
  `sisa_pokok` decimal(15,2) DEFAULT 0.00,
  `sisa_margin` decimal(15,2) DEFAULT 0.00,
  `angsuran_ke` int(11) DEFAULT 0,
  `tagihan_pokok` decimal(15,2) DEFAULT 0.00,
  `tagihan_margin` decimal(15,2) DEFAULT 0.00,
  `tagihan_denda` decimal(15,2) DEFAULT 0.00,
  `angsuran_pokok` decimal(15,2) DEFAULT 0.00,
  `angsuran_margin` decimal(15,2) DEFAULT 0.00,
  `angsuran_denda` decimal(15,2) DEFAULT 0.00,
  `tunggakan_pokok` decimal(15,2) DEFAULT 0.00,
  `tunggakan_margin` decimal(15,2) DEFAULT 0.00,
  `od_hari` int(11) DEFAULT 0,
  `tunggakan_denda` decimal(15,2) DEFAULT 0.00,
  `status` varchar(20) DEFAULT 'BELUM BAYAR',
  `edc` varchar(50) DEFAULT '-',
  `gaji_awal` decimal(15,2) DEFAULT 0.00,
  `sisa_gaji` decimal(15,2) DEFAULT 0.00,
  `simpanan_wajib_bayar` decimal(15,2) DEFAULT 0.00,
  PRIMARY KEY (`id`),
  KEY `no_anggota` (`no_anggota`),
  KEY `status` (`status`),
  CONSTRAINT `fk_angsuran_mt_anggota` FOREIGN KEY (`no_anggota`) REFERENCES `identitas` (`no_anggota`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `pencairan_dana_urgent`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `pencairan_dana_urgent` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `no_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `jenis_dana_urgent` varchar(50) DEFAULT NULL,
  `tanggal_pencairan_dana_urgent` date DEFAULT NULL,
  `tanggal_pembayaran_dana_urgent` date DEFAULT NULL,
  `jumlah_dana_urgent` decimal(15,2) DEFAULT 0.00,
  `margin_dana_urgent` decimal(15,2) DEFAULT 0.00,
  PRIMARY KEY (`id`),
  KEY `no_anggota` (`no_anggota`),
  CONSTRAINT `fk_pencairan_urgent_anggota` FOREIGN KEY (`no_anggota`) REFERENCES `identitas` (`no_anggota`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `angsuran_dana_urgent`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `angsuran_dana_urgent` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `no_anggota` varchar(50) NOT NULL,
  `nama_anggota` varchar(100) NOT NULL,
  `jenis_dana_urgent` varchar(50) DEFAULT NULL,
  `tgl_pencairan` date DEFAULT NULL,
  `tanggal_jatuh_tempo` date DEFAULT NULL,
  `tgl_bayar` date DEFAULT NULL,
  `margin` decimal(15,2) DEFAULT 0.00,
  `tagihan_pokok` decimal(15,2) DEFAULT 0.00,
  `tagihan_margin` decimal(15,2) DEFAULT 0.00,
  `tagihan_denda` decimal(15,2) DEFAULT 0.00,
  `angsuran_pokok` decimal(15,2) DEFAULT 0.00,
  `angsuran_margin` decimal(15,2) DEFAULT 0.00,
  `angsuran_denda` decimal(15,2) DEFAULT 0.00,
  `tunggakan_pokok` decimal(15,2) DEFAULT 0.00,
  `tunggakan_margin` decimal(15,2) DEFAULT 0.00,
  `od_hari` int(11) DEFAULT 0,
  `tunggakan_denda` decimal(15,2) DEFAULT 0.00,
  `status` varchar(20) DEFAULT 'BELUM BAYAR',
  `edc` varchar(50) DEFAULT '-',
  `gaji_awal` decimal(15,2) DEFAULT 0.00,
  `sisa_gaji` decimal(15,2) DEFAULT 0.00,
  `simpanan_wajib_bayar` decimal(15,2) DEFAULT 0.00,
  PRIMARY KEY (`id`),
  KEY `no_anggota` (`no_anggota`),
  KEY `status` (`status`),
  CONSTRAINT `fk_angsuran_urgent_anggota` FOREIGN KEY (`no_anggota`) REFERENCES `identitas` (`no_anggota`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `pengeluaran_operasional`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `pengeluaran_operasional` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tanggal` date NOT NULL,
  `coa_sumber_dana_id` int(11) NOT NULL,
  `coa_beban_id` int(11) NOT NULL,
  `nominal` decimal(15,2) NOT NULL,
  `keterangan` varchar(255) DEFAULT NULL,
  `cabang` varchar(50) DEFAULT 'GAS',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `aset_operasional`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `aset_operasional` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `nama_aset` varchar(150) NOT NULL,
  `lokasi_cabang` varchar(50) NOT NULL,
  `tanggal_perolehan` date NOT NULL,
  `nilai_aset` decimal(15,2) NOT NULL,
  `kondisi` varchar(50) NOT NULL,
  `keterangan` text DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `approval_queue`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `approval_queue` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tipe_transaksi` varchar(50) DEFAULT NULL,
  `data_payload` text DEFAULT NULL,
  `diajukan_oleh` varchar(50) DEFAULT NULL,
  `tanggal_pengajuan` datetime DEFAULT current_timestamp(),
  `status` enum('PENDING','APPROVED','REJECTED') DEFAULT 'PENDING',
  `cabang` varchar(50) DEFAULT 'GAS',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `audit_logs`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(100) DEFAULT NULL,
  `role` varchar(50) DEFAULT NULL,
  `cabang` varchar(50) DEFAULT NULL,
  `aksi` varchar(255) DEFAULT NULL,
  `detail` text DEFAULT NULL,
  `created_at` datetime DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Struktur tabel `penanganan_macet`
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `penanganan_macet` (
  `no_anggota` varchar(50) NOT NULL,
  `progres_marketing` text DEFAULT NULL,
  `solusi` text DEFAULT NULL,
  `updated_at` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`no_anggota`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;