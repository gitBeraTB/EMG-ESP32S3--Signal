import sys
import serial
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, Qt
import time
import csv

# ==========================================
# 1. AYARLAR
# ==========================================
SERIAL_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE   = 115200
MAX_POINTS  = 10000
OUTPUT_FILE = 'emg_3ch_training_data.csv'

# Etiket eslemesi — tusu BASILI TUT
# 0 = IDLE (tus yok, kayit yapilmaz)
# 1 = REST
# 2 = ELBOW (dirsek bukme/acma)
# 3 = SQUEEZE (nesne sikma/birakma)
# 4 = POWER_GRIP (guclu kavrama)
LABELS = {'1': 1, '2': 2, '3': 3, '4': 4}
LABEL_NAMES  = {0: 'IDLE', 1: 'REST', 2: 'ELBOW', 3: 'SQUEEZE', 4: 'POWER GRIP'}
LABEL_COLORS = {0: '#94a3b8', 1: '#22c55e', 2: '#3b82f6', 3: '#f59e0b', 4: '#ef4444'}

current_label = 0
active_keys   = set()

# ==========================================
# 2. SERIAL + CSV
# ==========================================
print(f"🔄 {SERIAL_PORT} portuna baglaniliyor...")
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    print("✅ Baglanti OK!")
except Exception as e:
    print(f"❌ Hata: {e}")
    sys.exit()

try:
    csv_file   = open(OUTPUT_FILE, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Zaman (sn)', 'CH1', 'CH2', 'CH3', 'Label'])
    print(f"📁 Kayit: '{OUTPUT_FILE}'")
except Exception as e:
    print(f"❌ Dosya hatasi: {e}")
    ser.close()
    sys.exit()

print("-" * 55)
print("ETIKETLEME (PLOT PENCERESI ODAKTA OLMALI):")
print("  Tus yok        -> kayit yok (IDLE)")
print("  '1' basili tut -> REST")
print("  '2' basili tut -> ELBOW (dirsek)")
print("  '3' basili tut -> SQUEEZE (sikma/birakma)")
print("  '4' basili tut -> POWER GRIP")
print("-" * 55)

start_time = time.time()

# ==========================================
# 3. GUI — 3 Kanalli PlotWindow
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
pg.setConfigOptions(antialias=True)

win = PlotWindow(show=True, title="3-Kanal EMG + Etiketleme")
win.resize(1200, 750)
win.setWindowTitle('EMG Bionic Hand — 3 Kanal Etiketli Kayit')
win.setBackground('#0f172a')
win.setFocusPolicy(Qt.StrongFocus)
win.setFocus()

# --- 3 Alt Grafik ---
CH_NAMES  = ['CH1: Biceps', 'CH2: On Kol Ic', 'CH3: On Kol Dis']
CH_COLORS = ['#10b981', '#3b82f6', '#f59e0b']

plots  = []
curves = []
for i in range(3):
    p = win.addPlot(row=i, col=0)
    p.setLabel('left', CH_NAMES[i], units='V')
    p.setYRange(0, 3.3, padding=0)
    p.setXRange(0, MAX_POINTS, padding=0)
    p.showGrid(x=True, y=True, alpha=0.3)
    if i < 2:
        p.hideAxis('bottom')
    else:
        p.setLabel('bottom', 'Ornekler')
    c = p.plot(pen=pg.mkPen(CH_COLORS[i], width=2))
    plots.append(p)
    curves.append(c)

# Etiket gostergesi (CH1 grafiğinin ustune)
label_text = pg.TextItem(text='IDLE', color=LABEL_COLORS[0], anchor=(0, 0))
label_text.setPos(50, 3.15)
font = pg.QtGui.QFont()
font.setPointSize(24)
font.setBold(True)
label_text.setFont(font)
plots[0].addItem(label_text)

# Sayac gostergesi
count_text = pg.TextItem(text='', color='#cbd5e1', anchor=(1, 0))
count_text.setPos(MAX_POINTS - 50, 3.15)
font2 = pg.QtGui.QFont()
font2.setPointSize(10)
count_text.setFont(font2)
plots[0].addItem(count_text)

# Veri tamponlari
data_bufs = [np.zeros(MAX_POINTS) for _ in range(3)]
counts    = {1: 0, 2: 0, 3: 0, 4: 0}
last_drawn_label = -1

# ==========================================
# 4. UPDATE
# ==========================================
def update():
    global last_drawn_label
    has_new = False
    lines_read = 0

    while ser.in_waiting > 0 and lines_read < 1000:
        try:
            line_str = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line_str:
                continue
            parts = line_str.split(',')
            if len(parts) != 3:
                continue
            try:
                raw_vals = [int(p) for p in parts]
            except ValueError:
                continue

            voltages = [(v / 4095.0) * 3.3 for v in raw_vals]
            t = time.time() - start_time

            # Etiket varsa CSV'ye yaz
            if current_label > 0:
                csv_writer.writerow([f"{t:.4f}",
                                     f"{voltages[0]:.4f}",
                                     f"{voltages[1]:.4f}",
                                     f"{voltages[2]:.4f}",
                                     current_label])
                counts[current_label] += 1

            # Tamponlara ekle
            for c in range(3):
                data_bufs[c] = np.roll(data_bufs[c], -1)
                data_bufs[c][-1] = voltages[c]
            has_new = True

        except Exception:
            pass
        lines_read += 1

    if has_new:
        for c in range(3):
            curves[c].setData(data_bufs[c])

        if current_label != last_drawn_label:
            label_text.setText(LABEL_NAMES[current_label])
            label_text.setColor(LABEL_COLORS[current_label])
            # Tum kanallarin cizgi rengini aktif etikete gore degistir
            for c in range(3):
                if current_label == 0:
                    curves[c].setPen(pg.mkPen(CH_COLORS[c], width=2))
                else:
                    curves[c].setPen(pg.mkPen(LABEL_COLORS[current_label], width=2.5))
            last_drawn_label = current_label

        count_text.setText(
            f"REST={counts[1]}  ELBOW={counts[2]}  "
            f"SQUEEZE={counts[3]}  GRIP={counts[4]}"
        )


timer = QTimer()
timer.timeout.connect(update)
timer.start(0)

# ==========================================
# 5. CALISTIR
# ==========================================
if __name__ == '__main__':
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        ser.close()
        csv_file.close()
        print("-" * 55)
        print(f"REST={counts[1]}  ELBOW={counts[2]}  "
              f"SQUEEZE={counts[3]}  GRIP={counts[4]}")
        print(f"Kaydedildi: {OUTPUT_FILE}")
