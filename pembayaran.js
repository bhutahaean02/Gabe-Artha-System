// Fungsi bantuan untuk mengubah angka menjadi format Rupiah
function formatRp(angka) {
    // Menambahkan penanganan untuk nilai negatif
    const number = Number(angka) || 0;
    const formatted = Math.abs(number).toLocaleString('id-ID');
    return number < 0 ? `- Rp ${formatted}` : `Rp ${formatted}`;
}

function getValInput(id) {
    let el = document.getElementById(id);
    if(!el || !el.value) return 0;
    return parseFloat(el.value.replace(/\./g, '').replace(/,/g, '.')) || 0;
}

function setValInput(id, val) {
    const el = document.getElementById(id);
    if (el) {
        el.value = val > 0 ? Number(val).toLocaleString('id-ID') : '';
    }
}

let allLoans = []; // PERUBAHAN: Variabel global untuk menyimpan semua pinjaman

// Load Data Anggota
document.addEventListener('DOMContentLoaded', function() {
    let t = new Date();
    document.getElementById('inputTanggalBayar').value = `${t.getFullYear()}-${String(t.getMonth()+1).padStart(2,'0')}-${String(t.getDate()).padStart(2,'0')}`;
    
    document.getElementById('inputTanggalBayar').addEventListener('change', function() {
        if(document.getElementById('selectAnggota').value) {
            document.getElementById('selectAnggota').dispatchEvent(new Event('change'));
        }
    });

    // Listener untuk input gaji awal keseluruhan
    const gajiAwalInput = document.getElementById('gaji_awal_keseluruhan');
    if (gajiAwalInput) {
        gajiAwalInput.addEventListener('input', hitungTotal);
    }

    fetch('/api/anggota_list')
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`Gagal memuat: Status ${r.status}`)))
        .then(res => {
            const select = document.getElementById('selectAnggota');
            if (res.status === 'success') {
                let optionsHtml = '<option value=""></option>';
                res.data.forEach(item => {
                    optionsHtml += `<option value="${item.no_anggota}">${item.no_anggota} - ${item.nama_anggota}</option>`;
                });
                select.innerHTML = optionsHtml;

                if (typeof $ !== 'undefined' && $.fn.select2) {
                    $('#selectAnggota').select2({
                        theme: 'bootstrap-5',
                        width: '100%',
                        placeholder: '-- Ketik Nama / No Anggota --'
                    }).on('select2:select', function (e) {
                        this.dispatchEvent(new Event('change'));
                    });
                }
            } else {
                select.innerHTML = `<option value="">Gagal: ${res.message || 'Format data salah'}</option>`;
            }
        })
        .catch(error => {
            console.error("Gagal memuat daftar anggota:", error);
            document.getElementById('selectAnggota').innerHTML = '<option value="">Error! Gagal memuat anggota.</option>';
        });
});

// PERUBAHAN BESAR: Event handler baru untuk 'selectAnggota'
document.getElementById('selectAnggota').addEventListener('change', function() {
    const no_anggota = this.value;
    const form = document.getElementById('formPembayaran');
    const container = document.getElementById('kartu-pembayaran-container');

    // Reset layout
    allLoans = [];
    container.innerHTML = '';
    form.style.display = 'none';
    document.getElementById('areaCetak').style.display = 'none';

    // Reset Gaji Awal field since we are not auto-filling it anymore
    document.getElementById('gaji_awal_keseluruhan').value = '';


    if (!no_anggota) {
        container.innerHTML = `<div class="text-center text-muted p-5 bg-light rounded border">
            <i class="fa-solid fa-arrow-up-wide-short fa-3x mb-3"></i>
            <h4 class="fw-light">Silakan pilih anggota untuk menampilkan tagihan.</h4>
        </div>`;
        hitungTotal(); // Reset total
        return;
    }

    fetch(`/api/info_tagihan/${no_anggota}?tanggal=${document.getElementById('inputTanggalBayar').value}`)
        .then(r => r.json())
        .then(res => {
            if (res.status !== 'success') throw new Error(res.message);

            allLoans = [
                ...(res.data_utama || []).map(loan => ({ ...loan, type: 'utama' })),
                ...(res.data_urgent || []).map(loan => ({ ...loan, type: 'urgent' }))
            ];
            
            form.style.display = 'block';
            renderLoanSections(allLoans); // Panggil fungsi render baru
            setupEventListeners(); // PERUBAHAN: Gunakan fungsi event listener baru
            hitungTotal();
        })
        .catch(error => {
            console.error('Error fetching info tagihan:', error);
            container.innerHTML = `<div class="alert alert-danger"><i class="fa-solid fa-circle-exclamation fa-2x mb-2 d-block text-danger"></i> Gagal memuat data tagihan: ${error.message}</div>`;
            form.style.display = 'none';
        });
});

