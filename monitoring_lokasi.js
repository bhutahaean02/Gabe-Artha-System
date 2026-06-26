document.addEventListener('DOMContentLoaded', function () {
    // 1. Inisialisasi Peta
    const map = L.map('map').setView([-7.5, 110.0], 7); // Set view to center of Java Island

    // 2. Tambahkan Basemap
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    // OPTIMASI: Buat ikon sekali saja dan cache
    const icons = {
        'LANCAR': new L.Icon({ iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] }),
        'Kurang Lancar': new L.Icon({ iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-yellow.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] }),
        'Macet': new L.Icon({ iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] }),
        'WO': new L.Icon({ iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] }),
        'default': new L.Icon({ iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] })
    };

    // 3. Inisialisasi MarkerCluster Group untuk performa tinggi
    const markersCluster = L.markerClusterGroup({
        chunkedLoading: true, // PENTING: untuk performa saat menambah banyak marker
        maxClusterRadius: 70
    });

    const layerGroups = {
        'LANCAR': L.layerGroup(),
        'Kurang Lancar': L.layerGroup(),
        'Macet': L.layerGroup(),
        'WO': L.layerGroup(),
        'default': L.layerGroup() // Fallback untuk status lain
    };

    const markers = {}; // To store markers by no_anggota
    let allAnggotaData = []; // To store all member data for searching

    // 4. Logika Pencarian Anggota (diperbarui untuk MarkerCluster)
    const searchInput = document.getElementById('search-anggota');
    const searchBtn = document.getElementById('btn-search-anggota');

    function performSearch() {
        const searchTerm = searchInput.value.trim().toLowerCase();
        if (!searchTerm) return;

        const foundAnggota = allAnggotaData.find(anggota =>
            anggota.nama_anggota.toLowerCase().includes(searchTerm) ||
            anggota.no_anggota.toLowerCase().includes(searchTerm)
        );

        if (foundAnggota) {
            const marker = markers[foundAnggota.no_anggota];
            if (marker) {
                // Gunakan metode dari MarkerCluster untuk zoom ke marker
                markersCluster.zoomToShowLayer(marker, () => {
                    marker.openPopup();
                });
            } else {
                alert('Anggota ditemukan, tetapi tidak memiliki marker di peta (kemungkinan terfilter).');
            }
        } else {
            alert('Anggota dengan nama atau nomor tersebut tidak ditemukan di peta.');
        }
    }

    if (searchBtn && searchInput) {
        searchBtn.addEventListener('click', performSearch);
        searchInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
    }

    // 5. Logika Filter (diperbarui untuk MarkerCluster)
    const filterContainer = document.getElementById('map-filters');
    if (filterContainer) {
        const filters = filterContainer.querySelectorAll('.filter-check');
        const filterAll = document.getElementById('filter-all');

        function updateMapLayers() {
            markersCluster.clearLayers(); // Hapus semua marker dari cluster
            const markersToAdd = [];

            filters.forEach(filter => {
                if (filter.id !== 'filter-all' && filter.checked) {
                    const status = filter.value;
                    if (layerGroups[status]) {
                        markersToAdd.push(...layerGroups[status].getLayers());
                    }
                }
            });
            markersCluster.addLayers(markersToAdd); // Tambahkan marker yang terfilter ke cluster
        }

        filterContainer.addEventListener('change', function (e) {
            const target = e.target;
            if (target.matches('.filter-check')) {
                if (target.id === 'filter-all') {
                    // Jika 'Semua' diubah, samakan state checkbox lain
                    filters.forEach(f => {
                        if (f.id !== 'filter-all') f.checked = target.checked;
                    });
                } else {
                    // Jika checkbox individu diubah, update 'Semua'
                    if (!target.checked) {
                        filterAll.checked = false;
                    } else {
                        let allOthersChecked = true;
                        filters.forEach(f => {
                            if (f.id !== 'filter-all' && !f.checked) {
                                allOthersChecked = false;
                            }
                        });
                        filterAll.checked = allOthersChecked;
                    }
                }
                updateMapLayers();
            }
        });
    }

    // 6. Ambil data dari API dan render peta
    fetch('/api/koordinat_anggota')
        .then(response => {
            if (!response.ok) {
                throw new Error('Gagal mengambil data dari server.');
            }
            return response.json();
        })
        .then(result => {
            if (result.status !== 'success') {
                throw new Error(result.message || 'Format data dari API salah.');
            }

            allAnggotaData = result.data;
            if (!allAnggotaData || allAnggotaData.length === 0) {
                document.getElementById('map').innerHTML = `<div class="alert alert-warning m-3">Tidak ada data anggota dengan koordinat valid untuk ditampilkan.</div>`;
                if (filterContainer) filterContainer.closest('.card').style.display = 'none';
                return;
            }

            // Looping dan buat semua marker, simpan di object `markers` dan `layerGroups`
            allAnggotaData.forEach(anggota => {
                const customIcon = icons[anggota.status] || icons['default'];
                const navigationUrl = `https://www.google.com/maps/dir/?api=1&destination=${anggota.lat},${anggota.lon}`;
                const popupContent = `
                    <div class="popup-header">${anggota.nama_anggota}</div>
                    <b>Status:</b> ${anggota.status}<br>
                    <b>Alamat:</b> ${anggota.alamat_tagih || 'N/A'}<br><br>
                    <a href="${navigationUrl}" target="_blank" class="btn btn-primary btn-sm w-100"><i class="fa-solid fa-diamond-turn-right me-1"></i> Navigasi</a>
                `;
                const marker = L.marker([anggota.lat, anggota.lon], { icon: customIcon })
                    .bindPopup(popupContent)
                    .bindTooltip(anggota.nama_anggota, {
                        permanent: true, // Agar nama selalu terlihat
                        direction: 'top', // Posisi di atas marker
                        offset: [0, -41], // Sesuaikan offset agar pas di atas ujung ikon
                        className: 'leaflet-tooltip-member' // Kelas CSS kustom untuk styling (opsional)
                    });
                
                // Simpan marker untuk referensi nanti (pencarian, filter)
                markers[anggota.no_anggota] = marker; // Simpan marker untuk pencarian
                const group = layerGroups[anggota.status] || layerGroups['default'];
                marker.addTo(group);
            });

            // Tambahkan semua layer group ke cluster group
            Object.values(layerGroups).forEach(group => markersCluster.addLayer(group));
            map.addLayer(markersCluster);

            // STABILITAS & UX: Zoom otomatis ke area yang berisi semua marker
            try {
                map.fitBounds(markersCluster.getBounds(), { padding: [50, 50] });
            } catch(e) {
                // Fallback jika hanya ada 1 marker atau terjadi error
                console.warn("Could not fit bounds, using default view.", e);
            }

            // SOLUSI 3: Panggil invalidateSize() untuk memaksa Leaflet menghitung ulang ukuran
            // kontainernya. Penggunaan setTimeout memberikan jeda agar elemen lain (seperti sidebar)
            // selesai dirender terlebih dahulu sebelum peta diukur.
            setTimeout(function () {
                map.invalidateSize();
            }, 400);

        })
        .catch(error => {
            console.error("Error:", error);
            const mapDiv = document.getElementById('map');
            mapDiv.innerHTML = `<div class="alert alert-danger m-3">Gagal memuat data lokasi: ${error.message}</div>`;
        });
});