import serial
import csv
import time
from pynput import keyboard

# --- AYARLAR ---
SERIAL_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE   = 115200
FILE_NAME   = "emg_3ch_training_data.csv"

# Etiket eslemesi — tusu BASILI TUT
LABELS = {
    '1': 1,   # REST
    '2': 2,   # ELBOW (dirsek bukme/acma)
    '3': 3,   # SQUEEZE (nesne sikma/birakma)
    '4': 4,   # POWER_GRIP (guclu kavrama)
}
LABEL_NAMES = {
    0: "GECIS (kayit yok)",
    1: "REST",
    2: "ELBOW",
    3: "SQUEEZE",
    4: "POWER_GRIP",
}

# --- GLOBAL ---
current_label = 0
running       = True
active_keys   = set()

# --- KLAVYE ---
def on_press(key):
    global current_label
    try:
        ch = key.char
        if ch in LABELS:
            active_keys.add(ch)
            current_label = LABELS[ch]
    except AttributeError:
        if key == keyboard.Key.esc:
            global running
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
            current_label = 0   # gecis — kayit yok
    except AttributeError:
        pass

# --- KAYIT ---
def record_data():
    global running
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"Baglanti OK: {SERIAL_PORT}")
        print("-" * 55)
        print("KULLANIM (tusu BASILI TUT):")
        print("  '1' -> REST          (kol gevsek)")
        print("  '2' -> ELBOW         (dirsek bukme/acma)")
        print("  '3' -> SQUEEZE       (nesne sikma/birakma)")
        print("  '4' -> POWER_GRIP    (guclu kavrama)")
        print("  Tus yok -> 0 (gecis, egitime girmez)")
        print("  ESC     -> kaydet & cik")
        print("-" * 55)
        print("Onerilen: her sinif icin 20-25 tekrar (~3sn)")
        print("Siniflari KARISTIR (1,3,2,4,1,4,2,3,...)")
        print("-" * 55)

        with open(FILE_NAME, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Zaman (sn)", "CH1", "CH2", "CH3", "Label"])
            t0    = time.time()
            count = 0
            last_print = 0

            while running:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    parts = line.split(',')
                    if len(parts) != 3:
                        continue
                    try:
                        raw_vals = [int(p) for p in parts]
                    except ValueError:
                        continue

                    voltages = [(v / 4095.0) * 3.3 for v in raw_vals]

                    if current_label > 0:
                        w.writerow([
                            f"{time.time() - t0:.4f}",
                            f"{voltages[0]:.4f}",
                            f"{voltages[1]:.4f}",
                            f"{voltages[2]:.4f}",
                            current_label
                        ])
                        count += 1
                        counts[current_label] += 1

                        if count - last_print >= 1000:
                            print(f"#{count}  anlik={LABEL_NAMES[current_label]}  "
                                  f"REST={counts[1]}  ELBOW={counts[2]}  "
                                  f"SQUEEZE={counts[3]}  GRIP={counts[4]}")
                            last_print = count

    except Exception as e:
        print(f"HATA: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
        print(f"\nKaydedildi: {FILE_NAME}")
        print(f"REST={counts[1]}  ELBOW={counts[2]}  "
              f"SQUEEZE={counts[3]}  GRIP={counts[4]}")


listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()
record_data()
