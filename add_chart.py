import download
import os
import json
import asyncio
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("filename")
parser.add_argument("id")
parser.add_argument("charter")

args = parser.parse_args()

async def main():
    with open("docs/data/db.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    client = download.DownloadClient()

    song_info = client.extract_song_info(args.filename)

    try:
        filelist = client.extract_files_from_zip(args.filename)
    except Exception as e:
        print(f"ERROR: Failed to extract file list for {args.filename} {e}")
        filelist = []

    entry = {
        "filename": args.filename,
        "id": args.id,
        "filelist": filelist
    } | song_info
    entry["version"] = None

    if song_info.get("hash", None):
        entry["tt_id"] = await client.get_toottally_id(args.filename, song_info["hash"])
    else:
        entry["tt_id"] = None
    entry["pixeldrain_id"] = None # This will be sorted later
    entry["charter"] = args.charter
    entry["size"] = os.path.getsize(args.filename)

    db.append(entry)

    with open("docs/data/db.json", "w", encoding="utf-8") as json_file:
        json.dump(db, json_file, indent=4, ensure_ascii=False)

asyncio.run(main())