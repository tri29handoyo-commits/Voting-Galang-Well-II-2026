# Voting Online — Token Sekali Pakai

Aplikasi voting online siap jalan menggunakan Flask + SQLite.

## 1. Jalankan di VS Code

Buka terminal pada folder project:

```bash
python -m venv venv
```

Windows:
```bash
venv\Scripts\activate
```

Install:
```bash
pip install -r requirements.txt
```

Jalankan:
```bash
python app.py
```

Kemudian buka:
http://127.0.0.1:5000

## 2. Login Admin

Alamat:
http://127.0.0.1:5000/admin/login

Username awal:
admin

Password awal:
admin123

**Segera ganti password sebelum digunakan untuk voting sungguhan.**

## 3. Fitur

- Token dibuat otomatis oleh admin.
- Token unik.
- Token yang sudah dipakai otomatis berubah menjadi TERPAKAI.
- Token tidak dapat digunakan kembali.
- Suara tersimpan di SQLite.
- Admin dapat menambah peserta.
- Admin dapat mengaktifkan/nonaktifkan peserta.
- Admin dapat membuka/menutup voting.
- Admin dapat melihat hasil suara.
- Admin dapat melihat status seluruh token.
- Reset voting tersedia untuk pengujian.

## 4. Catatan untuk online

Untuk penggunaan publik, jalankan di server seperti Render/Railway/VPS dengan database persisten. SQLite cocok untuk skala kecil. Jika voting akan digunakan oleh banyak pemilih secara bersamaan dalam jumlah besar, sebaiknya gunakan PostgreSQL.

## 5. Struktur

voting_web/
├── app.py
├── requirements.txt
├── README.md
├── database.db (dibuat otomatis setelah aplikasi pertama kali dijalankan)
├── templates/
└── static/
