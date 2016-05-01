FROM ubuntu:15.10
WORKDIR /setup
RUN apt-get update
RUN apt-get install -y postgresql-9.4
RUN apt-get install -y postgresql-server-dev-9.4
RUN apt-get install -y postgis
RUN apt-get install -y python3-dev
RUN apt-get install -y python3-pip
RUN pip3 install --system uwsgi
ADD /setup* /setup/
ADD /requirements.txt /setup/
USER postgres
RUN service postgresql start && /setup/setup.sh
WORKDIR /app
CMD service postgresql start && uwsgi --http :8080 --wsgi-file backend.py --callable app
