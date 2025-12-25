import json
import uuid
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, FilterSelector, Filter, MatchValue, FieldCondition
import ollama
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import os

# === CONFIG_IGNORE ===
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")  # 2025-04-08
QDRANT_URL = os.environ.get("HOST", "http://localhost") + ":6333"
print(f"Qdrant URL: {QDRANT_URL}")
QDRANT_API_KEY = "4471ec97c9071f536ca9849e3cad46f2"
OLLAMA_MODEL = "nomic-embed-text"
FILE_NAME = f"answered_ti_e2e_{CURRENT_DATE}.json"
COLLECTION_NAME = "questions-collection-combined"
EMBEDDING_DIM = 768
CHUNK_FILE = "/datasets/" + FILE_NAME 
WORKERS = 3
BATCH_SIZE = 200

if CHUNK_FILE is None:
    raise ValueError("CHUNK_FILE must be set to a valid file path.")

# === Load Data ===
with open(CHUNK_FILE, "r") as f:
    data = json.load(f)

# === Init Clients ===
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
OLLAMA_URL = os.environ.get("HOST", "http://localhost") + ":11434"
oclient = ollama.Client(host=OLLAMA_URL)

# === Delete existing metadata_date points in case re-run ===
client.delete(
    collection_name=COLLECTION_NAME,
    points_selector=FilterSelector(
        filter=Filter(
            must=[
                FieldCondition(
                    key="metadata_date",
                    match=MatchValue(value=CURRENT_DATE)
                )
            ]
        )
    )
)

# === Ollama Embedding Function ===
def get_embedding_ollama(text: str):
    response = oclient.embeddings(model=OLLAMA_MODEL, prompt=text)
    return response["embedding"]

# === Process Batch Function ===
def process_batch(batch_data):
    batch = []
    for item in tqdm(batch_data, desc="Embedding batch", leave=False):
        question_text = item.get("title", "") + "\n" + item.get("question", "")
        embedding = get_embedding_ollama(question_text)
        
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "url": item["url"],
                "content": f"TITLE: {item['title']}\nQUESTION: {item['question']}\nURL: {item['url']}\nANSWER: {item['answer']}",
                "metadata_date": CURRENT_DATE  # Added metadata for tracking
            }
        )
        batch.append(point)
    
    # Upload batch
    client.upsert(collection_name=COLLECTION_NAME, points=batch)
    return len(batch)

# === Parallel Processing ===
batches = [data[i:i + BATCH_SIZE] for i in range(0, len(data), BATCH_SIZE)]
total_uploaded = 0

print(f"🚀 Starting upload on {CURRENT_DATE}")
with ThreadPoolExecutor(max_workers=WORKERS) as executor:
    future_to_batch = {executor.submit(process_batch, batch): i for i, batch in enumerate(batches)}
    
    for future in tqdm(as_completed(future_to_batch), total=len(batches), desc="Processing batches"):
        batch_index = future_to_batch[future]
        try:
            uploaded = future.result()
            total_uploaded += uploaded
            print(f"📤 Batch {batch_index} completed: {uploaded} items. Total: {total_uploaded}")
        except Exception as e:
            print(f"❌ Batch {batch_index} failed: {str(e)}")

print(f"✅ All {total_uploaded} items embedded and uploaded to Qdrant on {CURRENT_DATE}.")