"""Toko Basmallah - aplikasi kasir online berbasis Streamlit.

Fitur: kasir, strata harga (jumlah + jenis pelanggan), hutang, poin member,
struk (cetak / salin / WhatsApp), dan dasbor penjualan.
Data disimpan di SQLite (file basmallah.db).
"""
import io
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

st.set_page_config(page_title="Toko Basmallah", page_icon="🛒", layout="wide")

DB_PATH = "basmallah.db"
TZ = ZoneInfo("Asia/Jakarta")
STRUK_WIDTH = 32


# ----------------------------------------------------------------------------
# Utilitas
# ----------------------------------------------------------------------------
def rp(n) -> str:
    return "Rp" + f"{int(round(n)):,}".replace(",", ".")


def now_ts() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
@st.cache_resource
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS produk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            harga INTEGER NOT NULL,
            grosir_min INTEGER,
            grosir_harga INTEGER,
            partai_min INTEGER,
            partai_harga INTEGER,
            stok INTEGER NOT NULL DEFAULT 0,
            gambar BLOB
        );
        CREATE TABLE IF NOT EXISTS member (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            hp TEXT,
            tier TEXT NOT NULL DEFAULT 'member',
            poin INTEGER NOT NULL DEFAULT 0,
            hutang INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            member_id INTEGER,
            member_nama TEXT,
            metode TEXT NOT NULL,
            subtotal INTEGER NOT NULL,
            poin_dipakai INTEGER NOT NULL DEFAULT 0,
            potongan_poin INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            poin_didapat INTEGER NOT NULL DEFAULT 0,
            dibayar INTEGER NOT NULL,
            kembali INTEGER NOT NULL DEFAULT 0,
            hutang INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transaksi_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trx_id INTEGER NOT NULL,
            produk_id INTEGER,
            nama TEXT NOT NULL,
            qty INTEGER NOT NULL,
            harga INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pembayaran_hutang (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            member_id INTEGER NOT NULL,
            jumlah INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pengaturan (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # Database lama (sebelum ada fitur gambar): tambahkan kolom gambar bila belum ada
    kolom = [r["name"] for r in conn.execute("PRAGMA table_info(produk)")]
    if "gambar" not in kolom:
        conn.execute("ALTER TABLE produk ADD COLUMN gambar BLOB")
        conn.commit()
    seed(conn)
    return conn


def proses_gambar(file):
    """Ubah gambar unggahan menjadi JPEG persegi 400x400 (hemat ruang). None bila file tidak valid."""
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (400, 400), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


DEFAULT_SETTINGS = {
    "toko_nama": "TOKO BASMALLAH",
    "toko_alamat": "Alamat toko Anda di sini",
    "poin_per": "10000",       # 1 poin tiap belanja Rp10.000
    "nilai_poin": "100",       # 1 poin = Rp100
    "diskon_member": "3",      # persen
    "diskon_reseller": "8",    # persen
}


def seed(conn: sqlite3.Connection) -> None:
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO pengaturan(key, value) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) FROM produk").fetchone()[0] == 0:
        contoh = [
            ("Beras Premium 5 kg", 72000, 3, 70000, 10, 68000, 40),
            ("Minyak Goreng 1 L", 18500, 6, 17800, 12, 17200, 60),
            ("Gula Pasir 1 kg", 17500, 5, 17000, 20, 16500, 35),
            ("Telur Ayam 1 kg", 29000, 5, 28000, None, None, 18),
            ("Mie Instan Goreng", 3200, 10, 3000, 40, 2850, 240),
            ("Kopi Sachet", 1500, 12, 1350, 60, 1250, 300),
            ("Teh Celup 25 pcs", 7500, 6, 7000, None, None, 7),
            ("Sabun Mandi Batang", 4500, 6, 4200, 24, 3900, 80),
            ("Deterjen Bubuk 1 kg", 22000, 4, 21000, None, None, 25),
            ("Tepung Terigu 1 kg", 12500, 5, 12000, 25, 11500, 9),
            ("Kecap Manis 600 ml", 19500, 6, 18500, None, None, 22),
            ("Air Mineral 600 ml", 3500, 12, 3200, 24, 3000, 120),
        ]
        conn.executemany(
            "INSERT INTO produk(nama,harga,grosir_min,grosir_harga,partai_min,partai_harga,stok) "
            "VALUES (?,?,?,?,?,?,?)",
            contoh,
        )
    if conn.execute("SELECT COUNT(*) FROM member").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO member(nama,hp,tier,poin,hutang) VALUES (?,?,?,?,?)",
            [
                ("Bu Siti Aminah", "0812-3456-7801", "member", 42, 0),
                ("Pak Hasan (Warung Hasan)", "0813-5566-2210", "reseller", 118, 185000),
                ("Bu Lestari", "0857-1200-9934", "member", 15, 64000),
            ],
        )
    conn.commit()


def q(sql: str, params=()) -> list:
    return get_conn().execute(sql, params).fetchall()


def run(sql: str, params=()) -> None:
    conn = get_conn()
    conn.execute(sql, params)
    conn.commit()


def df(sql: str, params=()) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(), params=params)


