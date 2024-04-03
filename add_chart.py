import download
import os
import json
import asyncio

filename = '03218. my time - bo en [Envy].zip'
id = '03218'
charter = 'Envy'

async def main():
    with open('docs/data/db.json', 'r', encoding='utf-8') as f:
        db = json.load(f)
    client = download.DownloadClient()

    song_info = client.extract_song_info(filename)

    try:
        filelist = client.extract_files_from_zip(filename)
    except Exception as e:
        print(f"ERROR: Failed to extract file list for {filename} {e}")
        filelist = []

    entry = {
        "filename": filename,
        "id": id,
        "filelist": filelist
    } | song_info
    entry["version"] = None

    if song_info.get('hash', None):
        entry["tt_id"] = await client.get_toottally_id(filename, song_info["hash"])
    else:
        entry["tt_id"] = None
    entry['pixeldrain_id'] = None # This will be sorted later
    entry['charter'] = charter
    entry['size'] = os.path.getsize(filename)

    db.append(entry)

    with open('docs/data/db.json', 'w', encoding="utf-8") as json_file:
        json.dump(db, json_file, indent=4, ensure_ascii=False)

asyncio.run(main())