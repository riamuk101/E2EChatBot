import sqlite3
import os
from qdrant_client import QdrantClient
import uuid
import requests

DB_PATH = "./open-webui/webui.db"
FUNCTION_PATH = "./n8n_function.py"
QDRANT_URL = "http://localhost:6333"
API_KEY = os.getenv("QDRANT_API_KEY", "4471ec97c9071f536ca9849e3cad46f2")
COLLECTION_NAME = "questions-collection-combined"
POINT_THRESHOLD = 100000
SNAPSHOT_NAME = "questions-collection-combined.snapshot"
SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "snapshots", SNAPSHOT_NAME
)

client = QdrantClient(url=QDRANT_URL, api_key=API_KEY)

def check_qdrant():
    try:
        info = client.get_collection(COLLECTION_NAME)
        print(f"[Qdrant] Found {info.points_count} points in '{COLLECTION_NAME}' collection.")
        if info.points_count < POINT_THRESHOLD:
            print(f"[Warning] Qdrant collection has less than {POINT_THRESHOLD} points.")
            return False
        return True
    except Exception as e:
        print(f"[Error] Failed to get Qdrant collection info: {e}")
        return False

def load_function_content():
    with open(FUNCTION_PATH, "r") as f:
        return f.read()
    
def restore_snapshot():
    try:
        # Verify snapshot file exists
        if not os.path.exists(SNAPSHOT_PATH):
            print(f"Error: Snapshot file '{SNAPSHOT_PATH}' does not exist.")
            return

        print(
            f"Snapshot file found: {SNAPSHOT_PATH}, size: {os.path.getsize(SNAPSHOT_PATH)} bytes")

        # Verify Qdrant server is reachable
        ping_response = requests.get(f"{QDRANT_URL}/")
        if ping_response.status_code != 200:
            print(
                f"Error: Qdrant server not reachable. Status: {ping_response.status_code}, Response: {ping_response.text}")
            return

        print("Qdrant server is reachable.")

        # Prepare the upload request
        upload_url = f"{QDRANT_URL}/collections/{COLLECTION_NAME}/snapshots/upload?priority=snapshot"
        headers = {"api-key": API_KEY}
        files = {"snapshot": (SNAPSHOT_NAME, open(SNAPSHOT_PATH, "rb"))}

        print(
            f"Uploading snapshot '{SNAPSHOT_NAME}' to create collection '{COLLECTION_NAME}'")
        print(f"Request URL: {upload_url}")

        # Send the upload request
        response = requests.post(upload_url, headers=headers, files=files)

        # Close the file
        files["snapshot"][1].close()

        # Check response
        if response.status_code == 200:
            print(
                f"Snapshot '{SNAPSHOT_NAME}' uploaded successfully. Collection '{COLLECTION_NAME}' created/restored. Double-check the collection in Qdrant.")
            try:
                print(f"Response JSON: {response.json()}")
            except ValueError:
                print("Response is not valid JSON.")
        else:
            print(
                f"Error uploading snapshot: Status {response.status_code}, Response: {response.text}")
            try:
                print(f"Response JSON: {response.json()}")
            except ValueError:
                print("Response is not valid JSON.")

        # Verify the collection exists
        client = QdrantClient(url=QDRANT_URL, api_key=API_KEY)
        collection = client.get_collections(COLLECTION_NAME)
        if collection:
            print(f"Collection '{COLLECTION_NAME}' exists after upload. Points count: {collection.points_count}")
        else:
            print(f"Collection '{COLLECTION_NAME}' does not exist after upload. Please check the Qdrant server.")
    except requests.exceptions.ConnectionError as ce:
        print(
            f"Connection error: Could not connect to Qdrant server at {QDRANT_URL}. Details: {ce}")
    except requests.exceptions.HTTPError as he:
        print(f"HTTP error occurred: {he}")
    except requests.exceptions.RequestException as re:
        print(f"Request error occurred: {re}")
    except FileNotFoundError as fnf:
        print(
            f"File error: Snapshot file '{SNAPSHOT_PATH}' not found. Details: {fnf}")
    except Exception as e:
        print(f"Unexpected error uploading snapshot: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

def install_missing_n8n_functions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM user WHERE id NOT IN (SELECT DISTINCT user_id FROM function WHERE name = 'n8n')")
    missing_users = [row[0] for row in cursor.fetchall()]
    print(f"[Users] Found {len(missing_users)} users missing 'n8n' function.")

    if not missing_users:
        conn.close()
        return

    confirm = input("Do you want to install the function for these users? (yes/no): ").strip().lower()
    if confirm not in ["yes", "y"]:
        print("Skipping function installation.")
        conn.close()
        return

    function_content = load_function_content()

    insert_sql = """
    INSERT INTO "function" (
        "id", "user_id", "name", "type", "content", "meta", 
        "created_at", "updated_at", "valves", "is_active", "is_global"
    ) VALUES (
        ?, ?, 'n8n', 'pipe', 
        ?, 
        '{"description": "n8n", "manifest": {}}',
        strftime('%s', 'now'), strftime('%s', 'now'), 
        'null', 1, 0
    );
    """

    for user_id in missing_users:
        generated_id = f"n8n-{uuid.uuid4().hex}"
        print(f"[Users] Installing function for user: {user_id} as function_id={generated_id}")
        cursor.execute(insert_sql, (generated_id, user_id, function_content))

    conn.commit()
    conn.close()
    print("[Users] All missing functions installed.")

def main():
    print("=== Auto Fix Utility ===")
    print("This script checks Qdrant point count and missing n8n functions for users.")

    print("\n--- Checking Qdrant ---")
    qdrant_ok = check_qdrant()
    if not qdrant_ok:
        print("[Action Required] Qdrant point count is below threshold.")
        # Ask user if they want to restore from snapshot
        restore = input("Do you want to restore from snapshot? (yes/no): ").strip().lower()
        if restore in ["yes", "y"]:
            restore_snapshot()
        else:
            print("Skipping snapshot restoration.")
    print("\n--- Checking Users ---")
    install_missing_n8n_functions()

    print("\n[Done] Auto-fix completed.")

if __name__ == "__main__":
    main()
