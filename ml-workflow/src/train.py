import tensorflow as tf
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
import time
import os
import sys
import shutil
import pickle

# --- KONFIGURATION VIA ENV ---
EPOCHS = int(os.environ.get('EPOCHS', 50))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 4096))
# Steuert die Breite der 3 Hidden Layers (Standard: 4096 für GPU Sättigung)
LAYER_SIZE = int(os.environ.get('LAYER_SIZE', 4096)) 

NFS_DATA_PATH = '/data/preprocessed_retail_data.csv'
LOCAL_DATA_PATH = '/tmp/training_data.csv'
NFS_MODEL_PATH = '/data/retail_model.h5'
NFS_WEIGHTS_PKL = '/data/retail_model.weights.pkl'
NFS_SHAPE_PATH = '/data/model_shape.txt'
NFS_CONFIG_PATH = '/data/model_config.txt' # Neu: Speichert Layer-Config

LOCAL_MODEL_PATH = '/tmp/retail_model.h5'
LOCAL_WEIGHTS_PKL = '/tmp/retail_model.weights.pkl'
LOCAL_SHAPE_PATH = '/tmp/model_shape.txt'
LOCAL_CONFIG_PATH = '/tmp/model_config.txt'

print(f"--- Phase 2: Training (Flexible Config) ---")
print(f"Config: {EPOCHS} Epochs | Batch {BATCH_SIZE} | Layer Size {LAYER_SIZE}")

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass
else:
    print("⚠ Keine GPU, nutze CPU.")

try:
    if not os.path.exists(NFS_DATA_PATH): raise FileNotFoundError(NFS_DATA_PATH)

    print("Lade Daten...", flush=True)
    shutil.copy(NFS_DATA_PATH, LOCAL_DATA_PATH)
    df = pd.read_csv(LOCAL_DATA_PATH)
    if 'Quantity' not in df.columns: raise ValueError("Quantity fehlt")
    df['PurchasedMultiple'] = (df['Quantity'] > 1).astype(int)

    X = df[['Price', 'Country']]
    y = df['PurchasedMultiple']

    preprocessor = ColumnTransformer(transformers=[
        ('num', StandardScaler(), ['Price']),
        ('cat', OneHotEncoder(handle_unknown='ignore'), ['Country'])
    ])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    X_train = preprocessor.fit_transform(X_train)
    
    if hasattr(X_train, "toarray"): X_train = X_train.toarray()
    
    input_dim = X_train.shape[1]
    print(f"Input Dimension: {input_dim}", flush=True)

    # --- DYNAMISCHES MODELL ---
    print(f"Baue Modell mit 3x {LAYER_SIZE} Dense Layers...", flush=True)
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(input_dim,)),
        
        # Layer 1
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        # Layer 2
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        # Layer 3
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        # Bottleneck
        tf.keras.layers.Dense(1024, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    print(f"Starte Training...", flush=True)
    model.fit(X_train, y_train, epochs=EPOCHS, batch_size=BATCH_SIZE, validation_split=0.1, verbose=2)

    print(f"Speichere Artefakte...", flush=True)
    
    # 1. H5
    try:
        model.save(LOCAL_MODEL_PATH, save_format='h5')
        shutil.move(LOCAL_MODEL_PATH, NFS_MODEL_PATH)
    except Exception as e:
        print(f"Warnung H5 Save: {e}")

    # 2. Pickle Weights
    weights = [w.tolist() for w in model.get_weights()]
    with open(LOCAL_WEIGHTS_PKL, 'wb') as f:
        pickle.dump(weights, f)
    shutil.move(LOCAL_WEIGHTS_PKL, NFS_WEIGHTS_PKL)

    # 3. Metadaten (Input Dim & Layer Size für Inferenz)
    with open(LOCAL_SHAPE_PATH, 'w') as f:
        f.write(str(input_dim))
    shutil.move(LOCAL_SHAPE_PATH, NFS_SHAPE_PATH)
    
    with open(LOCAL_CONFIG_PATH, 'w') as f:
        f.write(str(LAYER_SIZE))
    shutil.move(LOCAL_CONFIG_PATH, NFS_CONFIG_PATH)

    print("✅ Erfolg: Training beendet.", flush=True)

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    sys.exit(1)
