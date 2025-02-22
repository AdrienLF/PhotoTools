#!/usr/bin/env python

import os
import argparse
import sqlite3
import sqlite_vec
from PIL import Image
import numpy as np
import torch
from transformers import AutoModel, AutoProcessor
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global constants
DEFAULT_FOLDER = r"C:\Users\Adrien\Pictures\Street photo"
DB_PATH = "image_analysis.db"
DUPLICATES_FOLDER_NAME = "duplicates"
DEFAULT_SIMILARITY_THRESHOLD = 0.99  # Cosine similarity threshold for duplicates
# Adaptive default batch size based on GPU availability:
DEFAULT_BATCH_SIZE = 128 if torch.cuda.is_available() else 16


def load_siglip_model():
    """
    Loads the siglip2 model and processor using AutoModel/AutoProcessor with trust_remote_code enabled.
    Returns the model, processor, and a string identifying the model (used for DB tagging).
    """
    ckpt = "google/siglip2-so400m-patch14-384"
    model = AutoModel.from_pretrained(ckpt, device_map="auto", trust_remote_code=True).eval()
    processor = AutoProcessor.from_pretrained(ckpt, trust_remote_code=True)
    return model, processor, ckpt  # Using ckpt as the model name


def compute_embeddings_batch(model, processor, images):
    """
    Given a list of PIL images, computes their embeddings in one batch.
    Returns a NumPy array of shape (batch_size, embedding_dim).
    """
    inputs = processor(images=images, return_tensors="pt", padding="max_length", max_length=64).to(model.device)
    with torch.no_grad():
        image_embeddings = model.get_image_features(**inputs)
    return image_embeddings.cpu().numpy()


def classify_ratio(width, height):
    """
    Returns a string classification based on image dimensions.
    """
    if width > height:
        return "horizontal"
    elif height > width:
        return "vertical"
    else:
        return "square"


