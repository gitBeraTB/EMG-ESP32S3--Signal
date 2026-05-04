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
BAUD_RATE = 115200
MAX_POINTS = 10000
OUTPUT_FILE = 'emg_kayit_ch1.csv'

# Etiket eslemesi
# 1 = REST            ('1' basili tut)
# 2 = ELBOW ROTATION  ('2' basili tut)
# 3 = BICEPS          ('3' basili tut)
# Tus yok = kayit yok (gecis anlarini etiketleme)
LABELS = {'1': 1, '2': 2, '3': 3}
LABEL_NAMES = {0: 'IDLE', 1: 'REST', 2: 'ELBOW ROT', 3: 'BICEPS'}
LABEL_COLORS = {0: '#94a3b8', 1: '#22c55e', 2: '#3b82f6', 3: '#ef4444'}

current_label = 0   # tus yok = idle, kayit yok
active_keys = set()


# ==========================================
# 2. SERIAL + CSV
# ==========================================
print(f"🔄 {SERIAL_PORT} portuna bağlanılıyor...")
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    print("✅ Bağlantı OK!")
except Exception as e:
    print(f"❌ Hata: {e}")
    sys.exit()

try:
    csv_file = open(OUTPUT_FILE, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Zaman (sn)', 'Voltaj (V)', 'Label'])
    print(f"📁 Kayit: '{OUTPUT_FILE}'")
except Exception as e:
    print(f"❌ Dosya hatasi: {e}")
    ser.close()
    sys.exit()

print("-" * 50)
print("ETIKETLEME (PLOT PENCERESI ODAKTA OLMALI):")
print("  Tus yok        -> kayit yok (idle)")
print("  '1' basili tut -> REST")
print("  '2' basili tut -> ELBOW ROTATION")
print("  '3' basili tut -> BICEPS")
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
pg.setConfigOptions(antialias=True)

win = PlotWindow(show=True, title="EMG + Etiketleme")
win.resize(1100, 500)
win.setWindowTitle('EMG Bionic Hand - Etiketli Kayit')
win.setBackground('#0f172a')
win.setFocusPolicy(Qt.StrongFocus)
win.setFocus()

p = win.addPlot()
p.setLabel('bottom', 'Ornekler (Samples)')
p.setLabel('left', 'CH1: Sensor (V)', units='V')
p.setYRange(0, 3.3, padding=0)
p.setXRange(0, MAX_POINTS, padding=0)
p.showGrid(x=True, y=True, alpha=0.3)

curve = p.plot(pen=pg.mkPen(LABEL_COLORS[0], width=2.5))

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

data_buffer = np.zeros(MAX_POINTS)
counts = {1: 0, 2: 0, 3: 0}
last_drawn_label = -1

# ==========================================
# 4. UPDATE
# ==========================================
def update():
    global data_buffer, last_drawn_label
    has_new_data = False
    lines_read = 0

    while ser.in_waiting > 0 and lines_read < 1000:
        try:
            line_str = ser.readline().decode('utf-8', errors='ignore').strip()
            if line_str:
                try:
                    raw_val = float(line_str)
                    voltage_val = (raw_val / 4095.0) * 3.3
                    t = time.time() - start_time
                    if current_label > 0:
                        csv_writer.writerow([f"{t:.4f}", f"{voltage_val:.4f}", current_label])
                        counts[current_label] += 1
                    data_buffer = np.roll(data_buffer, -1)
                    data_buffer[-1] = voltage_val
                    has_new_data = True
                except ValueError:
                    pass
        except Exception:
            pass
        lines_read += 1

    if has_new_data:
        curve.setData(data_buffer)
        if current_label != last_drawn_label:
            label_text.setText(LABEL_NAMES[current_label])
            label_text.setColor(LABEL_COLORS[current_label])
            curve.setPen(pg.mkPen(LABEL_COLORS[current_label], width=2.5))
            last_drawn_label = current_label
        count_text.setText(
            f"REST={counts[1]}  ELBOW={counts[2]}  BICEPS={counts[3]}"
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
        print("-" * 50)
        print(f"REST={counts[1]}  ELBOW={counts[2]}  BICEPS={counts[3]}")
        print(f"Kaydedildi: {OUTPUT_FILE}")
