import streamlit as st
import json
import pandas as pd
from google import genai
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="Gudang Tracker", page_icon="📦")

# ========================================================
# 🔒 GERBANG KEAMANAN TINGKAT TINGGI (PASSWORD GATE)
# ========================================================
def check_password():
    """Mengembalikan True jika user berhasil memasukkan PIN yang benar."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    # Jika sudah sukses login sebelumnya, langsung lolos
    if st.session_state.password_correct:
        return True

    # Tampilan form login jika belum login
    st.markdown("### 🔑 Aplikasi Terkunci")
    password_input = st.text_input("Masukkan PIN Akses Gudang:", type="password")
    
    if st.button("Buka Kunci"):
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun() # Refresh halaman untuk memunculkan aplikasi
        else:
            st.error("❌ PIN Salah! Akses ditolak.")
            
    return False

# Jika satpam tidak meloloskan, hentikan kode di sini!
if not check_password():
    st.stop()
# ========================================================


# --- KODE INTI APLIKASI (Hanya jalan jika lolos PIN di atas) ---
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
client_gs = gspread.authorize(creds)
sheet = client_gs.open("Database Gudang").sheet1

tz_wib = timezone(timedelta(hours=7))
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

st.title("📦 Sistem Input Gudang (Smart Fallback)")
st.write("Akses Aman terverifikasi. Silakan masukkan laporan mutasi.")

laporan = st.text_area("Input Laporan Harian:")

if st.button("Kirim ke AI"):
    if laporan:
        waktu_sekarang = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S")
        
        df_gudang = pd.DataFrame()
        with st.spinner("Mengecek katalog master data gudang..."):
            try:
                data_gudang = sheet.get_all_records()
                if data_gudang:
                    df_gudang = pd.DataFrame(data_gudang)
            except Exception:
                pass

        prompt_system = """
        Lu adalah admin data entry. Ekstrak entitas dari teks ke JSON.
        1. "jumlah" (integer).
        2. "satuan" (default: "pcs").
        3. "status_transaksi" (masuk / keluar).
        4. "nama_barang" (murni nama benda).
        5. "varian" (spesifikasi/ukuran/rasa). Jika tidak ada, isi "".
        6. "kondisi" (penyok/mulus/brand new/old). Jika tidak ada, isi "".
        7. "keterangan_entitas" (pihak terkait). Jika tidak ada, isi "".
        8. "detail_tambahan" (sisa info). Jika tidak ada, isi "".
        Output HANYA JSON mentah tanpa markdown. Array of Objects jika banyak barang.
        """
        
        try:
            response = client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=f"{prompt_system}\n\nTeks Input:\n{laporan}"
            )
            
            hasil_json = json.loads(response.text.strip())
            data_baru = hasil_json if isinstance(hasil_json, list) else [hasil_json]
            
            data_bersih = []
            rows_to_insert = []
            
            for item in data_baru:
                status = item.get("status_transaksi", "").lower()
                nama_ekstrak = item.get("nama_barang", "").lower()
                varian_ekstrak = item.get("varian", "").lower()
                kondisi_ekstrak = item.get("kondisi", "").lower()
                
                if status == "keluar" and not df_gudang.empty:
                    mask_nama = df_gudang['nama_barang'].str.lower().str.contains(nama_ekstrak, na=False)
                    match_df = df_gudang[mask_nama]
                    
                    if not match_df.empty:
                        exact_match = match_df[
                            match_df['kondisi'].str.lower().str.contains(kondisi_ekstrak, na=False) &
                            match_df['varian'].str.lower().str.contains(varian_ekstrak, na=False)
                        ]
                        
                        if not exact_match.empty:
                            chosen_match = exact_match.iloc[0]
                        else:
                            chosen_match = match_df.iloc[0]
                        
                        item["nama_barang"] = chosen_match.get("nama_barang", item["nama_barang"])
                        item["varian"] = chosen_match.get("varian", "")
                        item["kondisi"] = chosen_match.get("kondisi", "")

                data_dict = {
                    "waktu_input": waktu_sekarang,
                    "nama_barang": item.get("nama_barang", "Tidak Diketahui"),
                    "jumlah": item.get("jumlah", 0),
                    "satuan": item.get("satuan", "pcs"),
                    "status_transaksi": status,
                    "varian": item.get("varian", ""),
                    "kondisi": item.get("kondisi", ""),
                    "keterangan_entitas": item.get("keterangan_entitas", ""),
                    "detail_tambahan": item.get("detail_tambahan", "")
                }
                data_bersih.append(data_dict)
                
                rows_to_insert.append([
                    data_dict["waktu_input"],
                    data_dict["nama_barang"],
                    data_dict["jumlah"],
                    data_dict["satuan"],
                    data_dict["status_transaksi"],
                    data_dict["varian"],
                    data_dict["kondisi"],
                    data_dict["keterangan_entitas"],
                    data_dict["detail_tambahan"]
                ])
                
            sheet.append_rows(rows_to_insert)
            st.success("Aman! Data berhasil diproses dengan fitur Fallback Pintar.")
            st.dataframe(pd.DataFrame(data_bersih))
            
        except json.JSONDecodeError:
            st.error("Gagal parse JSON. Hasil mentah:")
            st.write(response.text)
        except Exception as e:
            st.error(f"Ada error sistem: {e}")
            
    else:
        st.warning("Kotaknya diisi dulu, bos!")
