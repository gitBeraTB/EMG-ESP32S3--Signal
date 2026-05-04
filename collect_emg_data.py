import serial
import csv
import time
from pynput import keyboard

# --- AYARLAR ---
SERIAL_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE = 115200
FILE_NAME = "emg_training_data.csv"

# Etiket eslemesi
LABELS = {
    '1': 1,  # REST
    '2': 2,  # BICEPS kasili (izometrik)
    '3': 3,  # ELBOW hareketi (dinamik)
}
LABEL_NAMES = {0: "GECIS", 1: "REST", 2: "BICEPS", 3: "ELBOW"}

# --- GLOBAL ---
current_label = 0
running = True
active_keys = set()

# --- KLAVYE ---
def on_press(key):
    global current_label, running
    try:
        ch = key.char
        if ch in LABELS:
            active_keys.add(ch)
            current_label = LABELS[ch]
    except AttributeError:
        if key == keyboard.Key.esc:
            running = False

def on_release(key):
    global current_label
    try:
        ch = key.char
        if ch in active_keys:
            active_keys.discard(ch)
        if active_keys:
            current_label = LABELS[next(iter(active_keys))]
        else:
            current_label = 0  # gecis / etiketsiz
    except AttributeError:
        pass

# --- KAYIT ---
def record_data():
    global running
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"Baglanti OK: {SERIAL_PORT}")
        print("-" * 50)
        print("KULLANIM (tusu BASILI TUT):")
        print("  '1' -> REST (kol gevsek)")
        print("  '2' -> BICEPS KASILI (izometrik sik)")
        print("  '3' -> ELBOW HAREKETI (dirsek buk-ac)")
        print("  Tus yok -> 0 (gecis, egitime girmez)")
        print("  ESC    -> kaydet & cik")
        print("-" * 50)
        print("Onerilen: her sinif icin 20-25 tekrar (~3sn)")
        print("Siniflari KARISTIR (1,3,2,1,2,3,...)")
        print("-" * 50)

        with open(FILE_NAME, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "EMG_Value", "Label"])
            t0 = time.time()
            count = 0
            last_print = 0
            counts_per_label = {0: 0, 1: 0, 2: 0, 3: 0}
            while running:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line.isdigit():
                        w.writerow([time.time() - t0, int(line), current_label])
                        count += 1
                        counts_per_label[current_label] += 1
                        if count - last_print >= 1000:
                            print(f"#{count}  anlik={LABEL_NAMES[current_label]}  "
                                  f"REST={counts_per_label[1]} "
                                  f"BICEPS={counts_per_label[2]} "
                                  f"ELBOW={counts_per_label[3]}")
                            last_print = count
    except Exception as e:
        print(f"HATA: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
        print(f"\nKaydedildi: {FILE_NAME}")
        print(f"Sinif sayilari: REST={counts_per_label[1]}, "
              f"BICEPS={counts_per_label[2]}, ELBOW={counts_per_label[3]}")

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()
record_data()
