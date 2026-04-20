import scipy.io
import numpy as np
from sklearn.preprocessing import StandardScaler
import os

# --- AYARLAR ---
MAT_FILE = 'S1_A1_E1.mat'  # Başındaki / işaretini kaldırdık
OUTPUT_H = 'test_vectors.h'
NUM_CHANNELS = 4           # MODELİN 4 KANAL BEKLİYOR! (10 DEĞİL)
HEDEF_HAREKET = 17         # Yumruk (Hand Close)

print(f"Loading {MAT_FILE}...")
if not os.path.exists(MAT_FILE):
    raise SystemExit(f"HATA: {MAT_FILE} dosyası bulunamadı! Lütfen yükleyin.")

mat = scipy.io.loadmat(MAT_FILE)
emg_data = mat['emg']       
stimulus = mat['restimulus'] # 'stimulus' yerine 'restimulus' daha güvenilirdir

# --- 1. ÖNCE NORMALİZASYON (MODELİN DİLİNDEN KONUŞMAK İÇİN) ---
# Model StandardScaler ile eğitildi, test verisi de öyle olmalı.
# Sadece ilk 4 kanalı alıyoruz.
raw_data = emg_data[:, :NUM_CHANNELS]

print("Applying StandardScaler (Normalization)...")
scaler = StandardScaler()
# Tüm veriye fit ediyoruz ki modelin eğitimdeki dağılımına benzesin
scaled_data = scaler.fit_transform(raw_data)

# --- 2. SENARYO OLUŞTURMA (OTOMATİK SEÇİM) ---
# Elle index aramak yerine, kod kendisi bulsun.

# İndeksleri bul
idx_rest = np.where(stimulus == 0)[0]             # Dinlenme anları
idx_move = np.where(stimulus == HEDEF_HAREKET)[0] # Yumruk anları

if len(idx_move) == 0:
    raise SystemExit(f"HATA: Dosyada Hareket {HEDEF_HAREKET} (Yumruk) bulunamadı!")

# Senaryo: Dinlenme (50) -> Hareket (50) -> Dinlenme (50) -> Hareket (50)
# Hareketin ortasından (en güçlü yerinden) alalım
mid_move = len(idx_move) // 2

vec_rest1 = scaled_data[idx_rest[0:50]]           # Dinlenme Başı
vec_move1 = scaled_data[idx_move[mid_move:mid_move+50]] # Hareket Ortası
vec_rest2 = scaled_data[idx_rest[200:250]]        # Başka bir dinlenme
vec_move2 = scaled_data[idx_move[mid_move+100:mid_move+150]] # Hareketin devamı

# Hepsini Birleştir
final_test_vector = np.concatenate((vec_rest1, vec_move1, vec_rest2, vec_move2))

print(f"Test Vector Created. Shape: {final_test_vector.shape}") # (200, 4) olmalı

# --- 3. HEADER DOSYASI OLUŞTUR ---
print(f"Writing to {OUTPUT_H}...")
with open(OUTPUT_H, "w") as f:
    f.write(f"#ifndef TEST_VECTORS_H\n#define TEST_VECTORS_H\n\n")
    f.write(f"const int TEST_DATA_LEN = {len(final_test_vector)};\n")
    # C++ kodunda dizi boyutu sabit olduğu için [][4] formatını koruyoruz
    f.write(f"const float test_data[][{NUM_CHANNELS}] = {{\n")
    
    for row in final_test_vector:
        f.write("    {")
        f.write(", ".join([f"{x:.4f}" for x in row])) 
        f.write("},\n")
    f.write("};\n\n")
    f.write("#endif")

print(f"DONE! '{OUTPUT_H}' oluşturuldu. İndirip ESP32 src klasörüne atabilirsin.")

# Colab'dan indirmek için (Eğer Colab kullanıyorsan)
try:
    from google.colab import files
    files.download(OUTPUT_H)
except:
    pass