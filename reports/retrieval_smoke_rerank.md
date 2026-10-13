# Retrieval smoke check

Top-5 per retriever for 10 hand-written queries. Not an evaluation: no gold labels, no metrics. `expect` is a human hint written with the query. Scores are not comparable across retrievers (BM25 = Okapi score, dense = cosine, hybrid = RRF, rerank = cross-encoder logit).

BM25 heading prefix: True; dense model: intfloat/multilingual-e5-base; RRF k=60, candidates=50.

Reranker: BAAI/bge-reranker-v2-m3 on cuda (fp16), top-20 hybrid hits per query, batch 16. Latency: median 244 ms, max 265 ms over 9 queries after warm-up (first call 188 ms). Peak VRAM, encoder + reranker: 1799 MB.

## q01_sab: Siapa yang menerbitkan Surat Persetujuan Berlayar bagi kapal yang akan berlayar?

Expect: UU 17/2008 (syahbandar), possibly PP 31/2021

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 23.576 | UU 17/2008 Pasal 219 | uu_17_2008.pdf p. 90 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 (1) Setiap kapal yang berlayar wajib memiliki Surat Persetujuan Berlayar yang dikeluarkan oleh Syahb |
| 2 | 21.761 | UU 17/2008 Pasal 209 | uu_17_2008.pdf p. 87 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 209 Dalam melaksanakan fungsi dan tugas sebagaimana dimaksud dalam Pasal 207 dan Pasal 208 Syahbandar me |
| 3 | 18.276 | PP 31/2021 Pasal 216 | pp_31_2021.pdf p. 143 | current | Pasal 216 (1) Syahbandar diberikan kewenangan untuk tidak melayani Pelabuhan, Terminal Khusus, atau Terminal u |
| 4 | 17.827 | PP 31/2021 Penjelasan Pasal 89 | pp_31_2021_penjelasan.pdf p. 22-23 | current | Pasal 89 Pasal ini berasal dari Pasal 10 Peraturan Pemerintah Nomor 51 Tahun 2002 tentang Perkapalan. Ayat (1) |
| 5 | 15.908 | PP 31/2021 Pasal 169 | pp_31_2021.pdf p. 110 | current | Pasal 169 (1) Setelah dilakukan pemeriksaan sebagaimana dimaksud dalam Pasal 168 ayat (1) surat, dokumen, dan  |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.877 | UU 17/2008 Pasal 219 | uu_17_2008.pdf p. 90 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 (1) Setiap kapal yang berlayar wajib memiliki Surat Persetujuan Berlayar yang dikeluarkan oleh Syahb |
| 2 | 0.861 | UU 17/2008 Penjelasan Pasal 219 | uu_17_2008.pdf p. 190 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 Ayat (1) Surat Persetujuan Berlayar yang dalam kelaziman internasional disebut port clearance diterb |
| 3 | 0.839 | PM 93/2013 Pasal 35 | pm_93_2013.pdf p. 25-26 | current | Pasal 35 (1) Perusahaan angkutan laut nasional yang mengoperasikan kapal pada trayek angkutan laut lintas bata |
| 4 | 0.839 | PM 59/2021 Pasal 108 | pm_59_2021.pdf p. 58 | current | Pasal 108 (1) PKL pada Kapal berbendera asing wajib dibuat dalam Bahasa Indonesia dan Bahasa Inggris. (2) PKL  |
| 5 | 0.838 | UU 17/2008 Pasal 216 | uu_17_2008.pdf p. 89 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 216 (1) Kapal yang melakukan kegiatan perbaikan, percobaan berlayar, kegiatan alih muat di kolam pelabuh |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.033 | UU 17/2008 Pasal 219 | uu_17_2008.pdf p. 90 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 (1) Setiap kapal yang berlayar wajib memiliki Surat Persetujuan Berlayar yang dikeluarkan oleh Syahb |
| 2 | 0.031 | UU 17/2008 Penjelasan Pasal 219 | uu_17_2008.pdf p. 190 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 Ayat (1) Surat Persetujuan Berlayar yang dalam kelaziman internasional disebut port clearance diterb |
| 3 | 0.030 | PP 31/2021 Pasal 169 | pp_31_2021.pdf p. 110 | current | Pasal 169 (1) Setelah dilakukan pemeriksaan sebagaimana dimaksud dalam Pasal 168 ayat (1) surat, dokumen, dan  |
| 4 | 0.030 | UU 17/2008 Pasal 213 | uu_17_2008.pdf p. 88 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 213 (1) Pemilik, Operator Kapal, atau Nakhoda wajib memberitahukan kedatangan kapalnya di pelabuhan kepa |
| 5 | 0.029 | UU 17/2008 Pasal 216 | uu_17_2008.pdf p. 89 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 216 (1) Kapal yang melakukan kegiatan perbaikan, percobaan berlayar, kegiatan alih muat di kolam pelabuh |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.995 | UU 17/2008 Pasal 219 | uu_17_2008.pdf p. 90 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 (1) Setiap kapal yang berlayar wajib memiliki Surat Persetujuan Berlayar yang dikeluarkan oleh Syahb |
| 2 | 0.969 | PP 31/2021 Pasal 216 | pp_31_2021.pdf p. 143 | current | Pasal 216 (1) Syahbandar diberikan kewenangan untuk tidak melayani Pelabuhan, Terminal Khusus, atau Terminal u |
| 3 | 0.931 | UU 17/2008 Penjelasan Pasal 219 | uu_17_2008.pdf p. 190 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 219 Ayat (1) Surat Persetujuan Berlayar yang dalam kelaziman internasional disebut port clearance diterb |
| 4 | 0.920 | UU 17/2008 Pasal 323 | uu_17_2008.pdf p. 123-124 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 323 (1) Nakhoda yang berlayar tanpa memiliki Surat Persetujuan Berlayar yang dikeluarkan oleh Syahbandar |
| 5 | 0.920 | UU 17/2008 Pasal 209 | uu_17_2008.pdf p. 87 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 209 Dalam melaksanakan fungsi dan tugas sebagaimana dimaksud dalam Pasal 207 dan Pasal 208 Syahbandar me |

## q02_amended_pm74: Apa persyaratan untuk memperoleh izin usaha perusahaan angkutan laut?

