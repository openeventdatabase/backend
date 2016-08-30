FROM ubuntu:16.04
RUN apt-get update && \
    apt-get install -y postgresql-server-dev-all && \
    apt-get install -y python3-dev && \
    apt-get install -y python3-pip && \
    apt-get install -y libgeos-dev
RUN pip3 install uwsgi
ADD /requirements.txt /app/
WORKDIR /app
RUN pip3 install -r requirements.txt
CMD uwsgi --http :8080 --wsgi-file backend.py --callable app