// PERUBAHAN BESAR: Fungsi hitungTotal baru untuk kalkulasi dinamis
function hitungTotal() {
    let grandTotalKasir = 0;
    const gajiAwalInput = document.getElementById('gaji_awal_keseluruhan');
    const summaryTotalEl = document.getElementById('summary_total_bayar');
    const summarySisaEl = document.getElementById('summary_sisa_gaji');

    // Pengaman: Jika elemen ringkasan utama tidak ditemukan, hentikan fungsi untuk mencegah error.
    if (!summaryTotalEl || !summarySisaEl) {
        return;
    }

    const gajiAwalKeseluruhan = gajiAwalInput ? getNumValue(gajiAwalInput.value) : 0;

    document.querySelectorAll('.payment-card').forEach(card => {
        const checkBayar = card.querySelector('.check-bayar-card');
        
        // Hanya hitung kartu yang dicentang (atau kartu 'utama' yang tidak punya checkbox)
        if (!checkBayar || checkBayar.checked) {
            const getVal = (selector) => getNumValue(card.querySelector(selector).value);

            const pokok = getVal('.input-pokok');
            const margin = getVal('.input-margin');
            const denda = getVal('.input-denda');
            const simpanan = getVal('.input-simpanan');
            const edc = getVal('.input-edc');

            const totalPotonganKartu = pokok + margin + denda + simpanan + edc;
            
            // Update total per kartu (jika elemennya ada)
            const totalPotonganDisplay = card.querySelector('.total-potongan-display');
            if (totalPotonganDisplay) {
                totalPotonganDisplay.innerText = formatRp(totalPotonganKartu);
            }

            grandTotalKasir += totalPotonganKartu;
        }
    });

    // Update Grand Total di bawah
    summaryTotalEl.innerText = formatRp(grandTotalKasir);

    // Update Sisa Gaji Keseluruhan
    const sisaGaji = gajiAwalKeseluruhan - grandTotalKasir;
    summarySisaEl.innerText = formatRp(sisaGaji);
}

// Helper kecil untuk parsing nomor dari format Rupiah
function getNumValue(str) {
    if (!str) return 0;
    return parseFloat(str.replace(/[^0-9,]/g, '').replace(',', '.')) || 0;
}


