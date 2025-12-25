import json
import uuid
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client import models
from qdrant_client.models import PointStruct, VectorParams, Distance
import ollama
from concurrent.futures import ThreadPoolExecutor, as_completed

# === CONFIGURATION ===
QDRANT_URL = "http://localhost:6333"
QDRANT_API_KEY = "4471ec97c9071f536ca9849e3cad46f2"
OLLAMA_MODEL = "nomic-embed-text"
FILE_NAME = "118k-answered.json"
COLLECTION_NAME = f"questions-collection-combined"
EMBEDDING_DIM = 768
CHUNK_FILE = "datasets/" + FILE_NAME 
WORKERS = 3
BATCH_SIZE = 200

if CHUNK_FILE is None:
    raise ValueError("CHUNK_FILE must be set to a valid file path.")

# === Load Data ===
with open(CHUNK_FILE, "r") as f:
    data = json.load(f)

# === Init Clients ===
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
oclient = ollama.Client(host="localhost")

# === Ollama Embedding Function ===
def get_embedding_ollama(text: str):
    response = oclient.embeddings(model=OLLAMA_MODEL, prompt=text)
    return response["embedding"]

# === Process Batch Function ===
def process_batch(batch_data, batch_index):
    batch = []
    for item in tqdm(batch_data, desc=f"Embedding batch {batch_index}", leave=False):
        question_text = item.get("title", "") + "\n" + item.get("question", "")
        embedding = get_embedding_ollama(question_text)
        
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "url": item["url"],
                "content": f"TITLE: {item['title']}\nQUESTION: {item['question']}\nURL: {item['url']}\nANSWER: {item['answer']}",
            }
        )
        batch.append(point)
    
    # Upload batch
    client.upsert(collection_name=COLLECTION_NAME, points=batch)
    return len(batch)

# === Select Failed Batches ===
failed_batch_indices = [138, 140, 141, 142, 143]
batches = [data[i * BATCH_SIZE:(i + 1) * BATCH_SIZE] for i in failed_batch_indices]
total_uploaded = 0

print("🚀 Starting re-upload of failed batches")
with ThreadPoolExecutor(max_workers=WORKERS) as executor:
    future_to_batch = {executor.submit(process_batch, batch, i): i for i, batch in zip(failed_batch_indices, batches)}
    
    for future in tqdm(as_completed(future_to_batch), total=len(batches), desc="Processing failed batches"):
        batch_index = future_to_batch[future]
        try:
            uploaded = future.result()
            total_uploaded += uploaded
            print(f"📤 Batch {batch_index} completed: {uploaded} items. Total: {total_uploaded}")
        except Exception as e:
            print(f"❌ Batch {batch_index} failed again: {str(e)}")

print(f"✅ Re-uploaded {total_uploaded} items from failed batches to Qdrant.")