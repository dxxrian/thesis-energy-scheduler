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

print("--- Phase 2: Modelltraining gestartet ---", flush=True)
script_start_time = time.time()

# GPU-Verfügbarkeit prüfen
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ TensorFlow GPU gefunden: {gpus[0]}", flush=True)
    try:
        tf.config.experimental.set_memory_growth(gpus[0], True)
    except RuntimeError as e:
        print(e, flush=True)
else:
    print("⚠️ TensorFlow: Keine GPU gefunden, nutze CPU.", flush=True)

try:
    print(f"Lade vorverarbeitete Daten von {DATA_PATH}...", flush=True)
    df = pd.read_csv(DATA_PATH, nrows=50000) # Begrenze die Datenmenge für schnellere Tests
    print(f"Daten geladen. Shape: {df.shape}", flush=True)

    # Zielvariable: Wurde mehr als 1 Artikel gekauft? (Binäre Klassifikation)
    df['PurchasedMultiple'] = (df['Quantity'] > 1).astype(int)

    # Features und Target definieren
    features = ['Price', 'Country']
    target = 'PurchasedMultiple'
    X = df[features]
    y = df[target]

    # Preprocessing für das Modell (Skalierung und One-Hot-Encoding)
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), ['Price']),
            ('cat', OneHotEncoder(handle_unknown='ignore'), ['Country'])
        ])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"Trainingsdaten-Shape: {X_train.shape}, Testdaten-Shape: {X_test.shape}", flush=True)
    X_train_processed = preprocessor.fit_transform(X_train)
    X_test_processed = preprocessor.transform(X_test)
    print("Daten-Transformation abgeschlossen.", flush=True)

    print("Baue das Keras-Modell...", flush=True)
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

    print("Modell-Zusammenfassung:", flush=True)
    model.summary(print_fn=lambda x: print(x, flush=True))

    print("Starte Modelltraining...", flush=True)
    training_start_time = time.time()

    # Passe Epochen und Batch-Größe an, um >15s Laufzeit sicherzustellen
    epochs = 5
    batch_size = 512

    model.fit(X_train_processed, y_train, epochs=epochs, batch_size=batch_size, validation_split=0.1, verbose=2)

    training_duration = time.time() - training_start_time
    print(f"Modelltraining abgeschlossen. Dauer: {training_duration:.2f} Sekunden.", flush=True)

    # Evaluiere und speichere das Modell
    print("Evaluiere Modell auf Testdaten...", flush=True)
    loss, accuracy = model.evaluate(X_test_processed, y_test, verbose=0)
    print(f"Test-Genauigkeit: {accuracy:.4f}", flush=True)

    print(f"Speichere Modell nach {MODEL_PATH}...", flush=True)
    model.save(MODEL_PATH)
    print("Modell erfolgreich gespeichert.", flush=True)

except Exception as e:
    print(f"FATALER FEHLER in train.py: {e}", file=sys.stderr, flush=True)
    exit(1)

total_duration = time.time() - script_start_time
print(f"Gesamtdauer des Skripts: {total_duration:.2f} Sekunden.", flush=True)
print("--- Modelltraining erfolgreich abgeschlossen ---", flush=True)
