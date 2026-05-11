# ==============================================================
#  3-KANAL EMG — GOOGLE COLAB EGITIM SCRIPTI
# ==============================================================
# KULLANIM:
#   1. Google Colab'da yeni notebook ac.
#   2. Sol menuden "Files" -> emg_3ch_training_data.csv yukle.
#   3. Ilk hucreye su komutu yaz ve calistir:
#        !pip install micromlgen
#   4. Sonraki hucreye bu scriptin tamamini yapistir ve calistir.
#   5. model.h otomatik indirilecek — PlatformIO src/ altina koy.
# ==============================================================

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns

# ---------------------------------------------------------
# 1. VERI YUKLEME
# ---------------------------------------------------------
print("=" * 60)
print("1. Veri yukleniyor...")
CSV_FILE = 'emg_3ch_training_data.csv'

try:
    df = pd.read_csv(CSV_FILE)
    df.columns = df.columns.str.strip()
    print(f"   Boyut : {df.shape}")
    print(f"   Sutunlar: {df.columns.tolist()}")
except FileNotFoundError:
    print(f"HATA: '{CSV_FILE}' bulunamadi. Colab'a yukleyin.")
    raise SystemExit

# Sutun isimleri kontrolu
required_cols = {'CH1', 'CH2', 'CH3', 'Label'}
if not required_cols.issubset(set(df.columns)):
    print(f"HATA: Beklenen sutunlar: {required_cols}")
    print(f"       Mevcut sutunlar : {set(df.columns)}")
    raise SystemExit

# Label=0 varsa (gecis verileri) at
df = df[df['Label'] > 0].reset_index(drop=True)

print("\nLabel dagilimi:")
CLASS_NAMES = {1: 'REST', 2: 'ELBOW', 3: 'SQUEEZE', 4: 'POWER_GRIP'}
for lbl in sorted(df['Label'].unique()):
    n = (df['Label'] == lbl).sum()
    print(f"   {lbl} ({CLASS_NAMES.get(lbl, '?')}) : {n} ornek")

# ---------------------------------------------------------
# 2. FEATURE EXTRACTION — 3 Kanal x 6 Feature = 18
# ---------------------------------------------------------
print("\n" + "=" * 60)
print("2. Feature extraction (sliding window)...")

WINDOW_SIZE = 50    # 50 sample ≈ 25 ms @ 2000 Hz
STEP_SIZE   = 25    # %50 overlap
CHANNELS    = ['CH1', 'CH2', 'CH3']

features_list = []
labels_list   = []

for label in sorted(df['Label'].unique()):
    subset = df[df['Label'] == label]
    ch_signals = {ch: subset[ch].values for ch in CHANNELS}
    n_samples  = len(subset)

    for start in range(0, n_samples - WINDOW_SIZE + 1, STEP_SIZE):
        row_features = []
        for ch in CHANNELS:
            window = ch_signals[ch][start:start + WINDOW_SIZE]

            mean_val = np.mean(window)
            std_val  = np.std(window)
            var_val  = np.var(window)
            rms_val  = np.sqrt(np.mean(window ** 2))
            min_val  = np.min(window)
            max_val  = np.max(window)

            # Siralama: mean, std, var, rms, min, max
            # ESP32 firmware ile AYNI sira!
            row_features.extend([mean_val, std_val, var_val,
                                 rms_val, min_val, max_val])

        features_list.append(row_features)
        labels_list.append(label)

X = np.array(features_list)
y = np.array(labels_list)

# Feature isimleri
feature_names = []
for ch in CHANNELS:
    for feat in ['mean', 'std', 'var', 'rms', 'min', 'max']:
        feature_names.append(f"{ch}_{feat}")

print(f"   Feature matrisi: {X.shape}  (ornek x 18 feature)")
print(f"   Labels         : {y.shape}")

# ---------------------------------------------------------
# 3. EGITIM
# ---------------------------------------------------------
print("\n" + "=" * 60)
print("3. Random Forest egitiliyor...")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

clf = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,       # 4 sinif icin biraz daha derin
    random_state=42,
    n_jobs=-1
)
clf.fit(X_train, y_train)

train_acc = clf.score(X_train, y_train) * 100
test_acc  = clf.score(X_test, y_test) * 100
print(f"   Train accuracy : {train_acc:.2f}%")
print(f"   Test accuracy  : {test_acc:.2f}%")

# ---------------------------------------------------------
# 4. DEGERLENDIRME
# ---------------------------------------------------------
print("\n" + "=" * 60)
print("4. Siniflandirma raporu:")
y_pred = clf.predict(X_test)

unique_labels = sorted(np.unique(y))
target_names  = [CLASS_NAMES.get(l, str(l)) for l in unique_labels]

print(classification_report(y_test, y_pred, target_names=target_names))

# Confusion Matrix
cm = confusion_matrix(y_test, y_pred)
plt.figure(figsize=(8, 6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
            xticklabels=target_names, yticklabels=target_names)
plt.ylabel('Gercek')
plt.xlabel('Tahmin')
plt.title('Confusion Matrix — 3 Kanal x 4 Sinif')
plt.tight_layout()
plt.show()

# Feature Importance
importances = clf.feature_importances_
sorted_idx  = np.argsort(importances)[::-1]

plt.figure(figsize=(10, 5))
plt.bar(range(len(importances)), importances[sorted_idx], color='#3b82f6')
plt.xticks(range(len(importances)),
           [feature_names[i] for i in sorted_idx], rotation=45, ha='right')
plt.title('Feature Importance')
plt.tight_layout()
plt.show()

print("\nEn onemli 5 feature:")
for i in range(min(5, len(importances))):
    idx = sorted_idx[i]
    print(f"   {feature_names[idx]:>12s} : {importances[idx]:.4f}")

# ---------------------------------------------------------
# 5. MODEL EXPORT — model.h
# ---------------------------------------------------------
print("\n" + "=" * 60)
print("5. model.h olarak export ediliyor...")

try:
    from micromlgen import port
    c_code = port(clf, quantize=False)
    model_file = 'model.h'
    with open(model_file, 'w') as f:
        f.write(c_code)
    print(f"   '{model_file}' kaydedildi.")

    # Colab ortamindaysa otomatik indir
    try:
        from google.colab import files
        files.download(model_file)
        print("   Indirme baslatildi — model.h'yi PlatformIO src/ altina koyun.")
    except ImportError:
        print("   (Colab degil — dosya yerel olarak kaydedildi)")

except ImportError:
    print("   HATA: micromlgen kurulu degil!")
    print("   Cozum: !pip install micromlgen")
except Exception as e:
    print(f"   HATA: {e}")

print("\n" + "=" * 60)
print("TAMAMLANDI!")
print("Sonraki adim: model.h'yi src/ altina koyup")
print("main.cpp'de MODE_INFERENCE aktif edip flash'layin.")
print("=" * 60)