Expect: PM 93/2013 Pasal 71, superseded by PM 74/2016 Pasal 71

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 11.225 | PP 20/2010 Pasal 127 | pp_20_2010.pdf p. 66 | current | Pasal 127 (1) Untuk memperoleh izin usaha penyewaan peralatan angkutan laut atau peralatan jasa terkait dengan |
| 2 | 11.200 | PM 93/2013 Pasal 116 | pm_93_2013.pdf p. 79-80 | current | Pasal 116 Izin usaha atau izin operasi dapat dicabut tanpa melalui proses peringatan dan pembekuan izin, dalam |
| 3 | 11.146 | PM 93/2013 Pasal 71 ayat (1)-(8) | pm_93_2013.pdf p. 46-47 | SUPERSEDED by pm_74_2016 | Pasal 71 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada: a. Direktur  |
| 4 | 10.771 | PP 20/2010 Pasal 95 | pp_20_2010.pdf p. 47-48 | current | Pasal 95 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada Menteri, gube |
| 5 | 10.770 | UU 17/2008 Pasal 98 | uu_17_2008.pdf p. 48-49 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 98 (1) Pembangunan pelabuhan sungai dan danau wajib memperoleh izin dari bupati/walikota. (2) Pembanguna |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.897 | PM 93/2013 Pasal 69 ayat (1)-(2) | pm_93_2013.pdf p. 44 | current | Pasal 69 (1) Untuk memperoleh izin usaha angkutan laut sebagaimana dimaksud dalam Pasal 68 ayat (2), harus mem |
| 2 | 0.894 | PM 93/2013 Pasal 68 | pm_93_2013.pdf p. 43-44 | current | Pasal 68 (1) Usaha angkutan laut dilakukan oleh perusahaan angkutan laut nasional yang Berbadan Hukum Indonesi |
| 3 | 0.886 | PM 93/2013 Pasal 80 | pm_93_2013.pdf p. 52 | current | Pasal 80 (1) Kegiatan angkutan laut pelayaran-rakyat dilakukan oleh: a. orang perseorangan Warga Negara Indone |
| 4 | 0.882 | PM 93/2013 Pasal 70 | pm_93_2013.pdf p. 45-46 | current | Pasal 70 (1) Orang perseorangan warga negara Indonesia atau badan usaha dapat melakukan kerja sama dengan peru |
| 5 | 0.880 | PP 20/2010 Pasal 162 | pp_20_2010.pdf p. 81-82 | current | Pasal 162 (1) Untuk dapat melakukan kegiatan angkutan laut khusus sebagaimana dimaksud dalam Pasal 161 huruf a |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.031 | PM 93/2013 Pasal 69 ayat (1)-(2) | pm_93_2013.pdf p. 44 | current | Pasal 69 (1) Untuk memperoleh izin usaha angkutan laut sebagaimana dimaksud dalam Pasal 68 ayat (2), harus mem |
| 2 | 0.031 | PM 93/2013 Pasal 71 ayat (1)-(8) | pm_93_2013.pdf p. 46-47 | SUPERSEDED by pm_74_2016 | Pasal 71 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada: a. Direktur  |
| 3 | 0.030 | PP 20/2010 Pasal 95 | pp_20_2010.pdf p. 47-48 | current | Pasal 95 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada Menteri, gube |
| 4 | 0.029 | PM 93/2013 Pasal 73 | pm_93_2013.pdf p. 49 | current | Pasal 73 (1) Dalam hal terjadi perubahan nama perusahaan maka perusahaan angkutan laut nasional harus menyampa |
| 5 | 0.027 | PP 20/2010 Pasal 162 | pp_20_2010.pdf p. 81-82 | current | Pasal 162 (1) Untuk dapat melakukan kegiatan angkutan laut khusus sebagaimana dimaksud dalam Pasal 161 huruf a |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.999 | PM 93/2013 Pasal 69 ayat (1)-(2) | pm_93_2013.pdf p. 44 | current | Pasal 69 (1) Untuk memperoleh izin usaha angkutan laut sebagaimana dimaksud dalam Pasal 68 ayat (2), harus mem |
| 2 | 0.998 | PM 93/2013 Pasal 71 ayat (1)-(8) | pm_93_2013.pdf p. 46-47 | SUPERSEDED by pm_74_2016 | Pasal 71 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada: a. Direktur  |
| 3 | 0.997 | PM 93/2013 Pasal 82 ayat (1)-(8) | pm_93_2013.pdf p. 53-54 | current | Pasal 82 (1) Untuk memperoleh izin usaha angkutan laut pelayaran-rakyat, pemohon mengajukan permohonan kepada: |
| 4 | 0.996 | PM 93/2013 Pasal 81 ayat (1)-(3) | pm_93_2013.pdf p. 52-53 | current | Pasal 81 (1) Izin usaha sebagaimana dimaksud dalam Pasal 80 ayat (2), diberikan setelah memenuhi persyaratan:  |
| 5 | 0.995 | PP 20/2010 Pasal 95 | pp_20_2010.pdf p. 47-48 | current | Pasal 95 (1) Untuk memperoleh izin usaha angkutan laut, badan usaha mengajukan permohonan kepada Menteri, gube |

## q03_tol_laut: Bagaimana penyelenggaraan kewajiban pelayanan publik angkutan barang di laut (tol laut)?

