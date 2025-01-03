import os
import re
import sys
import json
import zipfile
import shutil
import hashlib
import aiohttp
import aiofiles
import disnake
import traceback
from typing import Optional
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from dotenv import load_dotenv
from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ServiceAccountCreds

# used for local testing
load_dotenv()

service_account_key = json.loads(os.getenv('SERVICE_ACCOUNT_KEY'))

GOOGLE_CREDS = ServiceAccountCreds(
    scopes=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.resource",
    ],
    **service_account_key
)


class DownloadClient(disnake.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.message_cache = []
        with open('.config/last_message.txt', 'r') as f:
            self.last_message_id = int(f.read().strip())
        with open('docs/data/db.json', 'r', encoding='utf-8') as f:
            self.db = json.load(f)
        # We'll init this later
        self.session: aiohttp.ClientSession = None
        self.user_agent = self.http.user_agent
    

    def parse_google_download_link(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        patterns = [
            r"^/file/d/(.*?)/(edit|view)$",
            r"^/file/u/[0-9]+/d/(.*?)/(edit|view)$",
            r"^/file/d/(.*?)/?(edit|view)?$",
            r"^/file/u/[0-9]+/d/?(.*?)/?(edit|view)?$",
        ]
        for pattern in patterns:
            match = re.match(pattern, parsed.path)
            if match:
                return match.groups()[0]
        return None
    

    async def download_google_file(self, file_id: str, path: str):
        async with Aiogoogle(service_account_creds=GOOGLE_CREDS) as aiogoogle:
            drive_v3 = await aiogoogle.discover("drive", "v3")
            await aiogoogle.as_service_account(
                drive_v3.files.get(
                    fileId=file_id, download_file=path, alt="media", acknowledgeAbuse=False
                ),
            )
        

    def snowflake_to_datetime(self, snowflake) -> datetime:
        timestamp = int(snowflake) >> 22
        timestamp += 1420070400000 # Discord's epoch
        return datetime.fromtimestamp(timestamp / 1000)
    

    async def download_discord_link(self, url: str, path: str):
        parsed_url = urlparse(url)
        expire_time = parse_qs(parsed_url.query).get('ex', None)
        if expire_time:
            expire_time = int(expire_time[0], 16)
            timestamp = datetime.fromtimestamp(expire_time)
            if timestamp > datetime.now():
                async with self.session.get(url) as response:
                    # we can try refreshing the URL below if we get a non-200 response
                    if response.status == 200:
                        async with aiofiles.open(path, 'wb') as file:
                            async for data, _ in response.content.iter_chunks():
                                await file.write(data)
                            return
        
        if not self.message_cache:
            submissions_channel: disnake.TextChannel = self.get_channel(int(os.getenv('SUBMISSIONS_CHANNEL')))
            self.message_cache = await submissions_channel.history(
                limit=None, after=self.snowflake_to_datetime(self.last_message_id), oldest_first=True
            ).flatten()
        
        attachment_id = parsed_url.path.split("/")[-2]

        for message in self.message_cache:
            for a in message.attachments:
                if a.id == attachment_id:
                    await a.save(fp=path)
                    return
        
        raise FileNotFoundError
    
    async def download_dropbox_link(self, url: str, path: str):
        url  = url.replace("dl=0", "dl=1")
        async with self.session.get(url) as response:
            if response.status != 200:
                raise FileNotFoundError
            async with aiofiles.open(path, 'wb') as file:
                async for data, _ in response.content.iter_chunks():
                    await file.write(data)
                return

    
    async def get_toottally_id(self, filename, hash):
        try:
            async with self.session.get(f'https://toottally.com/hashcheck/{hash}/') as r:
                if r.status == 200:
                    return int(await r.text())
                else:
                    print(f'Failed to get TootTally ID for {filename} [{hash}] - Error {r.status}')
                    return None
        except Exception as e:  # noqa: E722
            print(f'Failed to get TootTally ID for {filename} (Hash {hash}) - Unknown Error: {e}')
            return None
    
    def sanitise_filename(self, filename):
        return re.sub(r"[/\\?%*:|\"<>\x7F\x00-\x1F]", "-", filename)
        
    def extract_files_from_zip(self, zip_filepath):
        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            return sorted(zip_ref.namelist())

    def extract_song_info(self, zip_filepath):
        song_info_keys = ['name', 'shortName', 'trackRef', 'author', 'year', 'genre', 'description',
                        'tempo', 'timesig', 'difficulty', 'savednotespacing', 'note_color_start',
                        'note_color_end', 'endpoint', 'hash']

        try:
            with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
                song_tmb_files = [f for f in zip_ref.namelist() if 'song.tmb' in f]
                if len(song_tmb_files) > 1:
                    print(f"{zip_filepath} has more than one song.tmb file!")
                elif len(song_tmb_files) == 0:
                    print(f"{zip_filepath} has no song.tmb file!")
                    return {key: None for key in song_info_keys}

                song_tmb_file_path = song_tmb_files[0]

                # Read the JSON content from "song.tmb"
                with zip_ref.open(song_tmb_file_path) as song_tmb_file:
                    song_info = json.load(song_tmb_file)
                    song_tmb_file.seek(0)
                
                # Compute SHA-256 hash of "song.tmb" file
                hasher = hashlib.sha256()
                with zip_ref.open(song_tmb_file_path, 'r') as song_tmb_file:
                    buf = song_tmb_file.read(65536)
                    while len(buf) > 0:
                        hasher.update(buf)
                        buf = song_tmb_file.read(65536)
                song_info["hash"] = hasher.hexdigest()

                # Extract specified keys from "song.tmb"
                extracted_info = {key: song_info.get(key, None) for key in song_info_keys}
                return extracted_info

        except (json.JSONDecodeError):
            # Return None if the zip file is not valid or "song.tmb" is not a valid JSON file
            print(f"{zip_filepath} is not a valid chart!")
            return {key: None for key in song_info_keys}
        except (NotImplementedError, zipfile.BadZipFile):
            print(f"{zip_filepath} is not a valid ZIP file!")
            return {key: None for key in song_info_keys}
    
    def truncate_string_to_bytes(self, s: str, max_bytes: int) -> str:
        encoded = s.encode('utf-8')
        truncated = encoded[:max_bytes]
        return truncated.decode('utf-8', 'ignore')


    async def main(self):
        self.session = aiohttp.ClientSession()
        channel = self.get_channel(int(os.getenv('CHARTS_CHANNEL')))
        tootbender = await channel.guild.getch_member(int(os.getenv('TOOTBENDER_ID')))
        print('Fetching recent messages...')

        chart_id = int(self.db[-1]["id"])

        def filter(message: disnake.Message):
            if message.author != tootbender:
                return False
            if not message.embeds:
                return False
            if not message.components:
                return False
            return True

        count = 0
        last = self.last_message_id
            
        async for message in channel.history(
            limit=None, after=self.snowflake_to_datetime(self.last_message_id), oldest_first=True
        ).filter(filter):
            last = message.id
            _id = str(int(chart_id) + 1).zfill(5)
            url = None
            for row in message.components:
                for component in row.children:
                    if component.type != disnake.ComponentType.button:
                        continue
                    if component.label != "Download Chart":
                        continue
                    url = component.url
                    break
            
            if not url:
                continue
            if not message.embeds[0].description:
                continue
            mentions = re.findall(r"<@!?(\d+)>", message.embeds[0].description)
            users = []

            for id in mentions:
                user = channel.guild.get_member(id)
                if not user:
                    try:
                        user = await channel.guild.fetch_member(id)
                    except disnake.errors.NotFound:
                        user = await self.fetch_user(id)
                if user:
                    users.append(user)

            if not users:
                charter = None
            else:
                charter = users[0].display_name
            
            if message.embeds[0].title:
                tempfile = self.sanitise_filename(f"{_id}. {message.embeds[0].title} [{charter if charter else 'Unknown'}].zip")
            else:
                tempfile = f"{_id}. download.zip"
            
            print(f"Downloading {tempfile} by {charter} (Message ID: {message.id})")
            
            # TODO: Add failed downloads to a list and post to a webhook or something idk
            if 'cdn.discordapp.com/attachments/' in url:
                try:
                    await self.download_discord_link(url, tempfile)
                except FileNotFoundError:
                    print(f"ERROR: Failed to find a download link for {url} to save to {tempfile}")
                    chart_id = _id
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                    continue
                except Exception as e:
                    print(f"ERROR: Failed to download Discord link {url} to {tempfile}")
                    chart_id = _id
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                    continue
            elif 'drive.google.com/' in url:
                try:
                    gdrive_id = self.parse_google_download_link(url)
                    if not gdrive_id:
                        print(f"ERROR: Failed to parse Google Drive link {url} to save to {tempfile}")
                        chart_id = _id
                        continue
                    await self.download_google_file(gdrive_id, tempfile)
                except Exception as e:
                    print(f"ERROR: Failed to download Google Drive link for {url} to {tempfile}")
                    chart_id = _id
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                    continue
            elif 'dropbox.com/' in url:
                try:
                    await self.download_dropbox_link(url, tempfile)
                except FileNotFoundError:
                    print(f"ERROR: Failed to find a download link for {url} to save to {tempfile}")
                    chart_id = _id
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                    continue
                except Exception as e:
                    print(f"ERROR: Failed to download Dropbox link {url} to {tempfile}")
                    chart_id = _id
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                    continue
            else:
                print(f"ERROR: Unsupported download link: {url}")
                continue

            song_info = self.extract_song_info(tempfile)

            if song_info.get("name", None) and song_info.get("author", None):
                filename = f"{_id}. {song_info['name']} - {song_info['author']} [{charter if charter else 'Unknown'}].zip"
                if len(filename.encode('utf-8')) > 180: # estimated guess to keep under name limits
                    filename = f"{_id}. {song_info['name']} [{charter if charter else 'Unknown'}].zip"
                    if len(filename.encode('utf-8')) > 180:
                        _artist = self.truncate_string_to_bytes(song_info['author'], 72)
                        _song = self.truncate_string_to_bytes(song_info['name'], 72)
                        filename = f"{_id}. {_song} - {_artist}.zip"
            else:
                filename = tempfile
            filename = self.sanitise_filename(filename)
            
            try:
                filelist = self.extract_files_from_zip(tempfile)
            except Exception as e:
                print(f"ERROR: Failed to extract file list for {filename} {e}")
                filelist = []
            
            entry = {
                "filename": filename,
                "id": _id,
                "filelist": filelist
            } | song_info
            entry["version"] = None

            if song_info.get('hash', None):
                entry["tt_id"] = await self.get_toottally_id(filename, song_info["hash"])
            else:
                entry["tt_id"] = None
            entry['pixeldrain_id'] = None # Depreciated
            entry["download_path"] = None # This will be sorted later
            entry['charter'] = charter
            if users:
                entry['user_id'] = users[0].id
            else:
                entry['user_id'] = None
            entry['message_id'] = message.id
            entry['size'] = os.path.getsize(tempfile)
            if not os.path.exists('.charts/'):
                os.makedirs('.charts/')
            shutil.move(tempfile, '.charts/' + filename)
            self.db.append(entry)
            chart_id = _id
            count += 1

        if count:
            print(f"Saving {count} charts to the database...")
            with open('docs/data/db.json', 'w', encoding="utf-8") as json_file:
                json.dump(self.db, json_file, indent=4, ensure_ascii=False)
            with open('.config/last_message.txt', 'w') as file:
                file.write(str(last))
        else:
            print("No new charts added to the database")
        
        await self.close()
    
    async def on_ready(self):
        try:
            await self.main()
        except Exception:
            print(traceback.format_exc())
            sys.exit('Encountered a fatal error!')


if __name__ == "__main__":
    client = DownloadClient()
    client.run(os.getenv("DISCORD_TOKEN"))
