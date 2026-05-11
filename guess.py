#!/usr/bin/env python3
"""
guess.py – ESP32 model inference sonuçlarını gerçek zamanlı görselleştirir.
Serial port üzerinden gelen satırlar şu formatta olmalı:
    Raw:<adc_degeri>, Prediction:<code>
Kod çalıştırılmadan önce gerekli paketleri kurun:
    pip install pyserial matplotlib

Kullanım:
    python guess.py /dev/cu.usbmodem1101   # (MacOS örnek port)
"""

import sys
import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque

# --------------------------- Konfigürasyon ---------------------------
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem1101"
BAUD = 921600
MAX_POINTS = 2000               # gösterilecek maksimum örnek sayısı
# -------------------------------------------------------------------

# Seri portu aç
ser = serial.Serial(PORT, BAUD, timeout=0.1)

# Çizim için iki deque (FIFO) kullanacağız
raw_buf = deque(maxlen=MAX_POINTS)
pred_buf = deque(maxlen=MAX_POINTS)

# Matplotlib figür ve eksenleri
fig, (ax_raw, ax_pred) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
line_raw, = ax_raw.plot([], [], lw=1, color="#10b981")
line_pred, = ax_pred.plot([], [], lw=1, color="#f43f5e")

ax_raw.set_ylabel("Raw ADC (0‑4095)")
ax_raw.set_title("EMG Raw Signal")
ax_raw.grid(True)
ax_pred.set_ylabel("Tahmin (1000/2000)")
ax_pred.set_xlabel("Örnek")
ax_pred.set_title("Model Prediction (REST=1000, BICEPS=2000)")
ax_pred.grid(True)

# Çizim güncelleme fonksiyonu
def update(frame):
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            return line_raw, line_pred
        # Expected format: Raw:<value>, Prediction:<code>
        if line.startswith("Raw:"):
            parts = line.split(",")
            raw_part = parts[0].split(":")[1].strip()
            pred_full = parts[1].split(":")[1].strip() if len(parts) > 1 else "0"
            pred_part = pred_full.split()[0] # "1000 // REST" -> "1000"
            raw_val = int(raw_part)
            pred_val = int(pred_part)
            raw_buf.append(raw_val)
            pred_buf.append(pred_val)
    except Exception as e:
        # Hata olsa bile animasyon devam etsin
        print(f"Parsing error: {e}")

    # Güncel veriyle çizgileri güncelle
    xdata = list(range(len(raw_buf)))
    line_raw.set_data(xdata, list(raw_buf))
    line_pred.set_data(xdata, list(pred_buf))
    # Ekseni otomatik ölçekle (görünür veri aralığı)
    ax_raw.relim(); ax_raw.autoscale_view()
    ax_pred.relim(); ax_pred.autoscale_view()
    return line_raw, line_pred

ani = animation.FuncAnimation(fig, update, interval=30, blit=False)
plt.tight_layout()
plt.show()

ser.close()