Expect: PM 5/2024

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 34.347 | PM 5/2024 Pasal 12 | pm_5_2024.pdf p. 6 | current | Pasal 12 ( 1) Dalam hal masih tersedianya ruang muat kapal Tol Laut, barang pengadaan milik pemerintah, badan  |
| 2 | 24.043 | PM 5/2024 Pasal 1 | pm_5_2024.pdf p. 2 | current | Pasal 1 Dalam Peraturan Menteri ini yang dimaksud dengan: 1. Penyelenggaraan Kewajiban Pelayanan Publik Untuk  |
| 3 | 22.116 | PM 5/2024 Pasal 9 | pm_5_2024.pdf p. 5 | current | Pasal 9 ( 1) Pelaksana se bagaimana dimaksud dalam Pasal 6 diberikan subsidi angkutan barang di laut. (2) Subs |
| 4 | 22.021 | PM 5/2024 Pasal 17 | pm_5_2024.pdf p. 7 | current | Pasal 17 (1) Pengawasan teknis dan pengendalian dalam Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkuta |
| 5 | 21.538 | PM 5/2024 Pasal 16 | pm_5_2024.pdf p. 7 | current | Pasal 16 Pelaksana bertanggung jawab atas pelaksanaan dan penggunaan dana Penyelenggaraan Kewajiban Pelayanan  |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.897 | PM 5/2024 Pasal 2 | pm_5_2024.pdf p. 3 | current | Pasal 2 (1) Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut dilakukan dengan mengguna |
| 2 | 0.895 | PM 5/2024 Pasal 17 | pm_5_2024.pdf p. 7 | current | Pasal 17 (1) Pengawasan teknis dan pengendalian dalam Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkuta |
| 3 | 0.894 | PM 5/2024 Pasal 1 | pm_5_2024.pdf p. 2 | current | Pasal 1 Dalam Peraturan Menteri ini yang dimaksud dengan: 1. Penyelenggaraan Kewajiban Pelayanan Publik Untuk  |
| 4 | 0.891 | PM 5/2024 Pasal 12 | pm_5_2024.pdf p. 6 | current | Pasal 12 ( 1) Dalam hal masih tersedianya ruang muat kapal Tol Laut, barang pengadaan milik pemerintah, badan  |
| 5 | 0.888 | PM 5/2024 Pasal 7 | pm_5_2024.pdf p. 4-5 | current | Pasal 7 ( 1) Dalam rangka Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut, Pemerintah |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.032 | PM 5/2024 Pasal 12 | pm_5_2024.pdf p. 6 | current | Pasal 12 ( 1) Dalam hal masih tersedianya ruang muat kapal Tol Laut, barang pengadaan milik pemerintah, badan  |
| 2 | 0.032 | PM 5/2024 Pasal 1 | pm_5_2024.pdf p. 2 | current | Pasal 1 Dalam Peraturan Menteri ini yang dimaksud dengan: 1. Penyelenggaraan Kewajiban Pelayanan Publik Untuk  |
| 3 | 0.032 | PM 5/2024 Pasal 17 | pm_5_2024.pdf p. 7 | current | Pasal 17 (1) Pengawasan teknis dan pengendalian dalam Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkuta |
| 4 | 0.030 | PM 5/2024 Pasal 2 | pm_5_2024.pdf p. 3 | current | Pasal 2 (1) Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut dilakukan dengan mengguna |
| 5 | 0.029 | PM 5/2024 Pasal 7 | pm_5_2024.pdf p. 4-5 | current | Pasal 7 ( 1) Dalam rangka Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut, Pemerintah |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.997 | PM 5/2024 Pasal 1 | pm_5_2024.pdf p. 2 | current | Pasal 1 Dalam Peraturan Menteri ini yang dimaksud dengan: 1. Penyelenggaraan Kewajiban Pelayanan Publik Untuk  |
| 2 | 0.991 | PM 5/2024 Pasal 4 | pm_5_2024.pdf p. 3-4 | current | Pasal 4 (1) Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut wajib memenuhi prinsip-pr |
| 3 | 0.991 | PM 5/2024 Pasal 12 | pm_5_2024.pdf p. 6 | current | Pasal 12 ( 1) Dalam hal masih tersedianya ruang muat kapal Tol Laut, barang pengadaan milik pemerintah, badan  |
| 4 | 0.989 | PM 5/2024 Pasal 2 | pm_5_2024.pdf p. 3 | current | Pasal 2 (1) Penyelenggaraan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut dilakukan dengan mengguna |
| 5 | 0.989 | PM 5/2024 Pasal 15 | pm_5_2024.pdf p. 7 | current | Pasal 15 (1) Pelaksanaan Kewajiban Pelayanan Publik Untuk Angkutan Barang di laut diatur dalam kontrak antara  |

## q04_bongkar_muat: Apa saja kewajiban perusahaan bongkar muat dan persyaratan tenaga kerja bongkar muat?

Expect: PM 59/2021 and its amendment PM 3/2026 (Pasal 132)

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 30.828 | PP 20/2010 Pasal 81 | pp_20_2010.pdf p. 40 | current | Pasal 81 (1) Pelaksanaan kegiatan usaha bongkar muat barang sebagaimana dimaksud dalam Pasal 80 ayat (2) dilak |
| 2 | 29.695 | PM 59/2021 Pasal 3 | pm_59_2021.pdf p. 8-9 | SUPERSEDED by pm_3_2026 | Pasal 3 (1) Kegiatan Usaha Bongkar Muat Barang sebagaimana dimaksud dalam Pasal 2 huruf a merupakan kegiatan u |
| 3 | 28.460 | PM 3/2026 Pasal 3 | pm_3_2026.pdf p. 2-3 | amends pm_59_2021 Pasal 3 (replace) | 1. Ketentuan ayat (4) dan ayat (8) Pasal 3 diubah, serta ayat (7) dihapus, sehingga Pasal 3 berbunyi sebagai b |
| 4 | 24.972 | PM 3/2026 Pasal 3A | pm_3_2026.pdf p. 3 | amends pm_59_2021 Pasal 3A (insert) | 2. Di antara Pasal 3 dan Pasal 4 disisipkan 1 (satu) pasal, yakni Pasal 3A sehingga berbunyi sebagai berikut:  |
| 5 | 24.048 | PM 59/2021 Pasal 4 | pm_59_2021.pdf p. 9-10 | current | Pasal 4 (1) Kegiatan bongkar muat oleh perusahaan angkutan laut nasional sebagaimana dimaksud dalam Pasal 3 ay |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.883 | PP 20/2010 Pasal 81 | pp_20_2010.pdf p. 40 | current | Pasal 81 (1) Pelaksanaan kegiatan usaha bongkar muat barang sebagaimana dimaksud dalam Pasal 80 ayat (2) dilak |
| 2 | 0.878 | PM 59/2021 Pasal 3 | pm_59_2021.pdf p. 8-9 | SUPERSEDED by pm_3_2026 | Pasal 3 (1) Kegiatan Usaha Bongkar Muat Barang sebagaimana dimaksud dalam Pasal 2 huruf a merupakan kegiatan u |
| 3 | 0.873 | PM 3/2026 Pasal 3A | pm_3_2026.pdf p. 3 | amends pm_59_2021 Pasal 3A (insert) | 2. Di antara Pasal 3 dan Pasal 4 disisipkan 1 (satu) pasal, yakni Pasal 3A sehingga berbunyi sebagai berikut:  |
| 4 | 0.865 | PM 3/2026 Pasal 3 | pm_3_2026.pdf p. 2-3 | amends pm_59_2021 Pasal 3 (replace) | 1. Ketentuan ayat (4) dan ayat (8) Pasal 3 diubah, serta ayat (7) dihapus, sehingga Pasal 3 berbunyi sebagai b |
| 5 | 0.864 | PM 59/2021 Pasal 6 | pm_59_2021.pdf p. 11-12 | current | Pasal 6 (1) Kegiatan bongkar muat barang untuk kegiatan ship to ship (STS) transfer sebagaimana dimaksud dalam |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.033 | PP 20/2010 Pasal 81 | pp_20_2010.pdf p. 40 | current | Pasal 81 (1) Pelaksanaan kegiatan usaha bongkar muat barang sebagaimana dimaksud dalam Pasal 80 ayat (2) dilak |
| 2 | 0.032 | PM 59/2021 Pasal 3 | pm_59_2021.pdf p. 8-9 | SUPERSEDED by pm_3_2026 | Pasal 3 (1) Kegiatan Usaha Bongkar Muat Barang sebagaimana dimaksud dalam Pasal 2 huruf a merupakan kegiatan u |
| 3 | 0.031 | PM 3/2026 Pasal 3 | pm_3_2026.pdf p. 2-3 | amends pm_59_2021 Pasal 3 (replace) | 1. Ketentuan ayat (4) dan ayat (8) Pasal 3 diubah, serta ayat (7) dihapus, sehingga Pasal 3 berbunyi sebagai b |
| 4 | 0.031 | PM 3/2026 Pasal 3A | pm_3_2026.pdf p. 3 | amends pm_59_2021 Pasal 3A (insert) | 2. Di antara Pasal 3 dan Pasal 4 disisipkan 1 (satu) pasal, yakni Pasal 3A sehingga berbunyi sebagai berikut:  |
| 5 | 0.030 | PM 59/2021 Pasal 6 | pm_59_2021.pdf p. 11-12 | current | Pasal 6 (1) Kegiatan bongkar muat barang untuk kegiatan ship to ship (STS) transfer sebagaimana dimaksud dalam |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.979 | PP 20/2010 Pasal 81 | pp_20_2010.pdf p. 40 | current | Pasal 81 (1) Pelaksanaan kegiatan usaha bongkar muat barang sebagaimana dimaksud dalam Pasal 80 ayat (2) dilak |
| 2 | 0.971 | PM 59/2021 Pasal 3 | pm_59_2021.pdf p. 8-9 | SUPERSEDED by pm_3_2026 | Pasal 3 (1) Kegiatan Usaha Bongkar Muat Barang sebagaimana dimaksud dalam Pasal 2 huruf a merupakan kegiatan u |
| 3 | 0.960 | PM 3/2026 Pasal 3A | pm_3_2026.pdf p. 3 | amends pm_59_2021 Pasal 3A (insert) | 2. Di antara Pasal 3 dan Pasal 4 disisipkan 1 (satu) pasal, yakni Pasal 3A sehingga berbunyi sebagai berikut:  |
| 4 | 0.936 | PM 3/2026 Pasal 3 | pm_3_2026.pdf p. 2-3 | amends pm_59_2021 Pasal 3 (replace) | 1. Ketentuan ayat (4) dan ayat (8) Pasal 3 diubah, serta ayat (7) dihapus, sehingga Pasal 3 berbunyi sebagai b |
| 5 | 0.850 | PP 20/2010 Pasal 112 | pp_20_2010.pdf p. 58-59 | current | Pasal 112 (1) Izin usaha bongkar muat barang sebagaimana dimaksud dalam Pasal 111 huruf a diberikan oleh guber |

