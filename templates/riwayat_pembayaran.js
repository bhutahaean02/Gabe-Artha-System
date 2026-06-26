document.addEventListener('DOMContentLoaded', function() {
    const today = new Date();
    const firstDayOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);

    // Set default filter dates
    document.getElementById('filterStartDate').valueAsDate = firstDayOfMonth;
    document.getElementById('filterEndDate').valueAsDate = today;

    // Load initial data
    fetchData();

    // Add event listener to filter button
    document.getElementById('btnFilter').addEventListener('click', fetchData);

    // Add event listener for the new export button
    document.getElementById('btnExport').addEventListener('click', exportData);
});

function exportData() {
    const startDate = document.getElementById('filterStartDate').value;
    const endDate = document.getElementById('filterEndDate').value;
    const nama = document.getElementById('filterNama').value;
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate, nama_anggota: nama });
    window.location.href = `/api/export_riwayat_pembayaran?${params.toString()}`;
}

function formatRp(angka) {
    return `Rp ${Number(angka || 0).toLocaleString('id-ID')}`;
}

function fetchData() {
    const startDate = document.getElementById('filterStartDate').value;
    const endDate = document.getElementById('filterEndDate').value;
    const nama = document.getElementById('filterNama').value;
    const loadingIndicator = document.getElementById('loadingIndicator');
    const tableBody = document.getElementById('tabelBody');
    const btnFilter = document.getElementById('btnFilter');

    // Show loading and disable button
    loadingIndicator.style.display = 'block';
    tableBody.innerHTML = '';
    btnFilter.disabled = true;
    btnFilter.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-2"></i>Memuat...';

    // Reset totals
    document.getElementById('totalPokok').innerText = '';
    document.getElementById('totalMargin').innerText = '';
    document.getElementById('totalDenda').innerText = '';
    document.getElementById('totalEdc').innerText = '';
    document.getElementById('totalSimpanan').innerText = '';
    document.getElementById('grandTotal').innerText = '';

    const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        nama_anggota: nama
    });

    fetch(`/api/riwayat_pembayaran?${params.toString()}`)
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                renderTable(result.data);
            } else {
                tableBody.innerHTML = `<tr><td colspan="11" class="text-center text-danger">Gagal memuat data: ${result.message}</td></tr>`;
            }
        })
        .catch(error => {
            console.error('Error fetching data:', error);
            tableBody.innerHTML = `<tr><td colspan="11" class="text-center text-danger">Terjadi kesalahan jaringan.</td></tr>`;
        })
        .finally(() => {
            // Hide loading and enable button
            loadingIndicator.style.display = 'none';
            btnFilter.disabled = false;
            btnFilter.innerHTML = '<i class="fa-solid fa-magnifying-glass me-2"></i>Terapkan Filter';
        });
}

function renderTable(data) {
    const tableBody = document.getElementById('tabelBody');
    if (data.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="11" class="text-center">Tidak ada data pembayaran pada periode ini.</td></tr>`;
        return;
    }

    let html = '';
    let totalPokok = 0, totalMargin = 0, totalDenda = 0, totalEdc = 0, totalSimpanan = 0, grandTotal = 0;

    data.forEach(row => {
        const pokok = parseFloat(row.angsuran_pokok || 0);
        const margin = parseFloat(row.angsuran_margin || 0);
        const denda = parseFloat(row.angsuran_denda || 0);
        const edc = parseFloat(row.edc_val || 0);
        const simpanan = parseFloat(row.simpanan_wajib_bayar || 0);
        const totalBayar = parseFloat(row.total_bayar || 0);

        totalPokok += pokok;
        totalMargin += margin;
        totalDenda += denda;
        totalEdc += edc;
        totalSimpanan += simpanan;
        grandTotal += totalBayar;

        html += `
            <tr>
                <td>${new Date(row.tgl_bayar).toLocaleDateString('id-ID')}</td>
                <td>${row.no_anggota}</td>
                <td>${row.nama_anggota}</td>
                <td>${row.jenis}</td>
                <td>${row.angsuran_ke}</td>
                <td class="text-end">${pokok > 0 ? pokok.toLocaleString('id-ID') : '-'}</td>
                <td class="text-end">${margin > 0 ? margin.toLocaleString('id-ID') : '-'}</td>
                <td class="text-end">${denda > 0 ? denda.toLocaleString('id-ID') : '-'}</td>
                <td class="text-end">${edc > 0 ? edc.toLocaleString('id-ID') : '-'}</td>
                <td class="text-end">${simpanan > 0 ? simpanan.toLocaleString('id-ID') : '-'}</td>
                <td class="text-end fw-bold">${totalBayar > 0 ? totalBayar.toLocaleString('id-ID') : '-'}</td>
            </tr>
        `;
    });

    tableBody.innerHTML = html;

    // Update totals in the footer
    document.getElementById('totalPokok').innerText = formatRp(totalPokok);
    document.getElementById('totalMargin').innerText = formatRp(totalMargin);
    document.getElementById('totalDenda').innerText = formatRp(totalDenda);
    document.getElementById('totalEdc').innerText = formatRp(totalEdc);
    document.getElementById('totalSimpanan').innerText = formatRp(totalSimpanan);
    document.getElementById('grandTotal').innerText = formatRp(grandTotal);
}