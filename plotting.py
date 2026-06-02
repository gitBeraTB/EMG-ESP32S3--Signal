import sys
import os
import serial
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
import time
import csv
import re

# ==========================================
# 1. AYARLAR
# ==========================================
SERIAL_PORT = 'COM4'
BAUD_RATE   = 921600       # main.cpp ile ayni
MAX_POINTS  = 10000        # 5 sn @ 2 kHz (kasilmalari rahat gormek icin)
OUTPUT_DIR  = 'kayitlar'   # tum kayitlarin toplandigi klasor

# ==========================================
# 1b. KAYIT ADI (plot acilmadan once terminalden sorulur)
# ==========================================
os.makedirs(OUTPUT_DIR, exist_ok=True)
rec_name = input("Kayıt adı giriniz: ").strip()
if not rec_name:
    print("Hata: kayıt adı boş olamaz.")
    sys.exit()
# Dosya adi icin guvenli hale getir (bosluk -> _, gecersiz karakterleri temizle)
safe_name = re.sub(r'[^0-9A-Za-z._-]', '_', rec_name.replace(' ', '_'))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"emg_kayit_{safe_name}.csv")

# NOT: ESP32 MODE_COLLECT modunda olmali (main.cpp). Aksi halde CSV yerine
# tahmin metni gelir ve hicbir satir ayrıştirilamaz.
NUM_CH       = 3
CH_NAMES     = ['CH1', 'CH2', 'CH3']
CH_COLORS    = ['#ef4444', '#22c55e', '#eab308']   # kirmizi / yesil / sari

