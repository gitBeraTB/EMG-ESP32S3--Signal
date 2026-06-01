import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns

# ---------------------------------------------------------
# GOOGLE COLAB USAGE GUIDE
# 1. Open https://colab.research.google.com/  and create a new notebook.
# 2. !pip install micromlgen
# 3. Upload 'emg_kayit.csv' (produced by plotting.py) on the "Files" panel.
# 4. Run this whole script -> trains a BINARY (REST/SQUEEZE) model and
#    downloads model.h.
#
# IMPORTANT — this model is REUSED per channel on the ESP32:
#   pred_ch1 = clf.predict(&features[0])   // CH1 (cene/jaw)
#   pred_ch2 = clf.predict(&features[6])   // CH2 (bilek/wrist)
# So it must be a single-channel, 6-feature, 2-class detector with
# output 0 = REST, 1 = SQUEEZE to match the firmware.
#
# plotting.py CSV format:  Zaman (sn), CH1 (V), CH2 (V), Label
#   Label 1 = CH1 REST   2 = CH1 SQUEEZE
#   Label 3 = CH2 REST   4 = CH2 SQUEEZE
# CH1 and CH2 windows are POOLED into one dataset so a single model fits
# both muscles.
# ---------------------------------------------------------

# =========================================================
#  CONFIG
# =========================================================
CSV_FILE     = 'emg_kayit.csv'
LABEL_COLUMN = 'Label'

# plotting.py label value -> (voltage column, binary class 0=REST / 1=SQUEEZE)
LABEL_MAP = {
    1: ('CH1 (V)', 0),   # CH1 REST
    2: ('CH1 (V)', 1),   # CH1 SQUEEZE
    3: ('CH2 (V)', 0),   # CH2 REST
    4: ('CH2 (V)', 1),   # CH2 SQUEEZE
}

# plotting.py already writes VOLTS, so no ADC conversion needed here.
# (Firmware features are also computed in volts: adc * 3.3 / 4095.)
ADC_TO_VOLT = False
ADC_MAX     = 4095.0
VREF        = 3.3

WINDOW_SIZE = 50   # 50 samples ~ 0.025 s at 2000 Hz  (must match firmware)
STEP_SIZE   = 25   # 50 % overlap                      (must match firmware)

# =========================================================
print("1. Loading data...")
try:
    df = pd.read_csv(CSV_FILE)
    df.columns = df.columns.str.strip()
    print("Data shape:", df.shape)
    print("Columns:", df.columns.tolist())
except FileNotFoundError:
    print(f"ERROR: '{CSV_FILE}' not found. Upload it to Colab first.")
    raise SystemExit

if LABEL_COLUMN not in df.columns:
    print(f"ERROR: label column '{LABEL_COLUMN}' not present. Cannot continue.")
    raise SystemExit

needed_cols = {col for col, _ in LABEL_MAP.values()}
missing = [c for c in needed_cols if c not in df.columns]
if missing:
    print(f"ERROR: voltage column(s) not found: {missing}")
    print("Available columns:", df.columns.tolist())
    raise SystemExit

print("\nRaw label distribution (1=CH1R 2=CH1S 3=CH2R 4=CH2S):")
print(df[LABEL_COLUMN].value_counts())

# ---------------------------------------------------------
print("\n2. Feature extraction (sliding window, CH1+CH2 pooled)...")


def extract_features(window):
    """6 time-domain features in the EXACT order the firmware uses:
       mean, std, var, rms, min, max."""
    return [
        np.mean(window),
        np.std(window),
        np.var(window),
        np.sqrt(np.mean(window ** 2)),
        np.min(window),
        np.max(window),
    ]


features = []
labels   = []

for raw_label, (volt_col, bin_class) in LABEL_MAP.items():
    # Only the rows recorded under this label, from the relevant channel.
    signal = df[df[LABEL_COLUMN] == raw_label][volt_col].astype(float).values
    if ADC_TO_VOLT:
        signal = signal * VREF / ADC_MAX
    for start in range(0, len(signal) - WINDOW_SIZE + 1, STEP_SIZE):
        features.append(extract_features(signal[start:start + WINDOW_SIZE]))
        labels.append(bin_class)

X = np.array(features)
y = np.array(labels)
print("Feature matrix shape:", X.shape)
print("Window class distribution (0=REST, 1=SQUEEZE):",
      dict(zip(*np.unique(y, return_counts=True))))

if len(X) == 0 or len(np.unique(y)) < 2:
    print("ERROR: need both REST and SQUEEZE windows to train. Check labels.")
    raise SystemExit

# ---------------------------------------------------------
print("\n3. Train Random Forest (binary, max_depth=8)...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y)

clf = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
clf.fit(X_train, y_train)

print("Training completed.")
print(f"Test accuracy: {clf.score(X_test, y_test) * 100:.2f}%")

# ---------------------------------------------------------
print("\n4. Evaluation report")
y_pred = clf.predict(X_test)
target_names = ['REST', 'SQUEEZE']
print(classification_report(y_test, y_pred, target_names=target_names))

cm = confusion_matrix(y_test, y_pred)
plt.figure(figsize=(6, 5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
            xticklabels=target_names, yticklabels=target_names)
plt.ylabel('True label')
plt.xlabel('Predicted label')
plt.title('Confusion matrix')
plt.show()

# ---------------------------------------------------------
print("\n5. Export model to C++ header (quantization disabled)")
try:
    from micromlgen import port
    c_code = port(clf, quantize=False)  # disable quantization to avoid ESP32 crashes
    with open('model.h', 'w') as f:
        f.write(c_code)
    print("Model header saved as 'model.h'.")
    try:
        from google.colab import files
        files.download('model.h')
        print("Download started - place 'model.h' next to main.cpp in the PlatformIO src folder.")
    except ImportError:
        print("(Not on Colab) 'model.h' written to the working directory.")
except ImportError:
    print("ERROR: micromlgen not installed. Run '!pip install micromlgen' first.")
except Exception as e:
    print("ERROR while exporting model:", e)