## q05_unctad_en: How much did seaborne trade volumes grow in 2024 and why did ton-miles increase?

Expect: UNCTAD RMT 2025 Overview, chapter 1

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 48.125 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Maritime trade continues to adjust to geopolitical and structural pressures | unctad_rmt_2025.pdf p. 9-10 | current | Maritime trade continues to adjust to geopolitical and structural pressures Seaborne trade recorded firm growt |
| 2 | 31.598 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Diverging trends across shipping segments: Containerized and energy trade | unctad_rmt_2025.pdf p. 10-11 | current | Diverging trends across shipping segments: Containerized and energy trade Containerized trade rebounded in 202 |
| 3 | 28.653 | Review of Maritime Transport 2025: Overview > Foreword | unctad_rmt_2025.pdf p. 6-7 | current | These factors are already reshaping maritime trade patterns. While flows continued to expand by 2.2 per cent i |
| 4 | 13.966 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Critical minerals trade opens new opportunities, but logistics and policy readiness are key enabling factors | unctad_rmt_2025.pdf p. 11 | current | Critical minerals trade opens new opportunities, but logistics and policy readiness are key enabling factors T |
| 5 | 11.666 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty | unctad_rmt_2025.pdf p. 12-13 | current | Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty D |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.872 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Maritime trade continues to adjust to geopolitical and structural pressures | unctad_rmt_2025.pdf p. 9-10 | current | Maritime trade continues to adjust to geopolitical and structural pressures Seaborne trade recorded firm growt |
| 2 | 0.854 | Review of Maritime Transport 2025: Overview > Foreword | unctad_rmt_2025.pdf p. 6-7 | current | These factors are already reshaping maritime trade patterns. While flows continued to expand by 2.2 per cent i |
| 3 | 0.842 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Diverging trends across shipping segments: Containerized and energy trade | unctad_rmt_2025.pdf p. 10-11 | current | Diverging trends across shipping segments: Containerized and energy trade Containerized trade rebounded in 202 |
| 4 | 0.839 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty | unctad_rmt_2025.pdf p. 12-13 | current | Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty D |
| 5 | 0.826 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Transformational trends are influencing the global fleet profile and capacity | unctad_rmt_2025.pdf p. 14 | current | Transformational trends are influencing the global fleet profile and capacity On 1 January 2025, the global fl |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.033 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Maritime trade continues to adjust to geopolitical and structural pressures | unctad_rmt_2025.pdf p. 9-10 | current | Maritime trade continues to adjust to geopolitical and structural pressures Seaborne trade recorded firm growt |
| 2 | 0.032 | Review of Maritime Transport 2025: Overview > Foreword | unctad_rmt_2025.pdf p. 6-7 | current | These factors are already reshaping maritime trade patterns. While flows continued to expand by 2.2 per cent i |
| 3 | 0.032 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Diverging trends across shipping segments: Containerized and energy trade | unctad_rmt_2025.pdf p. 10-11 | current | Diverging trends across shipping segments: Containerized and energy trade Containerized trade rebounded in 202 |
| 4 | 0.031 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty | unctad_rmt_2025.pdf p. 12-13 | current | Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty D |
| 5 | 0.030 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Transformational trends are influencing the global fleet profile and capacity | unctad_rmt_2025.pdf p. 14 | current | Transformational trends are influencing the global fleet profile and capacity On 1 January 2025, the global fl |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.999 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Maritime trade continues to adjust to geopolitical and structural pressures | unctad_rmt_2025.pdf p. 9-10 | current | Maritime trade continues to adjust to geopolitical and structural pressures Seaborne trade recorded firm growt |
| 2 | 0.998 | Review of Maritime Transport 2025: Overview > Foreword | unctad_rmt_2025.pdf p. 6-7 | current | These factors are already reshaping maritime trade patterns. While flows continued to expand by 2.2 per cent i |
| 3 | 0.920 | Review of Maritime Transport 2025: Overview > 1. International maritime trade > Diverging trends across shipping segments: Containerized and energy trade | unctad_rmt_2025.pdf p. 10-11 | current | Diverging trends across shipping segments: Containerized and energy trade Containerized trade rebounded in 202 |
| 4 | 0.645 | Review of Maritime Transport 2025: Overview > 3. Freight rates and maritime transport costs > Freight rate volatility is becoming the norm, driven by geopolitical tensions, trade policy shifts, and fragile supply and demand fundamentals | unctad_rmt_2025.pdf p. 16-17 | current | Freight rate volatility is becoming the norm, driven by geopolitical tensions, trade policy shifts, and fragil |
| 5 | 0.171 | Review of Maritime Transport 2025: Overview > 4. Port performance and maritime trade facilitation > Port performance has varied across indicators and shipping segments; gender balance in the port workforce has yet to be achieved | unctad_rmt_2025.pdf p. 18-20 | current | Port performance has varied across indicators and shipping segments; gender balance in the port workforce has  |