// Eksekusi Submit Database
document.getElementById('formPembayaran').addEventListener('submit', function(e) {
    e.preventDefault();
    const btnSubmit = document.getElementById('btnSubmit');
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = 'Memproses...';

    const selectAnggota = document.getElementById('selectAnggota');
    const selectedOption = selectAnggota.options[selectAnggota.selectedIndex];
    const namaAnggotaFromSelect = selectedOption ? (selectedOption.text.split(' - ')[1] || 'Anggota') : 'Anggota';

    // PERUBAHAN BESAR: Payload dinamis dari kartu
    const payload = {
        no_anggota: selectAnggota.value,
        nama_anggota: namaAnggotaFromSelect,
        tanggal_bayar: document.getElementById('inputTanggalBayar').value,
        gaji_awal: getNumValue(document.getElementById('gaji_awal_keseluruhan').value),
        payments: []
    };

    document.querySelectorAll('.payment-card').forEach(card => {
        const checkBayar = card.querySelector('.check-bayar-card');
        
        // Hanya proses kartu yang dicentang untuk dibayar
        if (!checkBayar || checkBayar.checked) {
            const getVal = (selector) => getNumValue(card.querySelector(selector).value);

            const paymentData = {
                id_tagihan: card.dataset.idTagihan,
                jenis: card.dataset.type,
                nominal_pokok: getVal('.input-pokok'),
                nominal_margin: getVal('.input-margin'),
                nominal_denda: getVal('.input-denda'),
                simpanan_wajib: getVal('.input-simpanan'),
                edc: getVal('.input-edc'),
                // Ambil angsuran ke dari display di dalam kartu
                angsuran_ke: card.querySelector('.angsuran-ke-display') ? card.querySelector('.angsuran-ke-display').innerText : null
            };

            // Hanya kirim data pembayaran jika ada nominal yang dibayar
            if (paymentData.nominal_pokok > 0 || paymentData.nominal_margin > 0 || paymentData.nominal_denda > 0 || paymentData.simpanan_wajib > 0) {
                 payload.payments.push(paymentData);
            }
        }
    });

    if (payload.payments.length === 0) {
        alert('Tidak ada pembayaran yang dipilih atau diinput. Silakan centang kartu dan isi nominal pembayaran.');
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = '<i class="fa-solid fa-check-circle me-2"></i> Proses Bayar Angsuran';
        return;
    }

    fetch('/api/bayar_angsuran', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(result => {
        const alertBox = document.getElementById('alertBox');
        if(result.status === 'success') {
            alertBox.innerHTML = `<div class="alert alert-success fw-bold">${result.message}</div>`;
            $('#selectAnggota').val(null).trigger('change');
            
            const areaCetak = document.getElementById('areaCetak');
            const tombolCetak = document.getElementById('tombolCetak');
            areaCetak.style.display = 'block';
            tombolCetak.innerHTML = '';

            if(result.cetak_info && Array.isArray(result.cetak_info)) {
                result.cetak_info.forEach(info => {
                    if (info.id && info.jenis) {
                        const title = info.jenis === 'utama' ? 'Struk Angsuran Utama' : 'Struk Dana Urgent';
                        const color = info.jenis === 'utama' ? 'primary' : 'warning';
                        tombolCetak.innerHTML += `
                            <div class="mb-3 p-3 bg-light rounded border">
                                <h6 class="text-${color} fw-bold mb-2">${title}</h6>
                                <a href="/api/cetak_struk/${info.jenis}/${info.id}" target="_blank" class="btn btn-danger m-1"><i class="fa-solid fa-file-pdf me-1"></i> Cetak PDF</a>
                            </div>`;
                    }
                });
            }
        } else {
            alertBox.innerHTML = `<div class="alert alert-danger">Gagal: ${result.message}</div>`;
        }
    })
    .finally(() => {
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = '<i class="fa-solid fa-check-circle me-2"></i> Proses Bayar Angsuran';
        window.scrollTo(0,0);
    });
});


// --- FUNGSI-FUNGSI BARU UNTUK KARTU DINAMIS ---

function createPlaceholderCard(loanType, icon, colorClass) {
    const html = `
    <div class="card shadow-sm mb-4 bg-light">
        <div class="card-header ${colorClass} bg-opacity-10 d-flex justify-content-between align-items-center">
            <h5 class="mb-0 fw-bold ${colorClass}">
                <i class="fa-solid ${icon} me-2"></i>
                Pinjaman ${loanType}
            </h5>
        </div>
        <div class="card-body text-center text-muted py-4">
            <i class="fa-solid fa-circle-info fa-lg mb-2"></i>
            <p class="mb-0">Anggota tidak memiliki pinjaman ${loanType} yang aktif.</p>
        </div>
    </div>`;
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    return template.content.firstChild;
}

function renderLoanSections(loans) {
    const container = document.getElementById('kartu-pembayaran-container');
    container.innerHTML = ''; // Clear previous content

    const loanTypes = [
        { name: 'Multiguna', icon: 'fa-wallet', color: 'text-primary' },
        { name: 'Tempo', icon: 'fa-hourglass-half', color: 'text-info' },
        { name: 'Gaji', icon: 'fa-bolt', color: 'text-warning' },
        { name: 'THR', icon: 'fa-gifts', color: 'text-success' }
    ];

    loanTypes.forEach(typeInfo => {
        const matchingLoans = loans.filter(loan => 
            loan.jenis_pinjaman === typeInfo.name || loan.jenis_dana_urgent === typeInfo.name
        );

        if (matchingLoans.length > 0) {
            matchingLoans.forEach(loan => {
                const card = loan.type === 'utama' ? createUtamaCard(loan) : createUrgentCard(loan);
                container.appendChild(card);
            });
        } else {
            const placeholder = createPlaceholderCard(typeInfo.name, typeInfo.icon, typeInfo.color);
            container.appendChild(placeholder);
        }
    });
}

function createUtamaCard(loan) {
    const cardId = `card_utama_${loan.id}`;
    const sisaPokokUtama = Math.max(0, (loan.tagihan_pokok || 0) - (loan.angsuran_pokok || 0));
    const sisaMarginUtama = Math.max(0, (loan.tagihan_margin || 0) - (loan.angsuran_margin || 0));
    const dendaUtama = loan.kalkulasi_denda || 0;
    const edcDefault = (sisaPokokUtama > 0 || sisaMarginUtama > 0) ? 5000 : 0;
 
    // --- PERUBAHAN: Bedakan warna header & badge untuk tiap jenis pinjaman ---
    const isMultiguna = loan.jenis_pinjaman === 'Multiguna';
    const headerClass = isMultiguna ? 'bg-primary bg-opacity-10 text-primary' : 'bg-info bg-opacity-10 text-info';
    const badgeClass = isMultiguna ? 'bg-success' : 'bg-danger';
    const dendaInfo = dendaUtama > 0 ? `(Telat ${loan.od_hari} Hari)` : '';

    const tenorText = loan.tenor || 'N/A';
    const angsuranKeText = loan.angsuran_ke || 'N/A';
    const jatuhTempoText = loan.jatuh_tempo ? new Date(loan.jatuh_tempo).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';
    const tglCairText = loan.tgl_pencairan ? new Date(loan.tgl_pencairan).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';

    const html = `
    <div class="card shadow-sm mb-4 payment-card" id="${cardId}" data-id-tagihan="${loan.id}" data-jenis-pinjaman="${loan.jenis_pinjaman}" data-type="utama">
        <div class="card-header ${headerClass} p-3">
            <div class="d-flex justify-content-between align-items-center">
                <h5 class="mb-0 fw-bold d-flex align-items-center">
                    <i class="fa-solid ${isMultiguna ? 'fa-wallet' : 'fa-hourglass-half'} fa-fw me-2"></i>
                    Pinjaman ${loan.jenis_pinjaman}
                </h5>
                <div class="form-check form-switch">
                    <input class="form-check-input check-bayar-card" type="checkbox" role="switch" id="checkBayar_${loan.id}" checked>
                    <label class="form-check-label" for="checkBayar_${loan.id}">Bayar</label>
                </div>
            </div>
            <div class="d-flex justify-content-between align-items-center mt-1">
                <small class="text-muted">Cair: ${tglCairText}</small>
                <small class="text-muted">Tenor: ${tenorText} Bulan</small>
            </div>
        </div>
        <div class="card-body">
            <div class="row g-4">
                <div class="col-md-6">
                    <h6 class="fw-bold border-bottom pb-2 mb-3"><i class="fa-solid fa-file-invoice-dollar me-2 text-muted"></i>Rincian Tagihan Sistem</h6>
                    
                    <div class="row g-2" style="font-size: 0.9rem;">
                        <div class="col-7 text-muted">Angsuran Ke</div>
                        <div class="col-5 text-end fw-bold"><span class="angsuran-ke-display">${angsuranKeText}</span> / ${tenorText}</div>
                        <div class="col-7 text-muted">Jatuh Tempo</div>
                        <div class="col-5 text-end fw-bold">${jatuhTempoText}</div>
                        <div class="col-7 text-muted">Sisa Pokok Pinjaman</div>
                        <div class="col-5 text-end fw-bold">${formatRp(loan.sisa_pokok)}</div>
                        <div class="col-7 text-muted">Sisa Margin Pinjaman</div>
                        <div class="col-5 text-end fw-bold">${formatRp(loan.sisa_margin)}</div>
                    </div>

                    <hr class="my-3">
                    <h6 class="fw-bold text-primary mb-2">Tagihan Bulan Ini</h6>
                    <div class="list-group list-group-flush">
                        <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span>Tagihan Pokok</span>
                            <strong class="text-primary">${formatRp(loan.tagihan_pokok)}</strong>
                        </div>
                        <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span>Tagihan Margin</span>
                            <strong class="text-primary">${formatRp(loan.tagihan_margin)}</strong>
                        </div>
                         <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span class="text-danger">Tagihan Denda <small class="fw-normal">${dendaInfo}</small></span>
                            <strong class="text-danger">${formatRp(dendaUtama)}</strong>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <h6 class="fw-bold border-bottom pb-2 mb-3"><i class="fa-solid fa-keyboard me-2 text-muted"></i>Input Pembayaran Kasir</h6>
                    <div class="form-check form-switch mb-2" title="Aktifkan untuk mengisi nominal secara manual, misalnya untuk pembayaran sebagian atau lebih.">
                        <input class="form-check-input check-minus" type="checkbox" role="switch" id="checkMinus_${loan.id}">
                        <label class="form-check-label" for="checkMinus_${loan.id}">Buka Kunci Input (Edit Manual)</label>
                    </div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-money-bill-wave fa-fw me-2"></i>Pokok</span><input type="text" class="form-control format-rp input-kalkulasi input-pokok" value="${sisaPokokUtama > 0 ? sisaPokokUtama.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-hand-holding-dollar fa-fw me-2"></i>Margin</span><input type="text" class="form-control format-rp input-kalkulasi input-margin" value="${sisaMarginUtama > 0 ? sisaMarginUtama.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-triangle-exclamation fa-fw me-2"></i>Denda</span><input type="text" class="form-control format-rp input-kalkulasi input-denda" value="${dendaUtama > 0 ? dendaUtama.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-piggy-bank fa-fw me-2"></i>Titip Simp. Wajib</span><input type="text" class="form-control format-rp input-kalkulasi input-simpanan" value=""></div>
                    <div class="input-group mb-3"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-credit-card fa-fw me-2"></i>Biaya EDC</span><input type="text" class="form-control format-rp input-kalkulasi input-edc" value="${edcDefault > 0 ? edcDefault.toLocaleString('id-ID') : ''}"></div>
                    <hr>
                    <div class="d-flex justify-content-between align-items-center"><span class="fw-bold">Total Potongan Kartu Ini</span><span class="fw-bolder fs-5 text-danger total-potongan-display">Rp 0</span></div>
                </div>
            </div>
        </div>
    </div>`;
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    return template.content.firstChild;
}

function createUrgentCard(loan) {
    const cardId = `card_urgent_${loan.id}`;
    const sisaPokokUrgent = Math.max(0, (loan.tagihan_pokok || 0) - (loan.angsuran_pokok || 0));
    const sisaMarginUrgent = Math.max(0, (loan.tagihan_margin || 0) - (loan.angsuran_margin || 0));
    const dendaUrgent = loan.kalkulasi_denda || 0;
    const edcDefault = (sisaPokokUrgent > 0 || sisaMarginUrgent > 0) ? 5000 : 0;
    const jatuhTempoUrgent = loan.tanggal_jatuh_tempo ? new Date(loan.tanggal_jatuh_tempo).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';
    const tglCairText = loan.tgl_pencairan ? new Date(loan.tgl_pencairan).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';
    const dendaInfo = dendaUrgent > 0 ? `<small class="fw-normal">(Telat ${loan.od_hari} Hari)</small>` : '';

    const isGaji = loan.jenis_dana_urgent === 'Gaji';
    const headerClassUrgent = isGaji ? 'bg-warning bg-opacity-25 text-dark' : 'bg-success bg-opacity-25 text-dark';
    const iconUrgent = isGaji ? 'fa-bolt' : 'fa-gifts';

    const html = `
    <div class="card shadow-sm mb-4 payment-card" id="${cardId}" data-id-tagihan="${loan.id}" data-jenis-pinjaman="${loan.jenis_dana_urgent}" data-type="urgent">
        <div class="card-header ${headerClassUrgent} p-3">
            <div class="d-flex justify-content-between align-items-center">
                <h5 class="mb-0 fw-bold d-flex align-items-center">
                    <i class="fa-solid ${iconUrgent} fa-fw me-2"></i>
                    Dana Urgent ${loan.jenis_dana_urgent}
                </h5>
                <div class="form-check form-switch">
                    <input class="form-check-input check-bayar-card" type="checkbox" role="switch" id="checkBayar_${loan.id}" checked>
                    <label class="form-check-label" for="checkBayar_${loan.id}">Bayar</label>
                </div>
            </div>
            <div class="d-flex justify-content-between align-items-center mt-1">
                <small>Cair: ${tglCairText}</small>
                <small>Jatuh Tempo: ${jatuhTempoUrgent}</small>
            </div>
        </div>
        <div class="card-body">
            <div class="row g-4">
                <div class="col-md-6">
                    <h6 class="fw-bold border-bottom pb-2 mb-3"><i class="fa-solid fa-file-invoice-dollar me-2 text-muted"></i>Rincian Tagihan Sistem</h6>
                     <div class="list-group list-group-flush">
                        <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span>Tagihan Pokok</span>
                            <strong class="text-primary">${formatRp(loan.tagihan_pokok)}</strong>
                        </div>
                        <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span>Tagihan Margin</span>
                            <strong class="text-primary">${formatRp(loan.tagihan_margin)}</strong>
                        </div>
                         <div class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                            <span class="text-danger">Tagihan Denda ${dendaInfo}</span>
                            <strong class="text-danger">${formatRp(dendaUrgent)}</strong>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <h6 class="fw-bold border-bottom pb-2 mb-3"><i class="fa-solid fa-keyboard me-2 text-muted"></i>Input Pembayaran Kasir</h6>
                    <div class="form-check form-switch mb-2" title="Aktifkan untuk mengisi nominal secara manual, misalnya untuk pembayaran sebagian atau lebih.">
                        <input class="form-check-input check-minus" type="checkbox" role="switch" id="checkMinus_${loan.id}">
                        <label class="form-check-label" for="checkMinus_${loan.id}">Buka Kunci Input (Edit Manual)</label>
                    </div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-money-bill-wave fa-fw me-2"></i>Pokok</span><input type="text" class="form-control format-rp input-kalkulasi input-pokok" value="${sisaPokokUrgent > 0 ? sisaPokokUrgent.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-hand-holding-dollar fa-fw me-2"></i>Margin</span><input type="text" class="form-control format-rp input-kalkulasi input-margin" value="${sisaMarginUrgent > 0 ? sisaMarginUrgent.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-triangle-exclamation fa-fw me-2"></i>Denda</span><input type="text" class="form-control format-rp input-kalkulasi input-denda" value="${dendaUrgent > 0 ? dendaUrgent.toLocaleString('id-ID') : ''}" readonly></div>
                    <div class="input-group mb-2"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-piggy-bank fa-fw me-2"></i>Titip Simp. Wajib</span><input type="text" class="form-control format-rp input-kalkulasi input-simpanan" value=""></div>
                    <div class="input-group mb-3"><span class="input-group-text" style="width: 140px;"><i class="fa-solid fa-credit-card fa-fw me-2"></i>Biaya EDC</span><input type="text" class="form-control format-rp input-kalkulasi input-edc" value="${edcDefault > 0 ? edcDefault.toLocaleString('id-ID') : ''}"></div>
                    <hr>
                    <div class="d-flex justify-content-between align-items-center"><span class="fw-bold">Total Potongan Kartu Ini</span><span class="fw-bolder fs-5 text-danger total-potongan-display">Rp 0</span></div>
                </div>
            </div>
        </div>
    </div>`;
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    return template.content.firstChild;
}

function setupEventListeners() {
    const container = document.getElementById('kartu-pembayaran-container');
    if (!container) return;

    // Gunakan event delegation
    container.addEventListener('input', function(e) {
        // Format Rupiah
        if (e.target.classList.contains('format-rp')) {
            let val = e.target.value.replace(/[^0-9,]/g, '');
            if (val) {
                let parts = val.split(',');
                let intPart = parts[0].replace(/\./g, '').replace(/\B(?=(\d{3})+(?!\d))/g, ".");
                e.target.value = parts.length > 1 ? intPart + ',' + parts[1] : intPart;
            }
        }
        // Kalkulasi total jika ada input di field kalkulasi
        if (e.target.classList.contains('input-kalkulasi')) {
            hitungTotal();
        }
    });

    container.addEventListener('change', function(e) {
        // Toggle Readonly untuk input manual
        if (e.target.classList.contains('check-minus')) {
            const cardBody = e.target.closest('.card-body');
            const isLocked = !e.target.checked;
            cardBody.querySelector('.input-pokok').readOnly = isLocked;
            cardBody.querySelector('.input-margin').readOnly = isLocked;
            cardBody.querySelector('.input-denda').readOnly = isLocked;
        }
        // Toggle aktif/non-aktif kartu pembayaran
        if (e.target.classList.contains('check-bayar-card')) {
            const cardBody = e.target.closest('.card').querySelector('.card-body');
            if (e.target.checked) {
                cardBody.style.opacity = '1';
                cardBody.style.pointerEvents = 'auto';
            } else {
                cardBody.style.opacity = '0.5';
                cardBody.style.pointerEvents = 'none';
            }
            hitungTotal();
        }
    });
}

const toggleBayarCardListener = function() { // Fungsi ini masih relevan jika dipanggil dari tempat lain
    const cardBody = this.closest('.card').querySelector('.card-body');
    if (this.checked) {
        cardBody.style.opacity = '1';
        cardBody.style.pointerEvents = 'auto';
    } else {
        cardBody.style.opacity = '0.5';
        cardBody.style.pointerEvents = 'none';
    }
    hitungTotal();
};

// --- SCRIPT PELUNASAN KESELURUHAN ---
document.querySelectorAll('.format-rp-pelunasan').forEach(input => {
    input.addEventListener('input', function() {
        let rawVal = this.value.replace(/[^0-9]/g, '');
        if (rawVal) {
            this.value = Number(rawVal).toLocaleString('id-ID');
        } else {
            this.value = '0';
        }
    });
});

let pelunasanTotalTagihan = 0;
let pelunasanTotalSimpanan = 0;

function bukaModalPelunasan() {
    const no_anggota = document.getElementById('selectAnggota').value;
    if (!no_anggota) {
        alert('Silakan pilih anggota terlebih dahulu.');
        return;
    }
    
    document.getElementById('formPelunasan').reset();
    document.getElementById('pelunasan_no_anggota').value = no_anggota;
    document.getElementById('dispPelunasanSimpanan').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-muted"></i>';
    
    document.getElementById('pel_pokok_utama').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-muted"></i>';
    document.getElementById('pel_margin_utama').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-muted"></i>';
    document.getElementById('pel_pokok_urgent').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-muted"></i>';
    document.getElementById('pel_margin_urgent').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-muted"></i>';
    
    document.getElementById('warningSimpanan').classList.add('d-none');
    document.getElementById('btnSubmitPelunasan').disabled = false;
    
    const modal = new bootstrap.Modal(document.getElementById('modalPelunasan'));
    modal.show();
    
    fetch(`/api/cek_sisa_tagihan/${no_anggota}?tanggal=${document.getElementById('inputTanggalBayar').value}`)
    .then(res => res.json())
    .then(res => {
        if(res.status === 'success') {
            const d = res.data;
            pelunasanTotalTagihan = d.total_semua_tagihan;
            pelunasanTotalSimpanan = d.simpanan.total_simpanan;
            
            document.getElementById('pel_denda_utama').dataset.base = d.multiguna.denda;
            document.getElementById('pel_denda_urgent').dataset.base = d.urgent.denda;
            
            document.getElementById('pel_pokok_utama').innerText = formatRp(d.multiguna.sisa_pokok);
            document.getElementById('pel_margin_utama').innerText = formatRp(d.multiguna.sisa_margin);
            document.getElementById('pel_edc_utama').value = Number(d.multiguna.edc).toLocaleString('id-ID');
            document.getElementById('pel_denda_utama').value = Number(Math.round(d.multiguna.denda)).toLocaleString('id-ID');
            document.getElementById('pel_pokok_utama').dataset.val = d.multiguna.sisa_pokok;
            document.getElementById('pel_margin_utama').dataset.val = d.multiguna.sisa_margin;
            
            document.getElementById('pel_pokok_urgent').innerText = formatRp(d.urgent.sisa_pokok);
            document.getElementById('pel_margin_urgent').innerText = formatRp(d.urgent.sisa_margin);
            document.getElementById('pel_edc_urgent').value = Number(d.urgent.edc).toLocaleString('id-ID');
            document.getElementById('pel_denda_urgent').value = Number(Math.round(d.urgent.denda)).toLocaleString('id-ID');
            document.getElementById('pel_pokok_urgent').dataset.val = d.urgent.sisa_pokok;
            document.getElementById('pel_margin_urgent').dataset.val = d.urgent.sisa_margin;

            document.getElementById('dispPelunasanSimpanan').innerText = 'Rp ' + Number(pelunasanTotalSimpanan).toLocaleString('id-ID');
            
            document.getElementById('chkTanpaDendaPelunasan').checked = false;
            kalkulasiTotalPelunasan();

            if(pelunasanTotalTagihan <= 0) {
                alert('Anggota ini tidak memiliki sisa tagihan/pinjaman yang perlu dilunasi.');
                modal.hide();
            }
        } else {
            alert('Gagal mengambil data sisa tagihan: ' + res.message);
            modal.hide();
        }
    })
    .catch(err => {
        alert('Terjadi kesalahan jaringan.');
        console.error(err);
        modal.hide();
    });
}

function kalkulasiTotalPelunasan() {
    const getValFromId = (id) => parseFloat(document.getElementById(id).value.replace(/\./g, '').replace(/,/g, '.')) || 0;
    const getDatasetVal = (id) => parseFloat(document.getElementById(id).dataset.val) || 0;

    let p_utama = getDatasetVal('pel_pokok_utama');
    let m_utama = getDatasetVal('pel_margin_utama');
    let e_utama = getValFromId('pel_edc_utama');
    let d_utama = getValFromId('pel_denda_utama');
    let tot_utama = p_utama + m_utama + e_utama + d_utama;
    document.getElementById('pel_total_utama').innerText = formatRp(tot_utama);

    let p_urgent = getDatasetVal('pel_pokok_urgent');
    let m_urgent = getDatasetVal('pel_margin_urgent');
    let e_urgent = getValFromId('pel_edc_urgent');
    let d_urgent = getValFromId('pel_denda_urgent');
    let tot_urgent = p_urgent + m_urgent + e_urgent + d_urgent;
    document.getElementById('pel_total_urgent').innerText = formatRp(tot_urgent);

    let grand_total = tot_utama + tot_urgent;
    pelunasanTotalTagihan = grand_total;
    document.getElementById('pel_grand_total').innerText = formatRp(grand_total);

    document.getElementById('metode_pelunasan').dispatchEvent(new Event('change'));
}

['pel_edc_utama', 'pel_denda_utama', 'pel_edc_urgent', 'pel_denda_urgent'].forEach(id => {
    document.getElementById(id).addEventListener('input', kalkulasiTotalPelunasan);
});

document.getElementById('chkTanpaDendaPelunasan').addEventListener('change', function() {
    if(this.checked) {
        document.getElementById('pel_denda_utama').value = "0";
        document.getElementById('pel_denda_urgent').value = "0";
        document.getElementById('pel_denda_utama').readOnly = true;
        document.getElementById('pel_denda_urgent').readOnly = true;
    } else {
        document.getElementById('pel_denda_utama').value = Number(Math.round(document.getElementById('pel_denda_utama').dataset.base)).toLocaleString('id-ID');
        document.getElementById('pel_denda_urgent').value = Number(Math.round(document.getElementById('pel_denda_urgent').dataset.base)).toLocaleString('id-ID');
        document.getElementById('pel_denda_utama').readOnly = false;
        document.getElementById('pel_denda_urgent').readOnly = false;
    }
    kalkulasiTotalPelunasan();
});

document.getElementById('metode_pelunasan').addEventListener('change', function() {
    const areaKekurangan = document.getElementById('areaKekuranganTunai');
    const inputTunai = document.getElementById('inputPelunasanTunai');
    const btnSubmit = document.getElementById('btnSubmitPelunasan');
    
    document.getElementById('warningSimpanan').classList.add('d-none');

    if (this.value === 'simpanan') {
        if (pelunasanTotalSimpanan < pelunasanTotalTagihan) {
            let kekurangan = pelunasanTotalTagihan - pelunasanTotalSimpanan;
            inputTunai.value = Number(kekurangan).toLocaleString('id-ID');
            areaKekurangan.style.display = 'block';
            btnSubmit.innerHTML = '<i class="fa-solid fa-check me-1"></i> Proses (Simpanan + Tunai)';
        } else {
            inputTunai.value = "0";
            areaKekurangan.style.display = 'none';
            btnSubmit.innerHTML = '<i class="fa-solid fa-check me-1"></i> Eksekusi Pelunasan';
        }
    } else {
        inputTunai.value = Number(pelunasanTotalTagihan).toLocaleString('id-ID');
        areaKekurangan.style.display = 'block';
        btnSubmit.innerHTML = '<i class="fa-solid fa-check me-1"></i> Eksekusi Pelunasan';
    }
    btnSubmit.disabled = false;
});

document.getElementById('formPelunasan').addEventListener('submit', function(e) {
    e.preventDefault();
    const metode = document.getElementById('metode_pelunasan').value;
    if(!confirm(`PERINGATAN!\nAnda yakin ingin mengeksekusi Pelunasan untuk anggota ini menggunakan metode ${metode.toUpperCase()}?\nAksi ini akan membuat status pinjaman terkait menjadi LUNAS.`)) return;
    
    const btnSubmit = document.getElementById('btnSubmitPelunasan');
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i> Memproses...';
    
    const payload = {
        no_anggota: document.getElementById('pelunasan_no_anggota').value,
        tanggal_bayar: document.getElementById('inputTanggalBayar').value,
        metode_pelunasan: metode,
        edc_utama: document.getElementById('pel_edc_utama').value.replace(/[^0-9]/g, ''),
        edc_urgent: document.getElementById('pel_edc_urgent').value.replace(/[^0-9]/g, ''),
        denda_utama: document.getElementById('pel_denda_utama').value.replace(/[^0-9]/g, ''),
        denda_urgent: document.getElementById('pel_denda_urgent').value.replace(/[^0-9]/g, ''),
        nominal_bayar_tunai: document.getElementById('inputPelunasanTunai').value.replace(/[^0-9]/g, '')
    };
    
    fetch('/api/pelunasan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            alert(data.message);
            bootstrap.Modal.getInstance(document.getElementById('modalPelunasan')).hide();
            document.getElementById('selectAnggota').dispatchEvent(new Event('change'));
        
        const areaCetak = document.getElementById('areaCetak');
        const tombolCetak = document.getElementById('tombolCetak');
        areaCetak.style.display = 'block';
        tombolCetak.innerHTML = `
            <div class="mb-3 p-3 bg-danger bg-opacity-10 rounded border border-danger">
                <h6 class="text-danger fw-bold mb-2">Struk Pelunasan Dipercepat Keseluruhan</h6>
                <a href="/api/cetak_pelunasan/${data.cetak_info.no_anggota}/${data.cetak_info.tanggal_bayar}" target="_blank" class="btn btn-danger m-1"><i class="fa-solid fa-file-pdf me-1"></i> Cetak Bukti Pelunasan</a>
            </div>
        `;
        } else {
            alert('Gagal melakukan pelunasan: ' + data.message);
        }
    }).catch(err => {
        alert('Terjadi kesalahan sistem saat memproses pelunasan.');
        console.error(err);
    }).finally(() => {
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = '<i class="fa-solid fa-check me-1"></i> Eksekusi Pelunasan';
    });
});