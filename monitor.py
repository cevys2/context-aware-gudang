import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Dashboard Gudang", page_icon="📊", layout="wide")
st.title("📊 Monitor Stok Gudang (Cloud & Time-Synced)")

# --- FITUR CACHE: Biar Streamlit lu nggak lemot ---
# Fungsi ini bakal nyimpen memori tarikan dari Google Sheets selama 60 detik 
# biar aplikasi lu nggak gampang kena limit API Google.
@st.cache_data(ttl=60)
def get_data_from_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    # Ambil kredensial Google dari rahasia Streamlit
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client_gs = gspread.authorize(creds)
    sheet = client_gs.open("Database Gudang").sheet1
    # Tarik semua data dari Sheets jadi format tabel
    data = sheet.get_all_records()
    return pd.DataFrame(data)

# Tarik datanya
try:
    df = get_data_from_sheets()
except Exception as e:
    st.error(f"Gagal narik data dari Google Sheets: {e}")
    st.stop()

if df.empty:
    st.warning("Database masih kosong. Isi dulu dari aplikasi sebelah!")
    st.stop()

# --- OBAT ANTI-ERROR FORMAT WAKTU ---
# Kita pastiin Python ngebaca kolom waktu lu sebagai kalender, bukan sekadar teks
df['waktu_input'] = pd.to_datetime(df['waktu_input'], errors='coerce')

# --- SIDEBAR: SOLUSI DATA BENGKAK ---
with st.sidebar:
    st.header("🛠️ Kontrol Panel")
    st.write("Gunakan menu ini untuk menyaring data mutasi.")
    
    st.subheader("Filter Waktu Mutasi")
    pilihan_waktu = st.radio("Tampilkan log mutasi:", ["7 Hari Terakhir", "30 Hari Terakhir", "Semua Waktu"])
    
    # Logika Filter Tanggal
    sekarang = pd.Timestamp.now()
    if pilihan_waktu == "7 Hari Terakhir":
        df_terfilter = df[df['waktu_input'] >= (sekarang - pd.Timedelta(days=7))]
    elif pilihan_waktu == "30 Hari Terakhir":
        df_terfilter = df[df['waktu_input'] >= (sekarang - pd.Timedelta(days=30))]
    else:
        df_terfilter = df
        
    st.divider()
    
    st.subheader("Filter Barang")
    daftar_barang = df_terfilter['nama_barang'].unique().tolist()
    pilihan_barang = st.multiselect("Pilih Barang:", options=daftar_barang, default=daftar_barang)

# Terapin filter barang
df_terfilter = df_terfilter[df_terfilter['nama_barang'].isin(pilihan_barang)]


# --- LOGIKA STOK (Membaca Laci Schema Baru) ---
# Stok sekarang dihitung lebih presisi berdasarkan nama, satuan, varian, dan kondisi fisik
kolom_group = ['nama_barang', 'satuan', 'varian', 'kondisi']

# Bersihin laci kosong biar perhitungan matematika nggak error
for col in kolom_group:
    if col in df_terfilter.columns:
        df_terfilter[col] = df_terfilter[col].fillna("")

df_masuk = df_terfilter[df_terfilter['status_transaksi'].str.lower() == 'masuk'].groupby(kolom_group)['jumlah'].sum().reset_index()
df_masuk.rename(columns={'jumlah': 'total_masuk'}, inplace=True)

df_keluar = df_terfilter[df_terfilter['status_transaksi'].str.lower() == 'keluar'].groupby(kolom_group)['jumlah'].sum().reset_index()
df_keluar.rename(columns={'jumlah': 'total_keluar'}, inplace=True)

df_stok = pd.merge(df_masuk, df_keluar, on=kolom_group, how='outer').fillna(0)
df_stok['sisa_stok'] = (df_stok['total_masuk'] - df_stok['total_keluar']).astype(int)

def format_nama_lengkap(row):
    detail = []
    if str(row.get('varian', '')) != "": detail.append(str(row['varian']))
    if str(row.get('kondisi', '')) != "": detail.append(str(row['kondisi']))
    
    teks_detail = " - ".join(detail)
    if teks_detail:
        return f"{row['nama_barang']} [{row['satuan']}] ({teks_detail})"
    return f"{row['nama_barang']} [{row['satuan']}]"

df_stok['nama_lengkap'] = df_stok.apply(format_nama_lengkap, axis=1)

def status_warna(stok):
    if stok <= 0: return "Habis / Minus"
    elif stok <= 5: return "Menipis"
    else: return "Aman"

df_stok['status_stok'] = df_stok['sisa_stok'].apply(status_warna)


# --- UI BAGIAN 1: METRIC CARDS ---
total_jenis = len(df_stok)
total_fisik = df_stok['sisa_stok'].sum()
barang_kritis = len(df_stok[df_stok['status_stok'].isin(["Habis / Minus", "Menipis"])])

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("📦 Varian Aktif", total_jenis)
col_m2.metric("🔢 Total Fisik (Keseluruhan)", total_fisik)
col_m3.metric("⚠️ Perlu Restock", barang_kritis)

st.write("") 

# --- UI BAGIAN 2: GRAFIK INTERAKTIF ---
col_v1, col_v2 = st.columns([6, 4]) 

with col_v1:
    if not df_stok.empty:
        fig_bar = px.bar(
            df_stok, x='nama_lengkap', y='sisa_stok', color='status_stok',
            color_discrete_map={"Aman": "#2ecc71", "Menipis": "#f1c40f", "Habis / Minus": "#e74c3c"},
            text='sisa_stok', title="Posisi Stok Per Item"
        )
        fig_bar.update_layout(xaxis_title="", yaxis_title="", showlegend=False, plot_bgcolor='rgba(0,0,0,0)')
        fig_bar.update_traces(textposition='outside')
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("Grafik balok kosong karena filter.")
        
with col_v2:
    df_pie = df_stok[df_stok['sisa_stok'] > 0]
    if not df_pie.empty:
        fig_pie = px.pie(df_pie, values='sisa_stok', names='nama_lengkap', hole=0.5, title="Komposisi Gudang")
        fig_pie.update_layout(legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5))
        fig_pie.update_traces(textinfo='percent')
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Stok kosong, tidak ada komposisi.")

# --- UI BAGIAN 3: TABEL DATA & TOMBOL REFRESH ---
st.write("") 
with st.expander("📁 Lihat Log Mutasi & Detail Tabel"):
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        st.markdown(f"**Log Mutasi ({pilihan_waktu})**")
        st.dataframe(df_terfilter, use_container_width=True)
        
    with col_t2:
        st.markdown("**Rekap Sisa Stok**")
        st.dataframe(df_stok[['nama_lengkap', 'sisa_stok', 'status_stok']], use_container_width=True)

st.write("")
# Tombol ini fungsinya buat maksa aplikasi narik data ulang dari Google Sheets seketika
if st.button("🔄 Segarkan Data (Refresh Google Sheets)"):
    st.cache_data.clear()
    st.rerun()