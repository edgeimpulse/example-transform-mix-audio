FROM python:3.11.0-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libsndfile1

# Python dependencies
COPY requirements.txt ./
RUN pip3 --no-cache-dir install -r requirements.txt

COPY . ./

ENTRYPOINT [ "python3", "-u", "transform.py" ]
