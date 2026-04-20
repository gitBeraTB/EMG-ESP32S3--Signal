import serial
import matplotlib.pyplot as plt
from collections import deque
import time

# --- AYARLAR ---
PORT = '/dev/cu.usbmodem1101'         # Windows için COM3, Mac için /dev/tty...
BAUD_RATE = 115200
X_LEN = 200           # Ekranda gösterilecek veri nokta sayısı

# Seri portu başlat
try:
    ser = serial.Serial(PORT, BAUD_RATE)
    print(f"Baglanti basarili: {PORT}")
except Exception as e:
    print(f"HATA: Port acilamadi. {e}")
    exit()

# Veri havuzları (Deque)
y_signal = deque([0] * X_LEN, maxlen=X_LEN)  # Ham Sinyal
y_class  = deque([0] * X_LEN, maxlen=X_LEN)  # Tahmin Edilen Sınıf (0, 1, 2...)
y_conf   = deque([0] * X_LEN, maxlen=X_LEN)  # Güven Oranı (Opsiyonel)

# Grafik Ayarları (2 Alt Grafik: Üstte Sinyal, Altta Tahmin)
plt.ion()
fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 8))

# 1. Grafik: EMG Sinyali
line_signal, = ax1.plot(y_signal, color='green', label='EMG Girisi', alpha=0.7)
ax1.set_ylabel("Sinyal Genligi")
ax1.legend(loc='upper right')
ax1.grid(True, alpha=0.3)

# 2. Grafik: Tahmin Edilen Hareket (Classification)
line_class, = ax2.plot(y_class, color='blue', label='Tahmin Edilen Sinif', linewidth=2)
ax2.set_ylabel("Hareket No (Class ID)")
ax2.set_xlabel("Zaman (Ornek)")
ax2.set_ylim(-1, 13) # 0'dan 12'ye kadar sınıflarınız olduğu için aralığı geniş tuttum
ax2.legend(loc='upper right')
ax2.grid(True, alpha=0.3)

print("Veri bekleniyor... (Grafik penceresi acilacak)")

while True:
    if ser.in_waiting:
        try:
            # Satırı oku ve temizle
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            
            # BOŞ veya BİLGİ MESAJLARINI ATLA
            # Eğer satır sayı ile başlamıyorsa veya içinde virgül yoksa atla
            if not line or "," not in line:
                # Debug için ekrana yazdırabiliriz (Opsiyonel)
                # print(f"Bilgi Mesaji: {line}") 
                continue
            
            parts = line.split(',')
            
            # Tam olarak 3 parça veri bekliyoruz (Sinyal, Sınıf, Güven)
            if len(parts) == 3:
                val_signal = float(parts[0]) # Sinyal
                val_class  = int(parts[1])   # Sınıf (0, 1, 2...)
                val_conf   = float(parts[2]) # Güven (0.0 - 1.0)

                # Listelere ekle
                y_signal.append(val_signal)
                y_class.append(val_class)
                
                # Çizgileri güncelle
                line_signal.set_ydata(y_signal)
                line_class.set_ydata(y_class)
                
                # Eksenleri otomatik ölçekle (Sinyal sürekli değiştiği için)
                ax1.relim()
                ax1.autoscale_view(scalex=False, scaley=True)
                
                # Çizimi yenile
                plt.pause(0.001) 
                
                # Konsola da yazdır ki aktığını görelim
                print(f"Sinyal: {val_signal:.2f} | Hareket: {val_class} | Guven: %{val_conf*100:.1f}")
                
        except ValueError:
            # Bazen veri bozuk gelebilir, program çökmesin diye pas geçiyoruz
            continue
        except KeyboardInterrupt:
            print("Cikis yapiliyor...")
            ser.close()
            break