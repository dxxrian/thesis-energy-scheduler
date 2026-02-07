#train.py
import os
import sys
import shutil
import pickle
import tensorflow as tf
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer

# Konfiguration (Default: 50 Epochen, Matrix-Größe 4096)
EPOCHS = int(os.environ.get('EPOCHS', 50))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 4096))
LAYER_SIZE = int(os.environ.get('LAYER_SIZE', 4096))
NFS_DIR = '/data'
LOCAL_DIR = '/tmp'
DATA_FILE = 'preprocessed_retail_data.csv'

def main():
    print(f"--- ML TRAINING PHASE ---")
    print(f"Config: {EPOCHS} Epochs | Batch {BATCH_SIZE} | Neurons {LAYER_SIZE}")
    # GPU-Initialisierung
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        print(f"Hardware: GPU gefunden ({gpus[0]})")
        try:
            tf.config.experimental.set_memory_growth(gpus[0], True)
        except:
            pass
    else:
        print("Hardware: Fallback auf CPU")

    # Daten laden
    nfs_path = os.path.join(NFS_DIR, DATA_FILE)
    local_path = os.path.join(LOCAL_DIR, DATA_FILE)
    if not os.path.exists(nfs_path):
        print(f"!!! FEHLER: Daten nicht gefunden: {nfs_path}", file=sys.stderr)
        sys.exit(1)
    print("Kopiere Daten in lokalen Speicher...", flush=True)
    shutil.copy(nfs_path, local_path)
    df = pd.read_csv(local_path)

    # Vorbereitung der Daten
    if 'Quantity' not in df.columns:
        print("Fehler: Spalte 'Quantity' fehlt.", file=sys.stderr)
        sys.exit(1)
    df['PurchasedMultiple'] = (df['Quantity'] > 1).astype(int)
    X = df[['Price', 'Country']]
    y = df['PurchasedMultiple']

    # Transformation: Skalierung für Numerik, One-Hot für Kategorien
    preprocessor = ColumnTransformer(transformers=[
        ('num', StandardScaler(), ['Price']),
        ('cat', OneHotEncoder(handle_unknown='ignore'), ['Country'])
    ])
    X_train, _, y_train, _ = train_test_split(X, y, test_size=0.2)
    X_train = preprocessor.fit_transform(X_train)
    # Sparse Matrix in Dense konvertieren für TensorFlow
    if hasattr(X_train, "toarray"):
        X_train = X_train.toarray()
    input_dim = X_train.shape[1]
    print(f"Input Features: {input_dim}", flush=True)

    # Modell-Architektur definieren
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(input_dim,)),
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(LAYER_SIZE, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(1024, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    # Training
    print("Starte Training...", flush=True)
    model.fit(X_train, y_train, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=2)

    # Artefakte speichern
    print("Speichere Modell und Metadaten auf NFS...", flush=True)
    save_artifact(model, 'retail_model.h5', is_keras=True)
    weights = [w.tolist() for w in model.get_weights()]
    save_artifact(weights, 'retail_model.weights.pkl', is_pickle=True)
    save_artifact(str(input_dim), 'model_shape.txt', is_text=True)
    save_artifact(str(LAYER_SIZE), 'model_config.txt', is_text=True)

    print("ABGESCHLOSSEN.")

def save_artifact(data, filename, is_keras=False, is_pickle=False, is_text=False):
    """Hilfsfunktion für atomares Speichern auf NFS via lokalem Temp-File."""
    local_p = os.path.join(LOCAL_DIR, filename)
    nfs_p = os.path.join(NFS_DIR, filename)
    try:
        if is_keras:
            data.save(local_p, save_format='h5')
        elif is_pickle:
            with open(local_p, 'wb') as f: pickle.dump(data, f)
        elif is_text:
            with open(local_p, 'w') as f: f.write(data)
        shutil.move(local_p, nfs_p)
    except Exception as e:
        print(f"Warnung beim Speichern von {filename}: {e}")

if __name__ == "__main__":
    main()
