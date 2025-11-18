# ml-workflow/scripts/train.py
import tensorflow as tf
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
import time
import os
import sys

DATA_PATH = '/data/preprocessed_retail_data.csv'
MODEL_PATH = '/data/retail_model.keras'
os.makedirs('/data', exist_ok=True)

# Pufferung deaktivieren für sofortige Logs
sys.stdout.reconfigure(line_buffering=True)

print("--- Phase 2: Modelltraining gestartet ---")
script_start_time = time.time()

# GPU-Verfügbarkeit prüfen
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ TensorFlow GPU gefunden: {gpus[0]}")
    try:
        tf.config.experimental.set_memory_growth(gpus[0], True)
    except RuntimeError as e:
        print(e)
else:
    print("⚠ TensorFlow: Keine GPU gefunden, nutze CPU.")

try:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Daten nicht gefunden unter {DATA_PATH}")

    print(f"Lade vorverarbeitete Daten von {DATA_PATH}...")
    # Begrenze Datenmenge für Tests, entferne nrows für Produktion
    df = pd.read_csv(DATA_PATH, nrows=50000) 
    print(f"Daten geladen. Shape: {df.shape}")

    # Zielvariable: Wurde mehr als 1 Artikel gekauft?
    if 'Quantity' not in df.columns:
        raise ValueError("Spalte 'Quantity' fehlt im Datensatz.")
        
    df['PurchasedMultiple'] = (df['Quantity'] > 1).astype(int)

    features = ['Price', 'Country']
    target = 'PurchasedMultiple'
    X = df[features]
    y = df[target]

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), ['Price']),
            ('cat', OneHotEncoder(handle_unknown='ignore'), ['Country'])
        ])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"Trainingsdaten: {X_train.shape}, Testdaten: {X_test.shape}")
    
    X_train_processed = preprocessor.fit_transform(X_train)
    X_test_processed = preprocessor.transform(X_test)

    if hasattr(X_train_processed, "toarray"):
        print("Konvertiere Sparse Matrix zu Dense Array (Training)...")
        X_train_processed = X_train_processed.toarray()
    if hasattr(X_test_processed, "toarray"):
        print("Konvertiere Sparse Matrix zu Dense Array (Test)...")
        X_test_processed = X_test_processed.toarray()

    print("Daten-Transformation abgeschlossen.")

    print("Baue das Keras-Modell...")
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(X_train_processed.shape[1],)),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(64, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])

    model.compile(optimizer='adam',
                  loss='binary_crossentropy',
                  metrics=['accuracy'])

    model.summary(print_fn=print)

    print("Starte Modelltraining...")
    training_start_time = time.time()

    model.fit(X_train_processed, y_train, 
              epochs=5, 
              batch_size=512, 
              validation_split=0.1, 
              verbose=2)

    training_duration = time.time() - training_start_time
    print(f"Modelltraining abgeschlossen. Dauer: {training_duration:.2f} Sekunden.")

    print("Evaluiere Modell auf Testdaten...")
    loss, accuracy = model.evaluate(X_test_processed, y_test, verbose=0)
    print(f"Test-Genauigkeit: {accuracy:.4f}")

    print(f"Speichere Modell nach {MODEL_PATH}...")
    model.save(MODEL_PATH)
    print("Modell erfolgreich gespeichert.")

except Exception as e:
    # Schreibe Fehler explizit nach stderr
    print(f"FATALER FEHLER in train.py: {e}", file=sys.stderr)
    sys.exit(1)

total_duration = time.time() - script_start_time
print(f"Gesamtdauer des Skripts: {total_duration:.2f} Sekunden.")
print("--- Modelltraining erfolgreich abgeschlossen ---")
