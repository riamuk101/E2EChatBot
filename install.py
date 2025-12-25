# install.py
import subprocess
import sqlite3
import os
import time
import sys
import aiohttp
import asyncio
from qdrant_client import QdrantClient
from qdrant_client.http import models
import requests
import platform
import json

# Paths
DB_PATH = "./open-webui/webui.db"
SQL_SCRIPT_PATH = "./import_function.sql"
FUNCTION_PATH = "./n8n_function.py"
QDRANT_URL = "http://localhost:6333"
API_KEY = os.getenv("QDRANT_API_KEY", "4471ec97c9071f536ca9849e3cad46f2")
COLLECTION_NAME = "questions-collection-combined"
SNAPSHOT_NAME = "questions-collection-combined.snapshot"
SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "snapshots", SNAPSHOT_NAME
)

client = QdrantClient(url=QDRANT_URL, api_key=API_KEY)

def ensure_host_gateway_enabled():
    # Only run on Linux
    if platform.system() != "Linux":
        print("Skipping host-gateway setup: not on Linux.")
        return

    daemon_json_path = "/etc/docker/daemon.json"
    print(f"Checking {daemon_json_path}...")

    # Make sure the file exists
    if not os.path.exists(daemon_json_path):
        print(f"{daemon_json_path} does not exist. Creating it...")
        config = {}
    else:
        # Load existing JSON content
        try:
            with open(daemon_json_path, "r") as f:
                config = json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: {daemon_json_path} is invalid JSON. Overwriting it.")
            config = {}

    # Insert 'features': {'host-gateway': true}
    if "features" not in config:
        config["features"] = {}
    if config["features"].get("host-gateway") != True:
        config["features"]["host-gateway"] = True
        print("Added 'host-gateway': true to features.")
    else:
        print("'host-gateway' is already enabled.")

    # Save the modified JSON
    with open(daemon_json_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Saved {daemon_json_path}.")

    # Restart Docker service
    print("Restarting Docker service...")
    try:
        subprocess.run(["sudo", "systemctl", "restart", "docker"], check=True)
        print("Docker service restarted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error restarting Docker: {e}")
        raise

def start_docker():
    print("Starting Docker Compose...")
    subprocess.run(["docker-compose", "up", "-d"], check=True)
    print("Docker Compose started. Waiting for database to be ready...")

    # Wait for the database file to appear
    timeout = 180  # seconds
    start_time = time.time()
    while not os.path.exists(DB_PATH):
        if time.time() - start_time > timeout:
            raise Exception("Timeout waiting for webui.db to be created.")
        time.sleep(5)
    print("Database found.")

    # wait for the open-webui to be ready by fetch the url and not return code 500
    timeout = 60  # seconds
    start_time = time.time()
    while True:
        try:
            async def check_webui():
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://localhost:3000") as response:
                        if response.status == 200:
                            return True
                        else:
                            return False

            if asyncio.run(check_webui()):
                print("Open WebUI is ready.")
                break
        except Exception as e:
            print(f"Waiting for Open WebUI to be ready... {e}")
            if time.time() - start_time > timeout:
                raise Exception("Timeout waiting for Open WebUI to be ready.")
            time.sleep(3)
    print("Open WebUI is ready.")
    print("Docker Compose is running.")
    print("You can access it at http://localhost:3000\n\n")

    if platform.system() in ["Linux", "Darwin"]:  # Include macOS (Darwin) and Linux
        print("Changing permissions for the database file...")
        # Change permissions for the database file
        subprocess.run(
            ["sudo", "chown", "-R", f"{os.getenv('USER')}:{os.getenv('USER')}", "./open-webui/"],
            check=True
        )
        print("Permissions changed.")


def prompt_user():
    while True:
        response = input(
            "Please CREATE/LOG IN an account in Open WebUI at http://localhost:3000 to ask questions.\n\n\nHave you created your account? (yes/no): ").strip().lower()
        if response in ["yes", "y"]:
            return True
        elif response in ["no", "n"]:
            print("Please go create an account and come back.")
        else:
            print("Please enter 'yes' or 'no'.")


def load_function_content():
    with open(FUNCTION_PATH, "r") as f:
        return f.read()


def install_function_for_all_users():
    # Load the function content
    function_content = load_function_content()

    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all user IDs
    cursor.execute("SELECT id FROM user;")
    user_ids = [row[0] for row in cursor.fetchall()]
    print(f"Found {len(user_ids)} users in the database.")

    if not user_ids:
        print("No users found in the database. Please ensure you've created an account.")
        conn.close()
        return

    # Load the SQL script
    with open(SQL_SCRIPT_PATH, "r") as f:
        sql_script = f.read()

    # Install the function for each user
    for user_id in user_ids:
        print(f"Installing function for user: {user_id}")
        # Avoid duplicates
        cursor.execute(
            "DELETE FROM function WHERE user_id = ? AND id = 'n8n';", (user_id,))
        cursor.execute(sql_script, (user_id, function_content))
        print(f"Installed n8n function for user: {user_id}")

    # Commit changes and close
    conn.commit()
    conn.close()
    print("Function installation complete. Please reload the page and select n8n in the model list.")


def should_install_function():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM function WHERE id = 'n8n';")
    function_count = cursor.fetchone()[0]
    conn.close()
    return function_count == 0


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
                f"Snapshot '{SNAPSHOT_NAME}' uploaded successfully. Collection '{COLLECTION_NAME}' created/restored.")
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
        collections = client.get_collections()
        collection_names = [col.name for col in collections.collections]
        if COLLECTION_NAME in collection_names:
            print(f"Collection '{COLLECTION_NAME}' is now available.")
        else:
            print(f"Warning: Collection '{COLLECTION_NAME}' was not created.")

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


def setup_qdrant():
    """Set up Qdrant by creating the collection and restoring the snapshot."""
    client = QdrantClient(url=QDRANT_URL, api_key=API_KEY)

    try:
        # Verify connection
        client.get_collections()
        print("Connected to Qdrant.")

        # Create collection if it doesn't exist
        collections = client.get_collections().collections
        if any(c.name == COLLECTION_NAME for c in collections):
            print(f"Collection '{COLLECTION_NAME}' already exists.")
        else:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=768,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                )
            )
            print(f"Collection '{COLLECTION_NAME}' created successfully.")

        # Restore snapshot
        restore_snapshot()

    except Exception as e:
        raise Exception(f"Qdrant setup failed: {e}")


def main():
    try:
        start_docker()
        # Set up Qdrant
        print("Setting up Qdrant...")
        setup_qdrant()
        if should_install_function():
            print("Installing n8n function...")
            prompt_user()
            install_function_for_all_users()
        else:
            print("n8n function is already installed for all users.")
        print("Setup complete! You can now use the n8n function in Open WebUI.")

    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
    finally:
        # Optional: Keep Docker running or stop it
        print("Docker Compose is still running. Use 'docker-compose down' to stop it when done.")


if __name__ == "__main__":
    main()