## q06_tarif: Apa saja jenis tarif jasa kepelabuhanan untuk pelayanan jasa kapal?

Expect: PM 72/2017

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 21.389 | PM 72/2017 Pasal 3 | pm_72_2017.pdf p. 6 | current | Pasal 3 (1) Jenis tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 2 huruf a merupakan suat |
| 2 | 20.563 | PM 72/2017 Pasal 2 | pm_72_2017.pdf p. 6 | current | Pasal 2 Jenis tarif pelayanan kegiatan pengusahaan di Pelabuhan terdiri atas: a. jenis tarif pelayanan jasa ke |
| 3 | 20.447 | PM 72/2017 Pasal 7 | pm_72_2017.pdf p. 9 | current | Pasal 7 Struktur tarif pelayanan jasa kepelabuhanan dan tarif pelayanan jasa terkait dengan kepelabuhanan meru |
| 4 | 19.692 | PM 72/2017 Pasal 5 | pm_72_2017.pdf p. 7 | current | Pasal 5 Jenis tarif pelayanan jasa terkait dengan kepelabuhanan sebagaimana dimaksud dalam Pasal 2 huruf b mer |
| 5 | 19.198 | PM 72/2017 Pasal 16 | pm_72_2017.pdf p. 31 | current | Pasal 16 (1) Penetapan besaran tarif jasa kepelabuhanan pada terminal yang pelayanan jasanya diberikan oleh Ot |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.901 | PM 72/2017 Pasal 3 | pm_72_2017.pdf p. 6 | current | Pasal 3 (1) Jenis tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 2 huruf a merupakan suat |
| 2 | 0.896 | PM 72/2017 Pasal 17 | pm_72_2017.pdf p. 32 | current | Pasal 17 (1) Penetapan besaran tarif jasa kepelabuhanan oleh BUP sebagaimana dimaksud dalam Pasal 16 ayat (5), |
| 3 | 0.896 | PM 72/2017 Pasal 20 | pm_72_2017.pdf p. 35 | current | Pasal 20 (1) Penetapan besaran tarif jasa kepelabuhanan oleh BUP sebagaimana dimaksud dalam Pasal 16 ayat (5), |
| 4 | 0.893 | PM 72/2017 Pasal 8 | pm_72_2017.pdf p. 9-10 | current | Pasal 8 Kerangka tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 7, pada setiap jenis pela |
| 5 | 0.892 | PM 72/2017 Pasal 15 | pm_72_2017.pdf p. 30 | current | Pasal 15 (1) Besaran tarif jasa kepelabuhanan dapat ditetapkan secara paket. (2) Besaran tarif jasa kepelabuha |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.033 | PM 72/2017 Pasal 3 | pm_72_2017.pdf p. 6 | current | Pasal 3 (1) Jenis tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 2 huruf a merupakan suat |
| 2 | 0.030 | PM 72/2017 Pasal 11 | pm_72_2017.pdf p. 27-28 | current | Pasal 11 (1) Golongan tarif pelayanan jasa kepelabuhanan merupakan penggolongan tarif yang ditetapkan berdasar |
| 3 | 0.030 | PM 72/2017 Pasal 12 | pm_72_2017.pdf p. 28 | current | Pasal 12 (1) Tarif pelayanan jasa Kapal yang melakukan kegiatan angkutan laut dalam negeri dikenakan tarif jas |
| 4 | 0.030 | PM 72/2017 Pasal 2 | pm_72_2017.pdf p. 6 | current | Pasal 2 Jenis tarif pelayanan kegiatan pengusahaan di Pelabuhan terdiri atas: a. jenis tarif pelayanan jasa ke |
| 5 | 0.030 | PM 72/2017 Pasal 20 | pm_72_2017.pdf p. 35 | current | Pasal 20 (1) Penetapan besaran tarif jasa kepelabuhanan oleh BUP sebagaimana dimaksud dalam Pasal 16 ayat (5), |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.997 | PM 72/2017 Pasal 8 | pm_72_2017.pdf p. 9-10 | current | Pasal 8 Kerangka tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 7, pada setiap jenis pela |
| 2 | 0.995 | PM 72/2017 Pasal 3 | pm_72_2017.pdf p. 6 | current | Pasal 3 (1) Jenis tarif pelayanan jasa kepelabuhanan sebagaimana dimaksud dalam Pasal 2 huruf a merupakan suat |
| 3 | 0.994 | PM 72/2017 Pasal 4 | pm_72_2017.pdf p. 6-7 | current | Pasal 4 (1) Tarif pelayanan jasa Kapal sebagaimana dimaksud dalam Pasal 3 ayat (2) huruf a terdiri atas: a. ta |
| 4 | 0.993 | PM 72/2017 Pasal 12 | pm_72_2017.pdf p. 28 | current | Pasal 12 (1) Tarif pelayanan jasa Kapal yang melakukan kegiatan angkutan laut dalam negeri dikenakan tarif jas |
| 5 | 0.991 | PM 72/2017 Pasal 15 | pm_72_2017.pdf p. 30 | current | Pasal 15 (1) Besaran tarif jasa kepelabuhanan dapat ditetapkan secara paket. (2) Besaran tarif jasa kepelabuha |

## q07_rip: Apa yang dimaksud dengan Rencana Induk Pelabuhan dan siapa yang menetapkannya?