def get_settings() -> dict:
    s = {r["key"]: r["value"] for r in q("SELECT key, value FROM pengaturan")}
    return {
        "toko_nama": s.get("toko_nama", DEFAULT_SETTINGS["toko_nama"]),
        "toko_alamat": s.get("toko_alamat", DEFAULT_SETTINGS["toko_alamat"]),
        "poin_per": int(s.get("poin_per", 10000)),
        "nilai_poin": int(s.get("nilai_poin", 100)),
        "diskon_member": float(s.get("diskon_member", 3)),
        "diskon_reseller": float(s.get("diskon_reseller", 8)),
    }


# ----------------------------------------------------------------------------
# Harga bertingkat
# ----------------------------------------------------------------------------
def unit_price(p, qty: int, tier, cfg: dict):
    """Harga satuan sesuai jumlah (eceran/grosir/partai) lalu diskon jenis pelanggan."""
    base, label = p["harga"], "Eceran"
    if p["partai_min"] and qty >= p["partai_min"]:
        base, label = p["partai_harga"], "Partai"
    elif p["grosir_min"] and qty >= p["grosir_min"]:
        base, label = p["grosir_harga"], "Grosir"
    disc = 0.0
    if tier == "member":
        disc = cfg["diskon_member"]
    elif tier == "reseller":
        disc = cfg["diskon_reseller"]
    price = round(base * (1 - disc / 100) / 100) * 100
    return int(price), label


# ----------------------------------------------------------------------------
# Struk
# ----------------------------------------------------------------------------
def _pad(left: str, right: str, w: int = STRUK_WIDTH) -> str:
    left, right = str(left), str(right)
    space = w - len(left) - len(right)
    if space < 1:
        left = left[: max(0, w - len(right) - 1)]
        space = 1
    return left + " " * space + right


