import unittest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

# Menambahkan direktori root proyek ke path Python agar bisa mengimpor 'app'
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestBatalAngsuran(unittest.TestCase):

    def setUp(self):
        """Menyiapkan test client dan mock untuk koneksi database."""
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test_secret_key'
        self.client = app.test_client()

    @patch('api_transaksi.get_db_connection')
    def test_batal_angsuran_multiguna_lengkap(self, mock_get_db_connection):
        """
        Menguji pembatalan angsuran 'Multiguna' yang mencakup semua komponen:
        - Pembayaran Pokok
        - Pembayaran Margin
        - Pembayaran Denda
        - Biaya EDC
        - Titipan Simpanan Wajib
        """
        # --- ARRANGE (Persiapan data dan mock) ---

        # 1. Mock koneksi database dan cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # 2. Data angsuran yang akan 'ditemukan' di database saat query SELECT
        id_tagihan_to_cancel = 123
        no_anggota_test = "GAS-240626-001"
        nama_anggota_test = "Budi Tester"
        cabang_test = "GAS"
        
        mock_angsuran_row = {
            'id': id_tagihan_to_cancel,
            'no_anggota': no_anggota_test,
            'nama_anggota': nama_anggota_test,
            'angsuran_pokok': 500000.00,
            'angsuran_margin': 125000.00,
            'angsuran_denda': 50000.00,
            'tgl_bayar': datetime(2026, 6, 20).date(),
            'edc': '5000.00',
            'simpanan_wajib_bayar': 25000.00,
            'jenis_pinjaman': 'Multiguna'
        }
        
        mock_identitas_row = {
            'nama_anggota': nama_anggota_test,
            'cabang': cabang_test
        }

        # 3. Konfigurasi mock cursor untuk mengembalikan data di atas
        # Urutan fetch: angsuran_multiguna_tempo -> identitas -> COA IDs
        mock_cursor.fetchone.side_effect = [
            mock_angsuran_row,
            mock_identitas_row,
            (1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,) # Dummy COA ID untuk 8 jurnal
        ]

        # --- ACT (Menjalankan pemanggilan API) ---
        with self.client.session_transaction() as sess:
            sess['role'] = 'Manager'
            sess['cabang'] = 'GAS' # Admin bisa dari cabang mana saja
            sess['nama_lengkap'] = 'Manager Test'

        response = self.client.post(
            '/api/batal_angsuran',
            data=json.dumps({
                'jenis': 'utama',
                'id_tagihan': id_tagihan_to_cancel,
                'alasan': 'Unit Test',
                'is_approval_execution': True # Simulasi eksekusi langsung
            }),
            content_type='application/json'
        )

        # --- ASSERT (Verifikasi hasil) ---

        # 1. Cek respons HTTP
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('berhasil dibatalkan', response_data['message'])

        # 2. Verifikasi query UPDATE utama pada tabel angsuran
        update_angsuran_call = next(call for call in mock_cursor.execute.call_args_list if "UPDATE angsuran_multiguna_tempo" in call[0][0])
        expected_update_query = "UPDATE angsuran_multiguna_tempo SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0, simpanan_wajib_bayar=0 WHERE id=%s"
        self.assertEqual(" ".join(update_angsuran_call[0][0].split()), " ".join(expected_update_query.split()))
        self.assertEqual(update_angsuran_call[0][1], (id_tagihan_to_cancel,))

        # 3. Verifikasi query UPDATE pada tabel simpanan
        update_simpanan_call = next(call for call in mock_cursor.execute.call_args_list if "UPDATE simpanan SET simpanan_wajib" in call[0][0])
        simpanan_batal_val = mock_angsuran_row['simpanan_wajib_bayar']
        self.assertEqual(update_simpanan_call[0][1], (simpanan_batal_val, simpanan_batal_val, no_anggota_test))

        # 4. Verifikasi semua entri jurnal pembalik
        # Jurnal harus dicatat di cabang anggota, bukan cabang admin yang membatalkan.
        expected_cabang = cabang_test
        journal_calls = [call for call in mock_cursor.execute.call_args_list if "INSERT INTO jurnal_umum" in call[0][0]]
        
        self.assertEqual(len(journal_calls), 8, "Harusnya ada 8 entri jurnal pembalik untuk multiguna")

        # Helper untuk memeriksa entri jurnal
        def assert_journal_entry(keterangan_substr, debit, kredit, cabang):
            found = any(
                keterangan_substr in call[0][1][2] and call[0][1][3] == debit and call[0][1][4] == kredit and call[0][1][5] == cabang
                for call in journal_calls
            )
            self.assertTrue(found, f"Jurnal untuk '{keterangan_substr}' dengan Debit={debit}, Kredit={kredit}, Cabang={cabang} tidak ditemukan.")

        assert_journal_entry('Batal Angsuran Multiguna', 0, 500000 + 125000 + 50000, expected_cabang)
        assert_journal_entry('Batal EDC/Admin Multiguna', 0, 5000.00, expected_cabang)
        assert_journal_entry('Batal Pelunasan Pokok', 500000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan Margin', 125000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan Denda', 50000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan EDC/Admin', 5000.00, 0, expected_cabang)
        assert_journal_entry('Batal Kas Simpanan Wajib', 0, 25000.00, expected_cabang)
        assert_journal_entry('Batal Simpanan Wajib', 25000.00, 0, expected_cabang)

        # 5. Verifikasi transaksi di-commit
        mock_conn.commit.assert_called_once()

        # 6. Verifikasi Audit Log
        audit_log_call = next((call for call in mock_cursor.execute.call_args_list if "INSERT INTO audit_logs" in call[0][0]), None)
        self.assertIsNotNone(audit_log_call, "Entri audit log tidak dibuat.")
        self.assertEqual(audit_log_call[0][1][2], expected_cabang, "Cabang pada audit log salah.")
        self.assertEqual(audit_log_call[0][1][3], 'BATAL_ANGSURAN', "Aksi pada audit log salah.")
        self.assertIn('"alasan": "Unit Test"', audit_log_call[0][1][4], "Detail pada audit log salah.")

    @patch('api_transaksi.get_db_connection')
    def test_batal_angsuran_urgent_lengkap(self, mock_get_db_connection):
        """
        Menguji pembatalan angsuran 'Urgent' yang mencakup semua komponen:
        - Pokok, Margin, Denda, EDC, dan Simpanan Wajib.
        """
        # --- ARRANGE ---
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        id_tagihan_urgent = 456
        no_anggota_test = "GAS-240626-002"
        nama_anggota_test = "Siti Urgent"
        cabang_test = "TAMBAK"

        mock_angsuran_urgent_row = {
            'id': id_tagihan_urgent,
            'no_anggota': no_anggota_test,
            'nama_anggota': nama_anggota_test,
            'angsuran_pokok': 1000000.00,
            'angsuran_margin': 200000.00,
            'angsuran_denda': 10000.00,
            'tgl_bayar': datetime(2026, 6, 21).date(),
            'edc': '5000.00',
            'simpanan_wajib_bayar': 10000.00,
            'jenis_dana_urgent': 'Gaji'
        }
        
        mock_identitas_row = {
            'nama_anggota': nama_anggota_test,
            'cabang': cabang_test
        }

        # Urutan fetch: angsuran_dana_urgent -> identitas -> COA IDs
        mock_cursor.fetchone.side_effect = [
            mock_angsuran_urgent_row,
            mock_identitas_row,
            (10,), (11,), (12,), (13,), (14,), (15,), (16,), (17,) # Dummy COA IDs
        ]

        # --- ACT ---
        with self.client.session_transaction() as sess:
            sess['role'] = 'Manager'
            sess['cabang'] = 'GAS' # Simulating admin from a different branch
            sess['nama_lengkap'] = 'Manager Test'

        response = self.client.post(
            '/api/batal_angsuran',
            data=json.dumps({
                'jenis': 'urgent',
                'id_tagihan': id_tagihan_urgent,
                'alasan': 'Unit Test Urgent',
                'is_approval_execution': True
            }),
            content_type='application/json'
        )

        # --- ASSERT ---
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        self.assertEqual(response_data['status'], 'success')

        # Verifikasi UPDATE pada angsuran_dana_urgent
        update_angsuran_call = next(call for call in mock_cursor.execute.call_args_list if "UPDATE angsuran_dana_urgent" in call[0][0])
        expected_update_query = "UPDATE angsuran_dana_urgent SET angsuran_pokok=0, angsuran_margin=0, angsuran_denda=0, tagihan_denda=0, status='BELUM BAYAR', tgl_bayar=NULL, edc='-', sisa_gaji=0, simpanan_wajib_bayar=0 WHERE id=%s"
        self.assertEqual(" ".join(update_angsuran_call[0][0].split()), " ".join(expected_update_query.split()))
        self.assertEqual(update_angsuran_call[0][1], (id_tagihan_urgent,))

        # Verifikasi UPDATE pada simpanan
        update_simpanan_call = next(call for call in mock_cursor.execute.call_args_list if "UPDATE simpanan SET simpanan_wajib" in call[0][0])
        simpanan_batal_val = mock_angsuran_urgent_row['simpanan_wajib_bayar']
        self.assertEqual(update_simpanan_call[0][1], (simpanan_batal_val, simpanan_batal_val, no_anggota_test))

        # Verifikasi jurnal pembalik
        journal_calls = [call for call in mock_cursor.execute.call_args_list if "INSERT INTO jurnal_umum" in call[0][0]]
        self.assertEqual(len(journal_calls), 8, "Harusnya ada 8 entri jurnal pembalik untuk urgent")

        def assert_journal_entry(keterangan_substr, debit, kredit, cabang):
            found = any(
                keterangan_substr in call[0][1][2] and call[0][1][3] == debit and call[0][1][4] == kredit and call[0][1][5] == cabang
                for call in journal_calls
            )
            self.assertTrue(found, f"Jurnal untuk '{keterangan_substr}' dengan Debit={debit}, Kredit={kredit}, Cabang={cabang} tidak ditemukan.")

        expected_cabang = cabang_test 
        
        assert_journal_entry('Batal Angsuran Urgent Gaji', 0, 1000000 + 200000 + 10000, expected_cabang)
        assert_journal_entry('Batal EDC/Admin Urgent Gaji', 0, 5000.00, expected_cabang)
        assert_journal_entry('Batal Pelunasan Pokok Urgent Gaji', 1000000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan Margin Urgent Gaji', 200000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan Denda Urgent Gaji', 10000.00, 0, expected_cabang)
        assert_journal_entry('Batal Pendapatan EDC/Admin Urgent Gaji', 5000.00, 0, expected_cabang)
        assert_journal_entry('Batal Kas Simpanan Wajib', 0, 10000.00, expected_cabang)
        assert_journal_entry('Batal Simpanan Wajib', 10000.00, 0, expected_cabang)

        # Verifikasi audit log
        audit_log_call = next((call for call in mock_cursor.execute.call_args_list if "INSERT INTO audit_logs" in call[0][0]), None)
        self.assertIsNotNone(audit_log_call, "Entri audit log tidak dibuat untuk urgent.")
        self.assertEqual(audit_log_call[0][1][3], 'BATAL_ANGSURAN')
        self.assertIn('"alasan": "Unit Test Urgent"', audit_log_call[0][1][4])
        self.assertEqual(audit_log_call[0][1][2], expected_cabang)

        mock_conn.commit.assert_called_once()