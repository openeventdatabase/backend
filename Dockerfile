FROM ubuntu:15.10
WORKDIR /app
RUN apt-get update
RUN apt-get install -y postgresql-9.4
RUN apt-get install -y postgresql-server-dev-9.4
RUN apt-get install -y postgis
RUN apt-get install -y python3-dev
RUN apt-get install -y python3-pip
