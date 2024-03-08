import os
from internetarchive import get_session

config = {"s3":{"access_key": os.getenv("S3_ACCESS_KEY"), "secret_key": os.getenv("S3_SECRET_KEY")}}

session = get_session(config)
get_session()

item = session.get_item("TromboneChampCustoms")

for file in os.listdir('.charts/'):
    try:
        print(f"Uploading {file}...")
        item.upload_file('.charts/' + file)
    except Exception as e:
        print(f"Failed to upload {file} to the Internet Archive: {e}")

if not os.listdir('.charts/'):
    print("Nothing to upload!")
