import sys
import serial
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import time
import csv

# ==========================================
# 1. AYARLAR
# ==========================================
SERIAL_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE = 115200
MAX_POINTS = 10000  # Ekranda görünecek maksimum nokta sayısı
OUTPUT_FILE = 'emg_kayit_ch1.csv' # Kaydedilecek CSV dosyasının adı

print(f"🔄 {SERIAL_PORT} portuna bağlanılıyor...")

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)
    print("✅ Bağlantı Başarılı! Tek Kanal (GPIO 4) Ultra-Hızlı Çizici Başlatılıyor...")
except Exception as e:
    print(f"❌ Bağlantı Hatası: {e}")
    print("Kabloyu, port adını kontrol edin ve Serial Monitor'ün KAPALI olduğundan emin olun.")
    sys.exit()

# CSV Dosyasını Oluştur ve Aç
try:
    csv_file = open(OUTPUT_FILE, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Zaman (sn)', 'Voltaj (V)']) # Başlıkları yaz
    print(f"📁 Veriler aynı zamanda '{OUTPUT_FILE}' dosyasına kaydedilecek.")
except Exception as e:
    print(f"❌ Dosya oluşturma hatası: {e}")
    ser.close()
    sys.exit()

# Başlangıç zamanını al
start_time = time.time()

# ==========================================
# 2. GUI VE GRAFİK KURULUMU (PyQtGraph)
# ==========================================
app = QApplication(sys.argv)
pg.setConfigOptions(antialias=True) 

win = pg.GraphicsLayoutWidget(show=True, title="Gerçek Zamanlı Tek Kanal EMG")
win.resize(1000, 400)
win.setWindowTitle('EMG Bionic Hand - Tek Kanal Osiloskop ve Kaydedici')
win.setBackground('#0f172a') 

p = win.addPlot()
p.setLabel('bottom', 'Örnekler (Samples)')
p.setLabel('left', 'CH1: Sensör (V)', units='V')
p.setYRange(0, 3.3, padding=0)
p.setXRange(0, MAX_POINTS, padding=0)
p.showGrid(x=True, y=True, alpha=0.3)

curve = p.plot(pen=pg.mkPen('#ef4444', width=2.5)) 

data_buffer = np.zeros(MAX_POINTS)

# ==========================================
# 3. GÜNCELLEME DÖNGÜSÜ
# ==========================================
def update():
    global data_buffer
    has_new_data = False
    
    # Serial portta biriken verileri oku
    lines_read = 0
    while ser.in_waiting > 0 and lines_read < 1000:
        try:
            line_str = ser.readline().decode('utf-8', errors='ignore').strip()
            
            if line_str:
                try:
                    raw_val = float(line_str)
                    
                    # ESP32'den ne geliyorsa direkt voltaja çevir
                    voltage_val = (raw_val / 4095.0) * 3.3
                    
                    # --- CSV'YE KAYDETME İŞLEMİ ---
                    current_time = time.time() - start_time
                    csv_writer.writerow([f"{current_time:.4f}", f"{voltage_val:.4f}"])
                    
                    # Veri tamponunu sola kaydır
                    data_buffer = np.roll(data_buffer, -1)
                    data_buffer[-1] = voltage_val
                    
                    has_new_data = True
                except ValueError:
                    pass # Harf veya bozuk karakter geldiyse atla
                    
        except Exception:
            pass
            
        lines_read += 1

    if has_new_data:
        curve.setData(data_buffer)

timer = QTimer()
timer.timeout.connect(update)
timer.start(0)

# ==========================================
# 4. ÇALIŞTIRMA
# ==========================================
if __name__ == '__main__':
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("\nÇizim durduruldu.")
    finally:
        # Program kapatılırken portu ve dosyayı güvenle kapat
        ser.close()
        csv_file.close() 
        print("---------------------------------------------------------")
        print("🔌 Seri port kapatıldı.")
        print(f"🎉 KAYIT TAMAMLANDI! Veriler '{OUTPUT_FILE}' dosyasına başarıyla kaydedildi.")
        print("---------------------------------------------------------")