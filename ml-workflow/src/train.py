# ml-workflow/src/train.py
import tensorflow as tf
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
import time
import os
import sys
import shutil

# KONFIGURATION: Über Umgebungsvariablen steuerbar
# Standard (Thesis): 100 Epochen
EPOCHS = int(os.environ.get('EPOCHS', 100))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 2048))

DATA_PATH = '/data/preprocessed_retail_data.csv'
FINAL_MODEL_PATH = '/data/retail_model.h5'
LOCAL_MODEL_PATH = '/tmp/retail_model.h5'

os.makedirs('/data', exist_ok=True)
sys.stdout.reconfigure(line_buffering=True)

print(f"--- Phase 2: Training (RAM-Safe) ---")
print(f"Konfiguration: EPOCHS={EPOCHS}, BATCH_SIZE={BATCH_SIZE}")
script_start_time = time.time()

# GPU Setup
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass
else:
    print("⚠ Keine GPU, nutze CPU.")

try:
    if not os.path.exists(DATA_PATH): raise FileNotFoundError(DATA_PATH)

    print("Lade Daten...", flush=True)
    df = pd.read_csv(DATA_PATH)
    # KEINE Vervielfachung -> RAM sicher
    print(f"Datensatzgröße: {df.shape} (RAM sicher)")

    if 'Quantity' not in df.columns: raise ValueError("Quantity fehlt")
    df['PurchasedMultiple'] = (df['Quantity'] > 1).astype(int)

    X = df[['Price', 'Country']]
    y = df['PurchasedMultiple']

    print("Preprocessing...", flush=True)
    preprocessor = ColumnTransformer(transformers=[
        ('num', StandardScaler(), ['Price']),
        ('cat', OneHotEncoder(handle_unknown='ignore'), ['Country'])
    ])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    X_train = preprocessor.fit_transform(X_train)
    X_test = preprocessor.transform(X_test)

    # Sparse zu Dense (jetzt sicher, da Daten klein sind)
    if hasattr(X_train, "toarray"): X_train = X_train.toarray()
    if hasattr(X_test, "toarray"): X_test = X_test.toarray()

    print(f"Daten bereit.", flush=True)

    # Modell definieren
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(X_train.shape[1],)),
        tf.keras.layers.Dense(512, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(256, activation='relu'),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    print(f"Starte Training für {EPOCHS} Epochen...", flush=True)
    training_start = time.time()
    
    model.fit(X_train, y_train, 
              epochs=EPOCHS, 
              batch_size=BATCH_SIZE, 
              validation_split=0.1, 
              verbose=2) 

    duration = time.time() - training_start
    print(f"Training beendet. Dauer: {duration:.2f}s", flush=True)

    # Workaround für NFS-Schreibprobleme
    print(f"Speichere Modell lokal...", flush=True)
    model.save(LOCAL_MODEL_PATH, save_format='h5')
    print(f"Verschiebe auf NFS...", flush=True)
    shutil.move(LOCAL_MODEL_PATH, FINAL_MODEL_PATH)
    print("✅ Erfolg.", flush=True)

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
