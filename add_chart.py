import download
import os
import json
import asyncio
import aiohttp
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
    
    
    if song_info.get("name", None) and song_info.get("author", None):
        new_filename = f"{args.id}. {song_info['name']} - {song_info['author']} [{args.charter if args.charter else 'Unknown'}].zip"
        if len(new_filename.encode('utf-8')) > 180:
            new_filename = f"{args.id}. {song_info['name']} [{args.charter if args.charter else 'Unknown'}].zip"
            if len(new_filename.encode('utf-8')) > 180:
                _artist = client.truncate_string_to_bytes(song_info['author'], 72)
                _song = client.truncate_string_to_bytes(song_info['name'], 72)
                new_filename = f"{args.id}. {_song} - {_artist}.zip"

    entry = {
        "filename": new_filename,
        "id": args.id,
        "filelist": filelist
    } | song_info
    entry["version"] = None

    if song_info.get("hash", None):
        client.session = aiohttp.ClientSession()
        entry["tt_id"] = await client.get_toottally_id(args.filename, song_info["hash"])
    else:
        entry["tt_id"] = None
    entry["pixeldrain_id"] = None # This will be sorted later
    entry["download_path"] = None
    entry["charter"] = args.charter
    entry["size"] = os.path.getsize(args.filename)

    db.append(entry)

    os.rename(args.filename, ".charts/" + new_filename)

    with open("docs/data/db.json", "w", encoding="utf-8") as json_file:
        json.dump(db, json_file, indent=4, ensure_ascii=False)

asyncio.run(main())