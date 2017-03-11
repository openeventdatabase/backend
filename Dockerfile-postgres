FROM postgres:9.5
RUN apt-get update
RUN apt-get install -y postgis postgresql-9.5-postgis-scripts
ADD /setup.sql /docker-entrypoint-initdb.d/
