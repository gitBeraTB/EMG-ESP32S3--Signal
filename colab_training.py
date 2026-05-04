import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns

# ---------------------------------------------------------
# GOOGLE COLAB USAGE GUIDE
# 1. Open https://colab.research.google.com/
# 2. Create a new notebook.
# 3. On the left sidebar click "Files" and upload the CSV file
#    (the file should contain three columns: "Zaman (sn)", "Voltaj (V)", "Label").
# 4. Run the cell below to install the conversion library:
#    !pip install micromlgen
# 5. Run the whole script (copy‑paste all cells) to train the model and download model.h.
# ---------------------------------------------------------

print("1. Loading data...")
try:
    df = pd.read_csv('emg_kayit_ch1.csv')  # adjust filename if needed
    # Remove any accidental whitespace from column names
    df.columns = df.columns.str.strip()
    print("Data shape:", df.shape)
    print("Columns:", df.columns.tolist())
except FileNotFoundError:
    print("ERROR: 'emg_kayit_ch1.csv' not found. Upload it to Colab first.")
    raise SystemExit

# Expected column names (allow slight variations)
expected_cols = {'Zaman (sn)', 'Voltaj (V)', 'Label'}
if not expected_cols.issubset(set(df.columns)):
    print("WARNING: Expected columns not found. Available columns:", df.columns)
    # Try to guess common names
    if 'Timestamp' in df.columns:
        df.rename(columns={'Timestamp': 'Zaman (sn)'}, inplace=True)
    if 'EMG_Value' in df.columns:
        df.rename(columns={'EMG_Value': 'Voltaj (V)'}, inplace=True)
    if 'Label' not in df.columns:
        print("ERROR: No 'Label' column present. Cannot continue.")
        raise SystemExit

print("\nLabel distribution (1=Rest, 2=Elbow, 3=Biceps):")
print(df['Label'].value_counts())

# ---------------------------------------------------------
print("\n2. Feature extraction (sliding window)...")
WINDOW_SIZE = 50   # 50 samples ≈ 0.025 s at 2000 Hz
STEP_SIZE   = 25   # 50 % overlap

features = []
labels   = []

# Build windows per class
for label in df['Label'].unique():
    # Keep only the voltage column for this label
    signal = df[df['Label'] == label]['Voltaj (V)'].values
    for start in range(0, len(signal) - WINDOW_SIZE + 1, STEP_SIZE):
        window = signal[start:start + WINDOW_SIZE]
        # Time‑domain features (same as before)
        mean_val = np.mean(window)
        std_val  = np.std(window)
        var_val  = np.var(window)
        rms_val  = np.sqrt(np.mean(window ** 2))
        min_val  = np.min(window)
        max_val  = np.max(window)
        features.append([mean_val, std_val, var_val, rms_val, min_val, max_val])
        labels.append(label)

X = np.array(features)
y = np.array(labels)
print("Feature matrix shape:", X.shape)

# ---------------------------------------------------------
print("\n3. Train Random Forest (max_depth=8)...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y)

clf = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
clf.fit(X_train, y_train)

print("Training completed.")
print(f"Test accuracy: {clf.score(X_test, y_test) * 100:.2f}%")

# ---------------------------------------------------------
print("\n4. Evaluation report")
y_pred = clf.predict(X_test)
# Human‑readable class names
class_names = {1: 'REST', 2: 'ELBOW', 3: 'BICEPS'}
unique_labels = np.unique(y)
target_names = [class_names.get(l, str(l)) for l in unique_labels]
print(classification_report(y_test, y_pred, target_names=target_names))

cm = confusion_matrix(y_test, y_pred)
plt.figure(figsize=(8, 6))
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
    from google.colab import files
    c_code = port(clf, quantize=False)  # disable quantization to avoid ESP32 crashes
    model_file = 'model.h'
    with open(model_file, 'w') as f:
        f.write(c_code)
    print(f"Model header saved as '{model_file}'.")
    files.download(model_file)
    print("Download started – place 'model.h' into the PlatformIO src folder next to main.cpp.")
except ImportError:
    print("ERROR: micromlgen not installed. Run '!pip install micromlgen' first.")
except Exception as e:
    print("ERROR while exporting model:", e)
