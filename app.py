import streamlit as st
import json
import pandas as pd
from google import genai
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta

# --- SETUP GOOGLE SHEETS API ---
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
# Ambil kredensial Google dari rahasia Streamlit
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
client_gs = gspread.authorize(creds)
sheet = client_gs.open("Database Gudang").sheet1

# --- SETUP KUNCI ZONA WAKTU (WIB = UTC+7) ---
tz_wib = timezone(timedelta(hours=7))

# --- SETUP GEMINI API ---
# Ambil API key Gemini dari rahasia Streamlit (Cuma buat di app.py)
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

st.set_page_config(page_title="Gudang Tracker", page_icon="📦")
st.title("📦 Sistem Input Gudang (Smart Fallback)")
st.write("Sistem pencocokan mutasi pintar. Ambil yang spesifik, atau ambil apa yang ada!")

laporan = st.text_area("Input Laporan Harian:")

if st.button("Kirim ke AI"):
    if laporan:
        waktu_sekarang = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S")
        
        # Tarik master data gudang saat ini
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
                
                # ========================================================
                # 🧠 BEST PRACTICE: SMART FALLBACK (Ambil apa yang ada!)
                # ========================================================
                if status == "keluar" and not df_gudang.empty:
                    # 1. Cari berdasarkan nama barang saja (yang paling umum)
                    mask_nama = df_gudang['nama_barang'].str.lower().str.contains(nama_ekstrak, na=False)
                    match_df = df_gudang[mask_nama]
                    
                    if not match_df.empty:
                        # 2. Coba cari yang kondisinya pas (Spesifik)
                        exact_match = match_df[
                            match_df['kondisi'].str.lower().str.contains(kondisi_ekstrak, na=False) &
                            match_df['varian'].str.lower().str.contains(varian_ekstrak, na=False)
                        ]
                        
                        if not exact_match.empty:
                            # KETEMU YANG SPESIFIK! Pakai ini.
                            chosen_match = exact_match.iloc[0]
                        else:
                            # 3. GRACEFUL FALLBACK (Kalau gak ketemu yang spesifik, 
                            # ambil baris apa saja yang namanya cocok dari gudang)
                            chosen_match = match_df.iloc[0]
                        
                        # Terapkan hasil (entah itu spesifik atau fallback)
                        item["nama_barang"] = chosen_match.get("nama_barang", item["nama_barang"])
                        item["varian"] = chosen_match.get("varian", "")
                        item["kondisi"] = chosen_match.get("kondisi", "")
                # ========================================================

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