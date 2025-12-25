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

# === Create Collection with Optimized Config ===
if client.collection_exists(collection_name=COLLECTION_NAME):
    print(f"📦 Collection {COLLECTION_NAME} already exists, deleting")
    client.delete_collection(collection_name=COLLECTION_NAME)

print(f"🗃️ Creating collection: {COLLECTION_NAME} with optimized config")
client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=EMBEDDING_DIM,
        distance=Distance.COSINE,
        on_disk=True  # Store vectors on disk immediately
    ),
    hnsw_config=models.HnswConfigDiff(
        m=0
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
            }
        )
        batch.append(point)
    
    # Upload batch
    client.upsert(collection_name=COLLECTION_NAME, points=batch)
    return len(batch)

# === Parallel Processing ===
batches = [data[i:i + BATCH_SIZE] for i in range(0, len(data), BATCH_SIZE)]
total_uploaded = 0

print("🚀 Starting bulk upload with optimized memory configuration")
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

# === Post-Upload Optimization ===
print("🛠️ Re-enabling HNSW indexing for search optimization")
client.update_collection(
    collection_name=COLLECTION_NAME,
    hnsw_config=models.HnswConfigDiff(
        m=16  # Re-enable HNSW with production value
    )
)

# Optional: Enable scalar quantization for memory efficiency
print("🔧 Enabling scalar quantization")
client.update_collection(
    collection_name=COLLECTION_NAME,
    quantization_config=models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8,
            always_ram=True
        )
    )
)

print(f"✅ All {total_uploaded} items embedded and uploaded to Qdrant.")
print("Waiting for indexing to complete - monitor Qdrant logs for completion.")