Expect: PP 61/2009, PM 50/2021

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 10.786 | PP 61/2009 Pasal 20 | pp_61_2009.pdf p. 13-14 | current | Pasal 20 (1) Setiap pelabuhan wajib memiliki Rencana Induk Pelabuhan. (2) Rencana Induk Pelabuhan sebagaimana  |
| 2 | 10.780 | UU 17/2008 Pasal 71 | uu_17_2008.pdf p. 37-38 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 71 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 67 ayat (3) huruf b merupakan p |
| 3 | 10.754 | PP 61/2009 Pasal 21 | pp_61_2009.pdf p. 14 | current | Pasal 21 (1) Rencana Induk Pelabuhan laut dan Rencana Induk Pelabuhan sungai dan danau meliputi rencana perunt |
| 4 | 10.754 | PP 61/2009 Pasal 8 | pp_61_2009.pdf p. 8 | current | Pasal 8 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 7 ayat (1) memuat: a. kebijakan  |
| 5 | 10.668 | PP 61/2009 Pasal 7 | pp_61_2009.pdf p. 7 | current | Pasal 7 (1) Rencana Induk Pelabuhan Nasional yang merupakan perwujudan dari Tatanan Kepelabuhanan Nasional dig |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.885 | PP 61/2009 Pasal 28 | pp_61_2009.pdf p. 19 | current | Pasal 28 (1) Rencana Induk Pelabuhan ditetapkan oleh: a. Menteri untuk pelabuhan utama dan pelabuhan pengumpul |
| 2 | 0.882 | PM 50/2021 Pasal 40 | pm_50_2021.pdf p. 26 | current | Pasal 40 Rencana Induk Pelabuhan sebagaimana dimaksud dalam Pasal 35 ditetapkan oleh: a. Menteri untuk Pelabuh |
| 3 | 0.882 | PP 61/2009 Pasal 8 | pp_61_2009.pdf p. 8 | current | Pasal 8 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 7 ayat (1) memuat: a. kebijakan  |
| 4 | 0.880 | PP 61/2009 Pasal 7 | pp_61_2009.pdf p. 7 | current | Pasal 7 (1) Rencana Induk Pelabuhan Nasional yang merupakan perwujudan dari Tatanan Kepelabuhanan Nasional dig |
| 5 | 0.879 | UU 17/2008 Pasal 73 | uu_17_2008.pdf p. 38 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 73 (1) Setiap pelabuhan wajib memiliki Rencana Induk Pelabuhan. (2) Rencana Induk Pelabuhan sebagaimana  |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.031 | PP 61/2009 Pasal 8 | pp_61_2009.pdf p. 8 | current | Pasal 8 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 7 ayat (1) memuat: a. kebijakan  |
| 2 | 0.031 | PP 61/2009 Pasal 20 | pp_61_2009.pdf p. 13-14 | current | Pasal 20 (1) Setiap pelabuhan wajib memiliki Rencana Induk Pelabuhan. (2) Rencana Induk Pelabuhan sebagaimana  |
| 3 | 0.031 | PP 61/2009 Pasal 7 | pp_61_2009.pdf p. 7 | current | Pasal 7 (1) Rencana Induk Pelabuhan Nasional yang merupakan perwujudan dari Tatanan Kepelabuhanan Nasional dig |
| 4 | 0.031 | PP 61/2009 Pasal 28 | pp_61_2009.pdf p. 19 | current | Pasal 28 (1) Rencana Induk Pelabuhan ditetapkan oleh: a. Menteri untuk pelabuhan utama dan pelabuhan pengumpul |
| 5 | 0.031 | UU 17/2008 Pasal 71 | uu_17_2008.pdf p. 37-38 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 71 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 67 ayat (3) huruf b merupakan p |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.999 | PP 61/2009 Pasal 28 | pp_61_2009.pdf p. 19 | current | Pasal 28 (1) Rencana Induk Pelabuhan ditetapkan oleh: a. Menteri untuk pelabuhan utama dan pelabuhan pengumpul |
| 2 | 0.996 | PM 50/2021 Pasal 41 ayat (1)-(4) | pm_50_2021.pdf p. 26-27 | current | Pasal 41 (1) Permohonan penetapan Rencana Induk Pelabuhan pada Pelabuhan Utama dan Pelabuhan Pengumpul sebagai |
| 3 | 0.994 | PP 61/2009 Pasal 8 | pp_61_2009.pdf p. 8 | current | Pasal 8 (1) Rencana Induk Pelabuhan Nasional sebagaimana dimaksud dalam Pasal 7 ayat (1) memuat: a. kebijakan  |
| 4 | 0.994 | PM 50/2021 Pasal 40 | pm_50_2021.pdf p. 26 | current | Pasal 40 Rencana Induk Pelabuhan sebagaimana dimaksud dalam Pasal 35 ditetapkan oleh: a. Menteri untuk Pelabuh |
| 5 | 0.994 | PM 50/2021 Pasal 44 | pm_50_2021.pdf p. 29 | current | Pasal 44 (1) Rencana Induk Pelabuhan dilengkapi dengan Rancangan DLKr dan DLKp Pelabuhan. (2) Rencana Induk Pe |

## q08_pelayaran_rakyat: Bagaimana pemberdayaan angkutan laut pelayaran-rakyat oleh pemerintah?

