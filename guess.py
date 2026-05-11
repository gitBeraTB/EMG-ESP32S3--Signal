#!/usr/bin/env python3
"""
guess.py — 3 Kanalli ESP32 model inference sonuclarini gercek zamanli gorsellestir.

Serial port uzerinden gelen satirlar su formatta olmali:
    Raw:CH1,CH2,CH3, Prediction:CODE

Kurulum:
    pip install pyserial matplotlib

Kullanim:
    python guess.py /dev/cu.usbmodem1101
"""

import sys
import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque

# ==================== KONFIGÜRASYON ====================
PORT       = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem1101"
BAUD       = 115200
MAX_POINTS = 2000
# =======================================================

GESTURE_NAMES = {
    0: "REST",
    1000: "ELBOW",
    2000: "SQUEEZE",
    3000: "POWER GRIP",
}

# Seri port
ser = serial.Serial(PORT, BAUD, timeout=0.1)

# Tamponlar — 3 kanal + 1 prediction
ch1_buf  = deque(maxlen=MAX_POINTS)
ch2_buf  = deque(maxlen=MAX_POINTS)
ch3_buf  = deque(maxlen=MAX_POINTS)
pred_buf = deque(maxlen=MAX_POINTS)

# Matplotlib — 4 alt grafik
fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
fig.suptitle("3-Kanal EMG — Gercek Zamanli Tahmin", fontsize=14, fontweight='bold')

line_ch1,  = axes[0].plot([], [], lw=1, color="#10b981")
line_ch2,  = axes[1].plot([], [], lw=1, color="#3b82f6")
line_ch3,  = axes[2].plot([], [], lw=1, color="#f59e0b")
line_pred, = axes[3].plot([], [], lw=1.5, color="#ef4444")

axes[0].set_ylabel("CH1 Biceps")
axes[0].set_title("Biceps")
axes[0].grid(True, alpha=0.3)

axes[1].set_ylabel("CH2 On Kol Ic")
axes[1].set_title("On Kol Ic")
axes[1].grid(True, alpha=0.3)

axes[2].set_ylabel("CH3 On Kol Dis")
axes[2].set_title("On Kol Dis")
axes[2].grid(True, alpha=0.3)

axes[3].set_ylabel("Tahmin")
axes[3].set_xlabel("Ornek")
axes[3].set_title("Model Prediction (0=REST, 1000=ELBOW, 2000=SQUEEZE, 3000=GRIP)")
axes[3].set_yticks([0, 1000, 2000, 3000])
axes[3].set_yticklabels(["REST", "ELBOW", "SQUEEZE", "GRIP"])
axes[3].grid(True, alpha=0.3)

# Son tahmin gostergesi
pred_text = axes[3].text(0.98, 0.85, "", transform=axes[3].transAxes,
                         fontsize=14, fontweight='bold', color='#ef4444',
                         ha='right', va='top',
                         bbox=dict(boxstyle='round,pad=0.3',
                                   facecolor='#1e293b', alpha=0.9))


def update(frame):
    """Her frame'de Serial'den veri oku ve grafikleri guncelle."""
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line or not line.startswith("Raw:"):
            return line_ch1, line_ch2, line_ch3, line_pred

        # Format: Raw:CH1,CH2,CH3, Prediction:CODE ...
        # Ornek: Raw:2048,2050,2045, Prediction:1000 // ELBOW
        parts = line.split(", Prediction:")
        if len(parts) != 2:
            return line_ch1, line_ch2, line_ch3, line_pred

        raw_part  = parts[0].replace("Raw:", "")
        pred_part = parts[1].strip()

        # Raw kanallari parse et
        raw_vals = raw_part.split(",")
        if len(raw_vals) != 3:
            return line_ch1, line_ch2, line_ch3, line_pred

        ch1_val = int(raw_vals[0])
        ch2_val = int(raw_vals[1])
        ch3_val = int(raw_vals[2])

        # Prediction parse et (sayi kismini al)
        pred_val = int(pred_part.split()[0])

        ch1_buf.append(ch1_val)
        ch2_buf.append(ch2_val)
        ch3_buf.append(ch3_val)
        pred_buf.append(pred_val)

        # Tahmin metnini guncelle
        gesture = GESTURE_NAMES.get(pred_val, f"? ({pred_val})")
        pred_text.set_text(f">> {gesture}")

    except Exception as e:
        print(f"Parse error: {e}")

    # Grafikleri guncelle
    xdata = list(range(len(ch1_buf)))
    line_ch1.set_data(xdata, list(ch1_buf))
    line_ch2.set_data(xdata, list(ch2_buf))
    line_ch3.set_data(xdata, list(ch3_buf))
    line_pred.set_data(xdata, list(pred_buf))

    for ax in axes:
        ax.relim()
        ax.autoscale_view()

    return line_ch1, line_ch2, line_ch3, line_pred


ani = animation.FuncAnimation(fig, update, interval=30, blit=False)
plt.tight_layout()
plt.show()
ser.close()