def init_db(db_path=DB_PATH):
    """
    Initializes the SQLite database with performance tweaks and a table for images
    (supporting multiple models via a model_name column).
    """
    conn = sqlite3.connect(db_path)
    # SQLite performance optimizations:
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            width INTEGER,
            height INTEGER,
            ratio TEXT,
            embedding BLOB,
            model_name TEXT,
            UNIQUE(file_path, model_name)
        );
    """)
    conn.commit()
    return conn


def serialize_embedding(embedding):
    """
    Serializes an array of floats into a BLOB using sqlite-vec.
    """
    from sqlite_vec import serialize_float32
    return serialize_float32(embedding.tolist())


def batch_insert_images(conn, records):
    """
    Inserts multiple records into the database in one transaction.
    Each record is a tuple:
    (file_path, width, height, ratio, serialized_embedding, model_name)
    """
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO images (file_path, width, height, ratio, embedding, model_name) VALUES (?, ?, ?, ?, ?, ?)",
            records
        )
        conn.commit()
    except Exception as e:
        print(f"Error during batch insert: {e}")


def get_all_images(conn, model_name):
    """
    Retrieves all images from the database for a given model.
    Returns a list of dicts including id, file_path, dimensions, area, and the deserialized embedding.
    """
    cur = conn.execute("SELECT id, file_path, width, height, embedding FROM images WHERE model_name = ?", (model_name,))
    rows = cur.fetchall()
    images = []
    for row in rows:
        img_id, file_path, width, height, embedding_blob = row
        embedding = np.frombuffer(embedding_blob, dtype=np.float32)
        images.append({
            "id": img_id,
            "file_path": file_path,
            "width": width,
            "height": height,
            "area": width * height,
            "embedding": embedding
        })
    return images


def cosine_similarity(vec1, vec2):
    """
    Computes the cosine similarity between two vectors.
    """
    dot = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def find_duplicates(images, threshold=DEFAULT_SIMILARITY_THRESHOLD):
    """
    Finds groups of duplicate images (by comparing cosine similarity of embeddings).
    Returns a list of groups (each group is a list of indices in the images list).
    Note: This function is O(n²) and is intended for moderate image counts.
    """
    n = len(images)
    groups = []
    visited = [False] * n
    for i in range(n):
        if visited[i]:
            continue
        group = [i]
        visited[i] = True
        for j in range(i + 1, n):
            if visited[j]:
                continue
            sim = cosine_similarity(images[i]["embedding"], images[j]["embedding"])
            if sim >= threshold:
                group.append(j)
                visited[j] = True
        if len(group) > 1:
            groups.append(group)
    return groups


def move_duplicates(duplicate_groups, images, root_folder):
    """
    Moves the inferior (smaller) versions of duplicate images to a dedicated duplicates folder.
    """
    duplicates_folder = os.path.join(root_folder, DUPLICATES_FOLDER_NAME)
    os.makedirs(duplicates_folder, exist_ok=True)
    for group in duplicate_groups:
        # Keep the image with the largest area in place.
        best_index = max(group, key=lambda idx: images[idx]["area"])
        for idx in group:
            if idx == best_index:
                continue
            src = images[idx]["file_path"]
            filename = os.path.basename(src)
            dst = os.path.join(duplicates_folder, filename)
            try:
                print(f"Moving duplicate {src} to {dst}")
                shutil.move(src, dst)
            except Exception as e:
                print(f"Error moving file {src}: {e}")


def load_image_entry(file_path):
    """
    Loads an image from disk and returns a tuple:
    (file_path, width, height, ratio, image)
    Returns None if the image cannot be loaded.
    """
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            ratio = classify_ratio(width, height)
            image = img.convert("RGB")
        print(f"Loaded {file_path} [{width}x{height}, {ratio}]")
        return (file_path, width, height, ratio, image)
    except Exception as e:
        print(f"Could not open image {file_path}: {e}")
        return None


def analyze_images(root_folder, conn, model, processor, threshold, model_name, batch_size):
    """
    Walks through the folder structure to analyze images:
      - Gathers file paths.
      - Loads images concurrently.
      - Computes embeddings in batches.
      - Inserts records in batch into the database (tagged with model_name).
      - After processing, detects and moves duplicate images based only on the current model's embeddings.
    """
    # Gather all file paths.
    supported_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
    file_paths = []
    for dirpath, dirnames, filenames in os.walk(root_folder):
        if os.path.basename(dirpath) == DUPLICATES_FOLDER_NAME:
            continue
        for file in filenames:
            ext = os.path.splitext(file)[1].lower()
            if ext in supported_exts:
                file_paths.append(os.path.join(dirpath, file))

    batch_entries = []
    # Use a ThreadPoolExecutor for concurrent image loading.
    with ThreadPoolExecutor() as executor:
        future_to_fp = {executor.submit(load_image_entry, fp): fp for fp in file_paths}
        for future in as_completed(future_to_fp):
            result = future.result()
            if result is not None:
                batch_entries.append(result)
                if len(batch_entries) >= batch_size:
                    process_batch(batch_entries, conn, model, processor, model_name)
                    batch_entries = []
    if batch_entries:
        process_batch(batch_entries, conn, model, processor, model_name)

    # After processing, search for duplicates for the current model's images only.
    images = get_all_images(conn, model_name)
    duplicate_groups = find_duplicates(images, threshold)
    if duplicate_groups:
        print(f"Found {len(duplicate_groups)} group(s) of duplicates. Moving inferior versions.")
        move_duplicates(duplicate_groups, images, root_folder)
    else:
        print("No duplicates found.")


def process_batch(batch_entries, conn, model, processor, model_name):
    """
    Processes a batch of images: computes embeddings and inserts records into the database in a single transaction.
    """
    file_paths, widths, heights, ratios, images = zip(*batch_entries)
    print(f"Processing batch of {len(images)} images...")
    embeddings = compute_embeddings_batch(model, processor, list(images))
    # Prepare records for bulk insertion.
    records = []
    for i, embedding in enumerate(embeddings):
        records.append((file_paths[i], widths[i], heights[i], ratios[i],
                        serialize_embedding(embedding), model_name))
    batch_insert_images(conn, records)


def list_images_by_ratio(conn, model_name):
    """
    Retrieves and prints a list of images from the database (for the given model), sorted by aspect ratio.
    """
    cur = conn.execute("SELECT file_path, width, height, ratio FROM images WHERE model_name = ? ORDER BY ratio",
                       (model_name,))
    rows = cur.fetchall()
    if not rows:
        print("No images found in the database.")
        return
    print("Images by ratio:")
    for file_path, width, height, ratio in rows:
        print(f"{file_path} [{width}x{height}] - {ratio}")


def main():
    parser = argparse.ArgumentParser(description="Image Analyzer with siglip2 and sqlite-vec")
    parser.add_argument("--folder", type=str, default=DEFAULT_FOLDER,
                        help="Root folder to analyze images")
    parser.add_argument("--list", action="store_true",
                        help="List images info from the database without reanalyzing")
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD,
                        help="Cosine similarity threshold for duplicate detection")
    parser.add_argument("--batch_size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Number of images to process per batch")
    args = parser.parse_args()

    conn = init_db()

    print("Loading siglip2 model...")
    model, processor, model_name = load_siglip_model()
    print(f"Model '{model_name}' loaded.")

    if args.list:
        list_images_by_ratio(conn, model_name)
        return

    print("Starting analysis...")
    analyze_images(args.folder, conn, model, processor, args.threshold, model_name, args.batch_size)
    print("Analysis complete.\n")
    list_images_by_ratio(conn, model_name)


if __name__ == "__main__":
    main()