Expect: UU 66/2024 Pasal 15A-15E (inserted)

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 19.637 | UU 66/2024 Pasal 15C | uu_66_2024.pdf p. 11 | amends uu_17_2008 Pasal 15C (insert) | Pasal 15C (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 2 | 18.759 | UU 66/2024 Pasal 15B | uu_66_2024.pdf p. 10-11 | amends uu_17_2008 Pasal 15B (insert) | Pasal 15B (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 3 | 17.754 | UU 66/2024 Pasal 15E | uu_66_2024.pdf p. 11-12 | amends uu_17_2008 Pasal 15E (insert) | Pasal 15E (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat oleh perusahaan pelayaran-rakyat sebagaiman |
| 4 | 15.589 | UU 66/2024 Penjelasan Pasal 25A | uu_66_2024.pdf p. 45 | amends uu_17_2008 Pasal 25A (penjelasan) | Pasal 25A Kerja sama perusahaan angkutan laut nasional dengan angkutan pelayaran-rakyat dilakukan dalam rangka |
| 5 | 15.306 | UU 66/2024 Pasal 15A | uu_66_2024.pdf p. 10 | amends uu_17_2008 Pasal 15A (insert) | 2. Di antara Pasal 15 dan Pasal 16 disisipkan 5 (lima) pasal, yakni Pasal 15A, Pasal 15B, Pasal 15€, Pasal 15D |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.892 | UU 66/2024 Pasal 15B | uu_66_2024.pdf p. 10-11 | amends uu_17_2008 Pasal 15B (insert) | Pasal 15B (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 2 | 0.881 | UU 17/2008 Penjelasan Pasal 16 | uu_17_2008.pdf p. 144-145 | SUPERSEDED by uu_66_2024; may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 16 Ayat (1) Ketentuan ini dimaksudkan sebagai salah satu upaya memberikan pelindungan terhadap kelangsun |
| 3 | 0.880 | UU 17/2008 Pasal 16 | uu_17_2008.pdf p. 17 | SUPERSEDED by uu_66_2024; may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 16 (1) Pembinaan angkutan laut pelayaran-rakyat dilaksanakan agar kehidupan usaha dan peranan penting an |
| 4 | 0.876 | PP 20/2010 Pasal 47 | pp_20_2010.pdf p. 23-24 | current | Pasal 47 (1) Menteri melakukan pembinaan angkutan laut pelayaran-rakyat agar kehidupan usaha dan peranan penti |
| 5 | 0.873 | UU 66/2024 Pasal 15A | uu_66_2024.pdf p. 10 | amends uu_17_2008 Pasal 15A (insert) | 2. Di antara Pasal 15 dan Pasal 16 disisipkan 5 (lima) pasal, yakni Pasal 15A, Pasal 15B, Pasal 15€, Pasal 15D |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.033 | UU 66/2024 Pasal 15B | uu_66_2024.pdf p. 10-11 | amends uu_17_2008 Pasal 15B (insert) | Pasal 15B (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 2 | 0.032 | UU 66/2024 Pasal 15C | uu_66_2024.pdf p. 11 | amends uu_17_2008 Pasal 15C (insert) | Pasal 15C (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 3 | 0.031 | UU 66/2024 Pasal 15A | uu_66_2024.pdf p. 10 | amends uu_17_2008 Pasal 15A (insert) | 2. Di antara Pasal 15 dan Pasal 16 disisipkan 5 (lima) pasal, yakni Pasal 15A, Pasal 15B, Pasal 15€, Pasal 15D |
| 4 | 0.030 | UU 66/2024 Pasal 15E | uu_66_2024.pdf p. 11-12 | amends uu_17_2008 Pasal 15E (insert) | Pasal 15E (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat oleh perusahaan pelayaran-rakyat sebagaiman |
| 5 | 0.030 | UU 17/2008 Penjelasan Pasal 16 | uu_17_2008.pdf p. 144-145 | SUPERSEDED by uu_66_2024; may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 16 Ayat (1) Ketentuan ini dimaksudkan sebagai salah satu upaya memberikan pelindungan terhadap kelangsun |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.996 | UU 66/2024 Pasal 15B | uu_66_2024.pdf p. 10-11 | amends uu_17_2008 Pasal 15B (insert) | Pasal 15B (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 2 | 0.991 | UU 66/2024 Pasal 15E | uu_66_2024.pdf p. 11-12 | amends uu_17_2008 Pasal 15E (insert) | Pasal 15E (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat oleh perusahaan pelayaran-rakyat sebagaiman |
| 3 | 0.990 | UU 66/2024 Pasal 15C | uu_66_2024.pdf p. 11 | amends uu_17_2008 Pasal 15C (insert) | Pasal 15C (1) Pemberdayaan kegiatan Angkutan Laut Pelayaran-Rakyat sebagaimana dimaksud dalam Pasal 15A ayat ( |
| 4 | 0.983 | PM 93/2013 Pasal 55 ayat (1)-(2) | pm_93_2013.pdf p. 36-37 | current | Pasal 55 (1) Dalam rangka pengembangan angkutan laut pelayaran-rakyat, Direktur Jenderal melakukan pembinaan.  |
| 5 | 0.982 | UU 66/2024 Pasal 15A | uu_66_2024.pdf p. 10 | amends uu_17_2008 Pasal 15A (insert) | 2. Di antara Pasal 15 dan Pasal 16 disisipkan 5 (lima) pasal, yakni Pasal 15A, Pasal 15B, Pasal 15€, Pasal 15D |

## q09_cabotage_en: Can a foreign-flagged ship carry cargo between Indonesian domestic ports?

Expect: UU 17/2008 Pasal 8 (cabotage, Indonesian text; cross-lingual)

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 15.338 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty | unctad_rmt_2025.pdf p. 12-13 | current | Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty D |
| 2 | 12.405 | Review of Maritime Transport 2025: Overview > 4. Port performance and maritime trade facilitation > Port performance has varied across indicators and shipping segments; gender balance in the port workforce has yet to be achieved | unctad_rmt_2025.pdf p. 18-20 | current | Port performance has varied across indicators and shipping segments; gender balance in the port workforce has  |
| 3 | 11.257 | Review of Maritime Transport 2025: Overview > 4. Port performance and maritime trade facilitation > Port performance has varied across indicators and shipping segments; gender balance in the port workforce has yet to be achieved | unctad_rmt_2025.pdf p. 20-21 | current | Port performance has varied across indicators and shipping segments; gender balance in the port workforce has  |
| 4 | 9.811 | Review of Maritime Transport 2025: Overview > Policy focus | unctad_rmt_2025.pdf p. 27 | current | Leverage digital solutions and strengthen the regulatory framework to address cyberrisks: Policymakers as well |
| 5 | 9.782 | Review of Maritime Transport 2025: Overview > Foreword | unctad_rmt_2025.pdf p. 6-7 | current | These factors are already reshaping maritime trade patterns. While flows continued to expand by 2.2 per cent i |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.839 | PM 93/2013 Pasal 20 | pm_93_2013.pdf p. 19 | current | Pasal 20 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 2 | 0.832 | UU 17/2008 Pasal 11 | uu_17_2008.pdf p. 15 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 11 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 3 | 0.832 | PM 93/2013 Pasal 23 | pm_93_2013.pdf p. 20-21 | current | Pasal 23 (1) Perusahaan angkutan laut nasional dan/atau perusahaan angkutan laut asing yang mengoperasikan kap |
| 4 | 0.830 | PM 93/2013 Pasal 25 | pm_93_2013.pdf p. 21-22 | current | Pasal 25 (1) Kapal yang melakukan kegiatan angkutan laut luar negeri dapat melakukan kegiatan di pelabuhan ata |
| 5 | 0.828 | PP 20/2010 Pasal 24 | pp_20_2010.pdf p. 13 | current | Pasal 24 (1) Kapal yang melakukan kegiatan angkutan laut luar negeri dapat melakukan kegiatan di pelabuhan ata |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.024 | PP 61/2009 Pasal 99 | pp_61_2009.pdf p. 47 | current | Pasal 99 Pelabuhan laut dapat ditingkatkan kemampuan pengoperasian fasilitas pelabuhan dari fasilitas untuk me |
| 2 | 0.016 | PM 93/2013 Pasal 20 | pm_93_2013.pdf p. 19 | current | Pasal 20 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 3 | 0.016 | Review of Maritime Transport 2025: Overview > 2. World shipping fleet and services > Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty | unctad_rmt_2025.pdf p. 12-13 | current | Maritime transport is navigating uncharted waters amid geopolitical instability and trade policy uncertainty D |
| 4 | 0.016 | UU 17/2008 Pasal 11 | uu_17_2008.pdf p. 15 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 11 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 5 | 0.016 | Review of Maritime Transport 2025: Overview > 4. Port performance and maritime trade facilitation > Port performance has varied across indicators and shipping segments; gender balance in the port workforce has yet to be achieved | unctad_rmt_2025.pdf p. 18-20 | current | Port performance has varied across indicators and shipping segments; gender balance in the port workforce has  |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.389 | UU 17/2008 Pasal 8 | uu_17_2008.pdf p. 13 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 8 (1) Kegiatan angkutan laut dalam negeri dilakukan oleh perusahaan angkutan laut nasional dengan menggu |
| 2 | 0.075 | UU 17/2008 Pasal 11 | uu_17_2008.pdf p. 15 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 11 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 3 | 0.063 | PP 20/2010 Pasal 23 | pp_20_2010.pdf p. 12-13 | current | Pasal 23 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 4 | 0.028 | PM 93/2013 Pasal 20 | pm_93_2013.pdf p. 19 | current | Pasal 20 (1) Kegiatan angkutan laut dari dan ke luar negeri dilakukan oleh perusahaan angkutan laut nasional d |
| 5 | 0.025 | PM 72/2017 Pasal 14 | pm_72_2017.pdf p. 29-30 | current | Pasal 14 (1) Kapal angkutan laut berbendera Indonesia yang melakukan kegiatan angkutan laut dalam negeri yang  |

## q10_out_of_scope: Berapa tarif tiket pesawat Jakarta ke Bali pada musim liburan?

Expect: nothing relevant (aviation fares are out of scope)

**bm25**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 9.237 | PP 20/2010 Pasal 108 | pp_20_2010.pdf p. 56-57 | current | Pasal 108 (1) Untuk memperoleh izin usaha angkutan penyeberangan, badan usaha mengajukan permohonan kepada Gub |
| 2 | 9.170 | PP 20/2010 Pasal 104 | pp_20_2010.pdf p. 54-55 | current | Pasal 104 (1) Untuk memperoleh izin usaha angkutan sungai dan danau, setiap orang atau badan usaha mengajukan  |
| 3 | 8.724 | UU 17/2008 Pasal 279 | uu_17_2008.pdf p. 111-112 | REPEALED by uu_66_2024; may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 279 (1) Dalam rangka melaksanakan tugasnya penjaga laut dan pantai sebagaimana dimaksud dalam Pasal 277  |
| 4 | 8.633 | PM 72/2017 Pasal 8 | pm_72_2017.pdf p. 12-13 | current | 3) plugging/unplugging; 4) monitoring/supervisi; 5) pompa; 6) ramp door/moveable bridge; 7) grab dan hooper; 8 |
| 5 | 7.828 | UU 17/2008 Pasal 28 ayat (5)-(6) | uu_17_2008.pdf p. 22-23 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | (5) Izin usaha angkutan penyeberangan diberikan oleh: a. bupati/walikota sesuai dengan domisili badan usaha; a |

**dense**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.788 | PP 20/2010 Pasal 170 | pp_20_2010.pdf p. 85 | current | Pasal 170 Tarif angkutan di perairan terdiri atas tarif angkutan penumpang dan tarif angkutan barang. |
| 2 | 0.788 | UU 17/2008 Pasal 36 | uu_17_2008.pdf p. 25 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 36 Tarif usaha jasa terkait ditetapkan oleh penyedia jasa terkait berdasarkan kesepakatan antara penggun |
| 3 | 0.787 | PM 72/2017 Pasal 4 | pm_72_2017.pdf p. 6-7 | current | Pasal 4 (1) Tarif pelayanan jasa Kapal sebagaimana dimaksud dalam Pasal 3 ayat (2) huruf a terdiri atas: a. ta |
| 4 | 0.787 | UU 17/2008 Pasal 109 | uu_17_2008.pdf p. 52 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 109 Setiap pelayanan jasa kepelabuhanan dikenakan tarif sesuai dengan jasa yang disediakan. |
| 5 | 0.785 | PM 59/2021 Pasal 130 | pm_59_2021.pdf p. 67 | current | Pasal 130 (1) Setiap pelayanan jasa terkait dengan angkutan di perairan yang dilakukan oleh perusahaan jasa te |

**hybrid**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.030 | PM 72/2017 Pasal 4 | pm_72_2017.pdf p. 6-7 | current | Pasal 4 (1) Tarif pelayanan jasa Kapal sebagaimana dimaksud dalam Pasal 3 ayat (2) huruf a terdiri atas: a. ta |
| 2 | 0.030 | PP 20/2010 Pasal 170 | pp_20_2010.pdf p. 85 | current | Pasal 170 Tarif angkutan di perairan terdiri atas tarif angkutan penumpang dan tarif angkutan barang. |
| 3 | 0.027 | PP 20/2010 Pasal 175 | pp_20_2010.pdf p. 87 | current | Pasal 175 (1) Tarif usaha jasa terkait dengan angkutan di perairan sebagaimana dimaksud dalam Pasal 79 ayat (2 |
| 4 | 0.027 | UU 17/2008 Pasal 35 | uu_17_2008.pdf p. 25 | may be amended by UU 11/2020, UU 6/2023 (not in corpus) | Pasal 35 (1) Tarif angkutan di perairan terdiri atas tarif angkutan penumpang dan tarif angkutan barang. (2) T |
| 5 | 0.026 | PP 20/2010 Pasal 108 | pp_20_2010.pdf p. 56-57 | current | Pasal 108 (1) Untuk memperoleh izin usaha angkutan penyeberangan, badan usaha mengajukan permohonan kepada Gub |

**hybrid+rerank**

| # | score | where | pages | status | snippet |
|---|---|---|---|---|---|
| 1 | 0.000 | PM 72/2017 Pasal 4 | pm_72_2017.pdf p. 6-7 | current | Pasal 4 (1) Tarif pelayanan jasa Kapal sebagaimana dimaksud dalam Pasal 3 ayat (2) huruf a terdiri atas: a. ta |
| 2 | 0.000 | PM 72/2017 Pasal 12 | pm_72_2017.pdf p. 28 | current | Pasal 12 (1) Tarif pelayanan jasa Kapal yang melakukan kegiatan angkutan laut dalam negeri dikenakan tarif jas |
| 3 | 0.000 | PM 72/2017 Pasal 15 | pm_72_2017.pdf p. 30 | current | Pasal 15 (1) Besaran tarif jasa kepelabuhanan dapat ditetapkan secara paket. (2) Besaran tarif jasa kepelabuha |
| 4 | 0.000 | PP 20/2010 Pasal 171 | pp_20_2010.pdf p. 85-86 | current | Pasal 171 (1) Tarif angkutan penumpang sebagaimana dimaksud dalam Pasal 170 terdiri atas jenis tarif untuk: a. |
| 5 | 0.000 | PM 72/2017 Pasal 18 | pm_72_2017.pdf p. 32-34 | current | Pasal 18 Konsultasi sebagaimana dimaksud dalam Pasal 17 ayat (1) dilaksanakan dengan mekanisme sebagai berikut |
