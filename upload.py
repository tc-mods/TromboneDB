import os
import json
import requests
import boto3
import botocore
from dotenv import load_dotenv

# Used for development purposes
load_dotenv()

if not os.path.exists(".charts/"):
    print("No charts to upload!")
    exit()

s3 = boto3.client("s3",
  endpoint_url = f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
  aws_access_key_id = os.getenv("R2_ACCESS_KEY_ID"),
  aws_secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY"),
  region_name = "auto"
)

def upload_file_to_pixeldrain(file_path):
    url = "https://pixeldrain.com/api/file"
    with open(file_path, "rb") as f:
        file_path = os.path.basename(file_path)
        r = requests.post(url, files={"file": f}, auth=("", os.getenv("PIXELDRAIN_KEY")), data={"name": file_path.split(".")[0] + ".zip", "anonymous": False})
        if r.status_code == 201:
            print(f"File {file_path} uploaded successfully: {r.json()["id"]}")
            return r.json()["id"]
        else:
            print(f"Failed to upload {file_path}. Status code: {r.status_code}")
            return None

def upload_file_to_r2(file_path):
    with open(file_path, "rb") as f:
        file_path = os.path.basename(file_path)
        filename = file_path.split(".")[0] + ".zip"
        count = 0
        exists = True
        while exists:
            try:
                s3.head_object(Bucket=os.getenv("R2_BUCKET_NAME"), Key=filename)
                count += 1
                filename = file_path.split(".")[0] + f"-{count}.zip"
            except botocore.exceptions.ClientError:
                exists = False
                s3.upload_fileobj(f, os.getenv("R2_BUCKET_NAME"), filename)
                print(f"File {file_path} uploaded successfully: {filename}")
        return filename

with open("docs/data/db.json", "r", encoding="utf-8") as f:
    db = json.load(f)

filelist = os.listdir(".charts/")
if not filelist:
    print("No charts to upload!")
    exit()

for idx, chart in enumerate(db):
    # if not chart["pixeldrain_id"] and chart["filename"] in os.listdir(".charts/"):
    #     chart["pixeldrain_id"] = upload_file_to_pixeldrain(".charts/" + chart["filename"])
    #     db[idx] = chart
    if not chart["download_path"] and chart["filename"] in filelist:
        chart["download_path"] = upload_file_to_r2(".charts/" + chart["filename"])
        db[idx] = chart

with open("docs/data/db.json", "w", encoding="utf-8") as json_file:
    json.dump(db, json_file, indent=4, ensure_ascii=False)