# Etiket eslemesi (PER-KANAL):
#   '1' = CH1 REST   '2' = CH1 SQUEEZE   (cene)
#   '3' = CH2 REST   '4' = CH2 SQUEEZE   (bilek)
#   '5' = CH3 REST   '6' = CH3 SQUEEZE   (dirsek/biceps)
#   (0 = kayit yok / IDLE)
LABELS       = {'1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6}
LABEL_NAMES  = {0: 'IDLE',
                1: 'CH1 REST', 2: 'CH1 SQUEEZE',
                3: 'CH2 REST', 4: 'CH2 SQUEEZE',
                5: 'CH3 REST', 6: 'CH3 SQUEEZE'}
LABEL_COLORS = {0: '#94a3b8',
                1: '#22c55e', 2: '#ef4444',
                3: '#38bdf8', 4: '#f97316',
                5: '#a78bfa', 6: '#eab308'}

current_label = 0
active_keys   = set()

# ==========================================
# 2. SERIAL + CSV
# ==========================================
print(f"{SERIAL_PORT} portuna baglaniliyor...")
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    print("Baglanti OK")
except Exception as e:
    print(f"Hata: {e}")
    sys.exit()

try:
    csv_file   = open(OUTPUT_FILE, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    # Label = 1..6 (hangi kanal + REST/SQUEEZE). Egitim scripti bunu cozumler.
    csv_writer.writerow(['Zaman (sn)', 'CH1 (V)', 'CH2 (V)', 'CH3 (V)', 'Label'])
    print(f"Kayit: {OUTPUT_FILE}")
except Exception as e:
    print(f"Dosya hatasi: {e}")
    ser.close()
    sys.exit()

print("-" * 50)
print("ETIKETLEME (PLOT PENCERESI ODAKTA OLMALI):")
print("  Tus yok        -> kayit yok")
print("  '1' basili tut -> CH1 REST")
print("  '2' basili tut -> CH1 SQUEEZE")
print("  '3' basili tut -> CH2 REST")
print("  '4' basili tut -> CH2 SQUEEZE")
print("  '5' basili tut -> CH3 REST")
print("  '6' basili tut -> CH3 SQUEEZE")
print("-" * 50)

start_time = time.time()

# ==========================================
# 3. GUI - Qt klavye event'leri
# ==========================================
class PlotWindow(pg.GraphicsLayoutWidget):
    def keyPressEvent(self, event):
        global current_label
        if event.isAutoRepeat():
            return
        ch = event.text()
        if ch in LABELS:
            active_keys.add(ch)
            current_label = LABELS[ch]
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        global current_label
        if event.isAutoRepeat():
            return
        ch = event.text()
        if ch in active_keys:
            active_keys.discard(ch)
            current_label = LABELS[next(iter(active_keys))] if active_keys else 0
        else:
            super().keyReleaseEvent(event)

app = QApplication(sys.argv)
pg.setConfigOptions(antialias=False)   # cok nokta cizerken antialias yavaslatir

win = PlotWindow(show=True, title="EMG + Etiketleme")
win.resize(1100, 500)
win.setWindowTitle('EMG Bionic Hand - Etiketli Kayit (2CH)')
win.setBackground('#0f172a')
win.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
win.setFocus()

p = win.addPlot()
p.addLegend(offset=(10, 10))
p.setLabel('bottom', 'Ornekler (Samples)')
p.setLabel('left', 'Sensor (V)', units='V')
p.setYRange(0, 3.3, padding=0)
p.setXRange(0, MAX_POINTS, padding=0)
p.showGrid(x=True, y=True, alpha=0.3)
p.setDownsampling(auto=True, mode='peak')   # uzun egriyi otomatik seyreltir
p.setClipToView(True)

# Her kanal icin ayri egri
curves = [
    p.plot(pen=pg.mkPen(CH_COLORS[i], width=1.8), name=CH_NAMES[i])
    for i in range(NUM_CH)
]

label_text = pg.TextItem(text='IDLE', color=LABEL_COLORS[0], anchor=(0, 0))
label_text.setPos(50, 3.15)
font = pg.QtGui.QFont()
font.setPointSize(28)
font.setBold(True)
label_text.setFont(font)
p.addItem(label_text)

count_text = pg.TextItem(text='', color='#cbd5e1', anchor=(1, 0))
count_text.setPos(MAX_POINTS - 50, 3.15)
font2 = pg.QtGui.QFont()
font2.setPointSize(11)
count_text.setFont(font2)
p.addItem(count_text)

data_buffer = np.zeros((NUM_CH, MAX_POINTS))
counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
last_drawn_label = -1
serial_leftover = ''   # bir tick'te yarim kalan satir bir sonrakine tasinir

# ==========================================
# 4. UPDATE
# ==========================================
def update():
    global data_buffer, last_drawn_label, serial_leftover

    # --- 1) Bekleyen tum baytlari TEK seferde oku ---
    n_waiting = ser.in_waiting
    if n_waiting == 0:
        return
    chunk = ser.read(n_waiting).decode('utf-8', errors='ignore')
    serial_leftover += chunk
    lines = serial_leftover.split('\n')
    serial_leftover = lines[-1]      # son parca yarim olabilir
    lines = lines[:-1]

    # --- 2) Bu tick'te gelen tum ornekleri biriktir ---
    new_samples = []
    for line_str in lines:
        line_str = line_str.strip()
        if not line_str:
            continue
        parts = line_str.split(',')
        if len(parts) != NUM_CH:
            continue
        try:
            volts = [(float(p_) / 4095.0) * 3.3 for p_ in parts]
        except ValueError:
            continue
        new_samples.append(volts)
        if current_label > 0:
            t = time.time() - start_time
            csv_writer.writerow(
                [f"{t:.4f}"] + [f"{v:.4f}" for v in volts] + [current_label]
            )
            counts[current_label] += 1

    if not new_samples:
        return

    # --- 3) Buffer'i ornek-ornek degil, TEK roll ile guncelle ---
    arr = np.asarray(new_samples).T          # sekil: (NUM_CH, n)
    n = arr.shape[1]
    if n >= MAX_POINTS:
        data_buffer[:] = arr[:, -MAX_POINTS:]
    else:
        data_buffer = np.roll(data_buffer, -n, axis=1)
        data_buffer[:, -n:] = arr

    # --- 4) Tick basina bir kez ciz ---
    for i in range(NUM_CH):
        curves[i].setData(data_buffer[i])
    if current_label != last_drawn_label:
        label_text.setText(LABEL_NAMES[current_label])
        label_text.setColor(LABEL_COLORS[current_label])
        last_drawn_label = current_label
    count_text.setText(
        f"CH1 R={counts[1]} S={counts[2]}   CH2 R={counts[3]} S={counts[4]}"
        f"   CH3 R={counts[5]} S={counts[6]}"
    )

timer = QTimer()
timer.timeout.connect(update)
timer.start(33)   # ~30 FPS (sinirsiz yerine; okuma toplu yapildigi icin veri kaybi olmaz)

# ==========================================
# 5. CALISTIR
# ==========================================
if __name__ == '__main__':
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        ser.close()
        csv_file.close()
        print("-" * 50)
        print(f"CH1  REST={counts[1]}  SQUEEZE={counts[2]}")
        print(f"CH2  REST={counts[3]}  SQUEEZE={counts[4]}")
        print(f"CH3  REST={counts[5]}  SQUEEZE={counts[6]}")
        print(f"Kaydedildi: {OUTPUT_FILE}")
