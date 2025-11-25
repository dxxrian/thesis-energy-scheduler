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

# KONFIGURATION
EPOCHS = int(os.environ.get('EPOCHS', 100))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 2048))

# Pfade
NFS_DATA_PATH = '/data/preprocessed_retail_data.csv'
LOCAL_DATA_PATH = '/tmp/training_data.csv' # Wir kopieren hierhin
NFS_MODEL_PATH = '/data/retail_model.h5'
LOCAL_MODEL_PATH = '/tmp/retail_model.h5'

print(f"--- Phase 2: Training (Optimized I/O) ---")
script_start_time = time.time()

# GPU Check
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass
else:
    print("⚠ Keine GPU, nutze CPU.")

try:
    if not os.path.exists(NFS_DATA_PATH): raise FileNotFoundError(NFS_DATA_PATH)

    # SCHRITT 1: Daten vom langsamen NFS auf schnelle lokale Disk kopieren
    print("Kopiere Daten von NFS nach lokal (/tmp)...", flush=True)
    shutil.copy(NFS_DATA_PATH, LOCAL_DATA_PATH)

    print("Lade lokale Daten...", flush=True)
    df = pd.read_csv(LOCAL_DATA_PATH)

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

    if hasattr(X_train, "toarray"): X_train = X_train.toarray()
    if hasattr(X_test, "toarray"): X_test = X_test.toarray()

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
    model.fit(X_train, y_train, epochs=EPOCHS, batch_size=BATCH_SIZE, validation_split=0.1, verbose=2)

    # SCHRITT 2: Modell lokal speichern und dann verschieben
    print(f"Speichere Modell lokal...", flush=True)
    model.save(LOCAL_MODEL_PATH, save_format='h5')
    
    print(f"Verschiebe Modell auf NFS...", flush=True)
    shutil.move(LOCAL_MODEL_PATH, NFS_MODEL_PATH)
    
    print("✅ Erfolg.", flush=True)

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    sys.exit(1)

# Cleanup lokal
if os.path.exists(LOCAL_DATA_PATH): os.remove(LOCAL_DATA_PATH)
sys.exit(0)