def _center(text: str, w: int = STRUK_WIDTH) -> str:
    return " " * max(0, (w - len(text)) // 2) + text


def struk_text(trx: dict, cfg: dict) -> str:
    hr = "-" * STRUK_WIDTH
    d = datetime.strptime(trx["ts"], "%Y-%m-%d %H:%M:%S")
    lines = [
        _center(cfg["toko_nama"]),
        _center(cfg["toko_alamat"]),
        hr,
        f"No   : TRX-{trx['id']:04d}",
        f"Waktu: {d.strftime('%d/%m/%Y %H:%M')}",
        f"Plgn : {trx['member_nama'] or 'Umum'}",
        hr,
    ]
    for it in trx["items"]:
        lines.append(it["nama"][:STRUK_WIDTH])
        lines.append(
            _pad(f"  {it['qty']} x {it['harga']:,}".replace(",", "."),
                 f"{it['qty'] * it['harga']:,}".replace(",", "."))
        )
    lines.append(hr)
    lines.append(_pad("Subtotal", rp(trx["subtotal"])))
    if trx["potongan_poin"]:
        lines.append(_pad(f"Poin dipakai ({trx['poin_dipakai']})", "-" + rp(trx["potongan_poin"])))
    lines.append(_pad("TOTAL", rp(trx["total"])))
    if trx["metode"] == "tunai":
        lines.append(_pad("Tunai", rp(trx["dibayar"])))
        lines.append(_pad("Kembali", rp(trx["kembali"])))
    else:
        lines.append(_pad("Dibayar", rp(trx["dibayar"])))
        lines.append(_pad("Masuk hutang", rp(trx["hutang"])))
        lines.append(_pad("Total hutang", rp(trx["hutang_total"])))
    if trx["member_nama"]:
        lines.append(hr)
        lines.append(_pad("Poin didapat", f"+{trx['poin_didapat']}"))
        lines.append(_pad("Saldo poin", str(trx["poin_saldo"])))
    lines.append(hr)
    lines.append(_center("Terima kasih, semoga berkah"))
    return "\n".join(lines)


def print_button(text: str) -> None:
    """Tombol cetak: membuka dialog cetak browser untuk isi struk (lebar 58 mm)."""
    safe = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    components.html(
        f"""
        <style>
          @media print {{
            @page {{ size: 58mm auto; margin: 2mm; }}
            button {{ display: none; }}
            pre {{ display: block; }}
          }}
          body {{ margin: 0; font-family: sans-serif; }}
          pre {{ display: none; font-family: 'Courier New', monospace; font-size: 11px; margin: 0 0 8px; }}
          button {{ padding: 9px 16px; font-weight: 600; border-radius: 8px;
                   border: 1px solid #0d6b52; background: #0d6b52; color: #fff; cursor: pointer; }}
        </style>
        <pre id="s">{safe}</pre>
        <button onclick="window.print()">Cetak struk</button>
        """,
        height=60,
    )


# ----------------------------------------------------------------------------
# Login sederhana (opsional): isi APP_PASSWORD di Secrets Streamlit
# ----------------------------------------------------------------------------
def gate() -> None:
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    if not pw or st.session_state.get("auth"):
        return
    st.title("Toko Basmallah")
    entered = st.text_input("Kata sandi kasir", type="password")
    if st.button("Masuk", type="primary"):
        if entered == pw:
            st.session_state["auth"] = True
            st.rerun()
        else:
            st.error("Kata sandi salah.")
    st.stop()


# ----------------------------------------------------------------------------
# Keranjang & checkout
# ----------------------------------------------------------------------------
def init_state() -> None:
    st.session_state.setdefault("cart", {})
    st.session_state.setdefault("last_trx", None)


def clear_cart() -> None:
    st.session_state["cart"] = {}
    for k in [k for k in st.session_state if str(k).startswith("qty_")]:
        del st.session_state[k]


def checkout(lines, member, metode, bayar_input, pakai_poin, cfg):
    """Simpan transaksi. Mengembalikan (dict transaksi, pesan_error)."""
    subtotal = sum(l["harga"] * l["qty"] for l in lines)
    poin_dipakai, potongan = 0, 0
    if member and pakai_poin and member["poin"] > 0:
        poin_dipakai = min(member["poin"], subtotal // cfg["nilai_poin"])
        potongan = poin_dipakai * cfg["nilai_poin"]
    total = subtotal - potongan
    earn = (total // cfg["poin_per"]) if member else 0

    kembali = hutang = 0
    if metode == "tunai":
        if bayar_input < total:
            return None, f"Uang diterima kurang {rp(total - bayar_input)}."
        dibayar, kembali = total, bayar_input - total
        tunai_diterima = bayar_input
    else:
        if not member:
            return None, "Pilih member dulu untuk mencatat hutang."
        dibayar = min(bayar_input, total)
        hutang = total - dibayar
        tunai_diterima = dibayar

    # cek stok terbaru
    for l in lines:
        row = q("SELECT stok FROM produk WHERE id=?", (l["id"],))[0]
        if row["stok"] < l["qty"]:
            return None, f"Stok {l['nama']} tinggal {row['stok']}."

    conn = get_conn()
    ts = now_ts()
    cur = conn.execute(
        "INSERT INTO transaksi(ts,member_id,member_nama,metode,subtotal,poin_dipakai,potongan_poin,"
        "total,poin_didapat,dibayar,kembali,hutang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, member["id"] if member else None, member["nama"] if member else None, metode,
         subtotal, poin_dipakai, potongan, total, earn,
         tunai_diterima if metode == "tunai" else dibayar, kembali, hutang),
    )
    trx_id = cur.lastrowid
    for l in lines:
        conn.execute(
            "INSERT INTO transaksi_item(trx_id,produk_id,nama,qty,harga) VALUES (?,?,?,?,?)",
            (trx_id, l["id"], l["nama"], l["qty"], l["harga"]),
        )
        conn.execute("UPDATE produk SET stok = stok - ? WHERE id=?", (l["qty"], l["id"]))
    poin_saldo = hutang_total = 0
    if member:
        conn.execute(
            "UPDATE member SET poin = poin - ? + ?, hutang = hutang + ? WHERE id=?",
            (poin_dipakai, earn, hutang, member["id"]),
        )
        m2 = conn.execute("SELECT poin, hutang FROM member WHERE id=?", (member["id"],)).fetchone()
        poin_saldo, hutang_total = m2["poin"], m2["hutang"]
    conn.commit()

    return {
        "id": trx_id, "ts": ts, "member_nama": member["nama"] if member else None,
        "metode": metode, "subtotal": subtotal, "poin_dipakai": poin_dipakai,
        "potongan_poin": potongan, "total": total, "poin_didapat": earn,
        "dibayar": tunai_diterima if metode == "tunai" else dibayar,
        "kembali": kembali, "hutang": hutang, "poin_saldo": poin_saldo,
        "hutang_total": hutang_total, "items": lines,
    }, None


# ----------------------------------------------------------------------------
# Halaman: Kasir
# ----------------------------------------------------------------------------
def page_kasir(cfg: dict) -> None:
    left, right = st.columns([1.35, 1], gap="large")
    members = q("SELECT * FROM member ORDER BY nama")
    produk = q("SELECT * FROM produk ORDER BY nama")

    with right:
        st.subheader("Keranjang")
        opsi = {0: "Umum (bukan member)"}
        opsi.update({m["id"]: m["nama"] for m in members})
        member_id = st.selectbox("Pelanggan", list(opsi.keys()), format_func=lambda i: opsi[i], key="pelanggan")
        member = next((m for m in members if m["id"] == member_id), None)
        tier = member["tier"] if member else None
        if member:
            jenis = "Reseller" if tier == "reseller" else "Member"
            info = f"{jenis} · Poin {member['poin']}"
            if member["hutang"] > 0:
                info += f" · Hutang {rp(member['hutang'])}"
            st.caption(info)

    with left:
        st.subheader("Pilih barang")
        cari = st.text_input("Cari barang", placeholder="beras, minyak, gula...", label_visibility="collapsed")
        tampil = [p for p in produk if cari.lower() in p["nama"].lower()] if cari else produk
        if not tampil:
            st.info("Barang tidak ditemukan.")
        else:
            cols = st.columns(3)
            for i, p in enumerate(tampil):
                di_keranjang = st.session_state["cart"].get(p["id"], 0)
                sisa = p["stok"] - di_keranjang
                harga1, _ = unit_price(p, 1, tier, cfg)
                with cols[i % 3]:
                    with st.container(border=True):
                        if p["gambar"]:
                            st.image(p["gambar"], use_container_width=True)
                        st.markdown(f"**{p['nama']}**")
                        st.markdown(f"{rp(harga1)}")
                        if p["grosir_min"]:
                            gh, _ = unit_price(p, p["grosir_min"], tier, cfg)
                            st.caption(f"Grosir ≥{p['grosir_min']}: {rp(gh)} · Stok {sisa}")
                        else:
                            st.caption(f"Stok {sisa}")
                        if st.button("Tambah", key=f"add_{p['id']}", disabled=sisa <= 0, use_container_width=True):
                            st.session_state["cart"][p["id"]] = di_keranjang + 1
                            st.session_state.pop(f"qty_{p['id']}", None)
                            st.rerun()

    with right:
        cart = st.session_state["cart"]
        lines = []
        if not cart:
            st.info("Keranjang kosong. Klik Tambah pada barang.")
        for pid in list(cart.keys()):
            p = next((x for x in produk if x["id"] == pid), None)
            if p is None:
                cart.pop(pid, None)
                continue
            c1, c2, c3 = st.columns([2.2, 1.2, 0.8])
            with c1:
                st.markdown(f"**{p['nama']}**")
            with c2:
                qty = st.number_input(
                    "Jumlah", min_value=1, max_value=max(1, p["stok"]),
                    value=min(cart[pid], max(1, p["stok"])), step=1,
                    key=f"qty_{pid}", label_visibility="collapsed",
                )
            with c3:
                if st.button("Hapus", key=f"del_{pid}"):
                    cart.pop(pid, None)
                    st.session_state.pop(f"qty_{pid}", None)
                    st.rerun()
            cart[pid] = int(qty)
            harga, label = unit_price(p, int(qty), tier, cfg)
            st.caption(f"{int(qty)} × {rp(harga)} = {rp(harga * int(qty))} · {label}")
            lines.append({"id": pid, "nama": p["nama"], "qty": int(qty), "harga": harga})

        subtotal = sum(l["harga"] * l["qty"] for l in lines)
        pakai_poin = False
        if member and member["poin"] > 0 and subtotal > 0:
            pakai_poin = st.checkbox(f"Pakai poin (1 poin = {rp(cfg['nilai_poin'])})")
        potongan = 0
        if pakai_poin:
            potongan = min(member["poin"], subtotal // cfg["nilai_poin"]) * cfg["nilai_poin"]
        total = subtotal - potongan

        st.divider()
        st.write(f"Subtotal: **{rp(subtotal)}**")
        if potongan:
            st.write(f"Potongan poin: **-{rp(potongan)}**")
        st.markdown(f"### Total: {rp(total)}")
        if member and total > 0:
            st.caption(f"Poin didapat: +{total // cfg['poin_per']}")

        metode = st.radio("Pembayaran", ["tunai", "hutang"], horizontal=True,
                          format_func=lambda x: x.capitalize())
        if metode == "tunai":
            bayar = st.number_input("Uang diterima (Rp)", min_value=0, step=1000, value=0)
            st.write(f"Kembalian: **{rp(max(0, bayar - total))}**")
        else:
            bayar = st.number_input("Bayar di muka / DP (Rp, boleh 0)", min_value=0, step=1000, value=0)
            st.write(f"Masuk hutang: **{rp(max(0, total - bayar))}**")
            if not member:
                st.warning("Pilih member dulu untuk mencatat hutang.")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Selesaikan & buat struk", type="primary", disabled=not lines, use_container_width=True):
                trx, err = checkout(lines, member, metode, int(bayar), pakai_poin, cfg)
                if err:
                    st.error(err)
                else:
                    st.session_state["last_trx"] = trx
                    clear_cart()
                    st.rerun()
        with b2:
            if st.button("Kosongkan", disabled=not lines, use_container_width=True):
                clear_cart()
                st.rerun()

    trx = st.session_state.get("last_trx")
    if trx:
        st.divider()
        st.success(f"Transaksi TRX-{trx['id']:04d} selesai.")
        teks = struk_text(trx, cfg)
        s1, s2 = st.columns([1, 1], gap="large")
        with s1:
            st.code(teks, language=None)
        with s2:
            print_button(teks)
            st.link_button("Kirim lewat WhatsApp", "https://wa.me/?text=" + urllib.parse.quote(teks))
            st.caption("Ikon salin ada di pojok kanan atas kotak struk.")
            if st.button("Transaksi baru"):
                st.session_state["last_trx"] = None
                st.rerun()


# ----------------------------------------------------------------------------
# Halaman: Dasbor
# ----------------------------------------------------------------------------
def page_dasbor(cfg: dict) -> None:
    st.subheader("Dasbor")
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    hari_ini = q("SELECT COALESCE(SUM(total),0) AS omzet, COUNT(*) AS n FROM transaksi WHERE substr(ts,1,10)=?", (today,))[0]
    hutang = q("SELECT COALESCE(SUM(hutang),0) AS h FROM member")[0]["h"]
    jml_member = q("SELECT COUNT(*) AS n FROM member")[0]["n"]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Penjualan hari ini", rp(hari_ini["omzet"]))
    k2.metric("Transaksi hari ini", hari_ini["n"])
    k3.metric("Hutang beredar", rp(hutang))
    k4.metric("Member terdaftar", jml_member)

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Penjualan 7 hari terakhir**")
        tanggal = [(datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
        data = df("SELECT substr(ts,1,10) AS tgl, SUM(total) AS omzet FROM transaksi GROUP BY tgl")
        peta = dict(zip(data["tgl"], data["omzet"]))
        grafik = pd.DataFrame({"Tanggal": tanggal, "Penjualan (Rp)": [peta.get(t, 0) for t in tanggal]}).set_index("Tanggal")
        st.bar_chart(grafik)
    with c2:
        st.markdown("**Barang terlaris**")
        top = df(
            "SELECT nama AS Barang, SUM(qty) AS Terjual FROM transaksi_item "
            "GROUP BY nama ORDER BY Terjual DESC LIMIT 5"
        )
        if top.empty:
            st.caption("Belum ada penjualan.")
        else:
            st.bar_chart(top.set_index("Barang"))

    c3, c4 = st.columns(2, gap="large")
    with c3:
        st.markdown("**Stok menipis (10 atau kurang)**")
        low = df("SELECT nama AS Barang, stok AS Stok FROM produk WHERE stok <= 10 ORDER BY stok")
        if low.empty:
            st.caption("Semua stok aman.")
        else:
            st.dataframe(low, hide_index=True, use_container_width=True)
    with c4:
        st.markdown("**Transaksi terakhir**")
        last = df(
            "SELECT 'TRX-' || printf('%04d', id) AS No, ts AS Waktu, COALESCE(member_nama,'Umum') AS Pelanggan, "
            "metode AS Metode, total AS Total FROM transaksi ORDER BY id DESC LIMIT 10"
        )
        st.dataframe(last, hide_index=True, use_container_width=True)

    st.divider()
    st.markdown("**Pengaturan toko, poin, dan diskon**")
    with st.form("pengaturan"):
        a, b = st.columns(2)
        nama = a.text_input("Nama toko di struk", cfg["toko_nama"])
        alamat = b.text_input("Alamat di struk", cfg["toko_alamat"])
        p1, p2, p3, p4 = st.columns(4)
        poin_per = p1.number_input("1 poin tiap belanja (Rp)", min_value=1, value=cfg["poin_per"], step=1000)
        nilai = p2.number_input("Nilai 1 poin (Rp)", min_value=1, value=cfg["nilai_poin"], step=50)
        dm = p3.number_input("Diskon member (%)", min_value=0.0, max_value=50.0, value=cfg["diskon_member"], step=0.5)
        dr = p4.number_input("Diskon reseller (%)", min_value=0.0, max_value=50.0, value=cfg["diskon_reseller"], step=0.5)
        if st.form_submit_button("Simpan pengaturan", type="primary"):
            for k, v in {
                "toko_nama": nama, "toko_alamat": alamat, "poin_per": int(poin_per),
                "nilai_poin": int(nilai), "diskon_member": dm, "diskon_reseller": dr,
            }.items():
                run("INSERT INTO pengaturan(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
            st.success("Pengaturan disimpan.")
            st.rerun()

    st.markdown("**Cadangan data**")
    semua = df(
        "SELECT t.id AS no, t.ts AS waktu, t.member_nama AS pelanggan, t.metode, t.total, "
        "i.nama AS barang, i.qty, i.harga FROM transaksi t JOIN transaksi_item i ON i.trx_id=t.id ORDER BY t.id"
    )
    st.download_button("Unduh riwayat penjualan (CSV)", semua.to_csv(index=False).encode("utf-8"),
                       file_name="penjualan-basmallah.csv", mime="text/csv")


# ----------------------------------------------------------------------------
# Halaman: Produk
# ----------------------------------------------------------------------------
def page_produk() -> None:
    st.subheader("Produk & strata harga")
    with st.expander("Tambah barang baru"):
        with st.form("tambah_produk", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            nama = c1.text_input("Nama barang")
            harga = c2.number_input("Harga eceran (Rp)", min_value=0, step=500)
            stok = c3.number_input("Stok awal", min_value=0, step=1)
            d1, d2, d3, d4 = st.columns(4)
            gmin = d1.number_input("Grosir mulai (jumlah)", min_value=0, step=1)
            gh = d2.number_input("Harga grosir (Rp)", min_value=0, step=500)
            pmin = d3.number_input("Partai mulai (jumlah)", min_value=0, step=1)
            ph = d4.number_input("Harga partai (Rp)", min_value=0, step=500)
            foto = st.file_uploader("Gambar barang (boleh dikosongkan)", type=["jpg", "jpeg", "png", "webp"])
            if st.form_submit_button("Tambah", type="primary"):
                gambar = proses_gambar(foto) if foto is not None else None
                if foto is not None and gambar is None:
                    st.error("File gambar tidak bisa dibaca. Coba file JPG atau PNG lain.")
                elif not nama.strip() or harga <= 0:
                    st.error("Isi nama dan harga eceran.")
                elif (gmin and (gmin < 2 or gh <= 0 or gh >= harga)) or (pmin and (pmin <= (gmin or 1) or ph <= 0 or ph >= (gh or harga))):
                    st.error("Harga grosir harus lebih murah dari eceran, dan harga partai lebih murah dari grosir dengan jumlah mulai lebih besar.")
                else:
                    run(
                        "INSERT INTO produk(nama,harga,grosir_min,grosir_harga,partai_min,partai_harga,stok,gambar) VALUES (?,?,?,?,?,?,?,?)",
                        (nama.strip(), int(harga), int(gmin) or None, int(gh) or None, int(pmin) or None, int(ph) or None, int(stok), gambar),
                    )
                    st.success(f"{nama} ditambahkan.")
                    st.rerun()

    st.caption("Klik sel untuk mengubah harga atau stok, lalu tekan Simpan perubahan. Kosongkan kolom grosir/partai bila tidak ada.")
    data = df("SELECT id, nama, harga, grosir_min, grosir_harga, partai_min, partai_harga, stok FROM produk ORDER BY nama")
    edit = st.data_editor(
        data, hide_index=True, use_container_width=True, disabled=["id"], key="editor_produk",
        column_config={
            "nama": "Barang", "harga": st.column_config.NumberColumn("Eceran", format="%d"),
            "grosir_min": "Grosir mulai", "grosir_harga": st.column_config.NumberColumn("Harga grosir", format="%d"),
            "partai_min": "Partai mulai", "partai_harga": st.column_config.NumberColumn("Harga partai", format="%d"),
            "stok": "Stok",
        },
    )
    if st.button("Simpan perubahan", type="primary"):
        def nz(v):
            return None if pd.isna(v) or int(v) == 0 else int(v)
        for _, r in edit.iterrows():
            run(
                "UPDATE produk SET nama=?, harga=?, grosir_min=?, grosir_harga=?, partai_min=?, partai_harga=?, stok=? WHERE id=?",
                (str(r["nama"]), int(r["harga"]), nz(r["grosir_min"]), nz(r["grosir_harga"]),
                 nz(r["partai_min"]), nz(r["partai_harga"]), int(r["stok"]), int(r["id"])),
            )
        st.success("Perubahan disimpan.")
        st.rerun()


# ----------------------------------------------------------------------------
# Halaman: Gambar produk
# ----------------------------------------------------------------------------
def page_gambar() -> None:
    st.subheader("Gambar produk")
    produk = q("SELECT id, nama, gambar FROM produk ORDER BY nama")
    if not produk:
        st.info("Belum ada barang. Tambahkan barang di menu Produk.")
        return

    tanpa = sum(1 for p in produk if not p["gambar"])
    st.caption(f"{len(produk) - tanpa} dari {len(produk)} barang sudah punya gambar.")

    with st.container(border=True):
        st.markdown("**Tambah atau ganti gambar**")
        nama_by_id = {p["id"]: p["nama"] for p in produk}
        pilih = st.selectbox("Barang", list(nama_by_id.keys()), format_func=lambda i: nama_by_id[i])
        sekarang = next(p for p in produk if p["id"] == pilih)
        c1, c2 = st.columns([1, 2], gap="large")
        with c1:
            if sekarang["gambar"]:
                st.image(sekarang["gambar"], caption="Gambar sekarang", use_container_width=True)
            else:
                st.caption("Belum ada gambar.")
        with c2:
            foto = st.file_uploader(
                "Unggah gambar (JPG, PNG, atau WEBP)", type=["jpg", "jpeg", "png", "webp"], key=f"unggah_{pilih}"
            )
            st.caption("Gambar otomatis dipotong persegi dan dikecilkan supaya ringan.")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Simpan gambar", type="primary", disabled=foto is None, use_container_width=True):
                    data = proses_gambar(foto)
                    if data is None:
                        st.error("File gambar tidak bisa dibaca. Coba file JPG atau PNG lain.")
                    else:
                        run("UPDATE produk SET gambar=? WHERE id=?", (data, pilih))
                        st.success("Gambar tersimpan.")
                        st.rerun()
            with b2:
                if st.button("Hapus gambar", disabled=not sekarang["gambar"], use_container_width=True):
                    run("UPDATE produk SET gambar=NULL WHERE id=?", (pilih,))
                    st.rerun()

    st.markdown("**Semua barang**")
    kolom = st.columns(4)
    for i, p in enumerate(produk):
        with kolom[i % 4]:
            with st.container(border=True):
                if p["gambar"]:
                    st.image(p["gambar"], use_container_width=True)
                else:
                    st.caption("Belum ada gambar")
                st.markdown(f"**{p['nama']}**")


# ----------------------------------------------------------------------------
# Halaman: Member
# ----------------------------------------------------------------------------
def page_member(cfg: dict) -> None:
    st.subheader("Member")
    with st.expander("Daftarkan member baru"):
        with st.form("tambah_member", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            nama = c1.text_input("Nama")
            hp = c2.text_input("No. HP")
            tier = c3.selectbox(
                "Jenis", ["member", "reseller"],
                format_func=lambda t: f"Member (diskon {cfg['diskon_member']:g}%)" if t == "member" else f"Reseller (diskon {cfg['diskon_reseller']:g}%)",
            )
            if st.form_submit_button("Daftarkan", type="primary"):
                if not nama.strip():
                    st.error("Isi nama member.")
                else:
                    run("INSERT INTO member(nama,hp,tier) VALUES (?,?,?)", (nama.strip(), hp.strip() or "-", tier))
                    st.success(f"{nama} terdaftar.")
                    st.rerun()

    data = df("SELECT nama AS Nama, hp AS 'No. HP', tier AS Jenis, poin AS Poin, hutang AS Hutang FROM member ORDER BY nama")
    data["Nilai poin"] = data["Poin"] * cfg["nilai_poin"]
    st.dataframe(data, hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Halaman: Hutang
# ----------------------------------------------------------------------------
def page_hutang() -> None:
    st.subheader("Hutang pelanggan")
    daftar = q("SELECT * FROM member WHERE hutang > 0 ORDER BY hutang DESC")
    st.metric("Total belum dibayar", rp(sum(m["hutang"] for m in daftar)))
    if not daftar:
        st.success("Tidak ada hutang. Alhamdulillah.")
        return
    for m in daftar:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 1.3, 1.5, 1.2])
            c1.markdown(f"**{m['nama']}**")
            c1.caption(m["hp"])
            c2.markdown(f"Sisa: **{rp(m['hutang'])}**")
            jumlah = c3.number_input("Jumlah bayar", min_value=0, max_value=int(m["hutang"]), step=1000,
                                     key=f"bayar_{m['id']}", label_visibility="collapsed")
            with c4:
                if st.button("Catat", key=f"catat_{m['id']}", disabled=jumlah <= 0):
                    run("UPDATE member SET hutang = hutang - ? WHERE id=?", (int(jumlah), m["id"]))
                    run("INSERT INTO pembayaran_hutang(ts,member_id,jumlah) VALUES (?,?,?)", (now_ts(), m["id"], int(jumlah)))
                    st.session_state.pop(f"bayar_{m['id']}", None)
                    st.rerun()
                if st.button("Lunas", key=f"lunas_{m['id']}"):
                    run("UPDATE member SET hutang = 0 WHERE id=?", (m["id"],))
                    run("INSERT INTO pembayaran_hutang(ts,member_id,jumlah) VALUES (?,?,?)", (now_ts(), m["id"], int(m["hutang"])))
                    st.session_state.pop(f"bayar_{m['id']}", None)
                    st.rerun()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    gate()
    init_state()
    cfg = get_settings()
    st.title("Toko Basmallah")
    tabs = st.tabs(["Kasir", "Dasbor", "Produk", "Gambar", "Member", "Hutang"])
    with tabs[0]:
        page_kasir(cfg)
    with tabs[1]:
        page_dasbor(cfg)
    with tabs[2]:
        page_produk()
    with tabs[3]:
        page_gambar()
    with tabs[4]:
        page_member(cfg)
    with tabs[5]:
        page_hutang()


main()
