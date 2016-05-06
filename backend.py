# backend.py
# openeventdatabase

import os
import falcon
import psycopg2
import uuid
import json
import codecs

def db_connect():
    try:
      db = psycopg2.connect(dbname="oedb")
    except:
      db_host = os.getenv("DB_HOST","localhost")
      db_password = os.getenv("POSTGRES_PASSWORD","")
      db = psycopg2.connect(dbname="oedb",host=db_host,password=db_password)

    return db

def standard_headers(resp):
    resp.set_header('X-Powered-By', 'OpenEventDatabase')
    resp.set_header('Access-Control-Allow-Origin', '*')
    resp.set_header('Access-Control-Allow-Headers', 'X-Requested-With')

class StatsResource(object):
    def on_get(self, req, resp):
        db = db_connect()
        cur = db.cursor()
        cur.execute("SELECT count(*) as events_count, max(createdate) as last_created, max(lastupdate) as last_updated from events;")
        stat = cur.fetchone()
        cur.close()
        db.close()

        standard_headers(resp)
        resp.body = """{"events_count": %s, "last_created": "%s", "last_updated": "%s"}""" % (stat[0], stat[1],stat[2])
        resp.status = falcon.HTTP_200

class EventsResource(object):
    def on_get(self,req,resp):
        db = db_connect()
        cur = db.cursor()
        # get event geojson Feature
        cur.execute("""
SELECT format('{"type":"Feature", "id": "'|| events_id::text ||'", "properties": '|| events_tags::text ||', "geometry":'|| st_asgeojson(geom)) ||' }'
FROM events
JOIN geo ON (hash=events_geo)""");
        standard_headers(resp)
        resp.body = '{"type": "FeatureCollection","features": ['+','.join([x[0] for x in cur.fetchall()])+']}'
        resp.status = falcon.HTTP_200

class EventResource(object):
    def on_get(self, req, resp, id = None):
        standard_headers(resp)
        db = db_connect()
        cur = db.cursor()
        if id is None:
            # get query search parameters

            if 'bbox' in req.params:
                # limit search with bbox (E,S,W,N)
                event_bbox = cur.mogrify(" AND geom && ST_SetSRID(ST_MakeBox2D(ST_Point(%s,%s),ST_Point(%s,%s)),4326) ",tuple(req.params['bbox']))
            else:
                event_bbox = ""

            if 'near' in req.params:
                # limit search with location+distance (long, lat, distance in meters)
                event_bbox = cur.mogrify(" AND geom && st_expand(st_buffer(st_setsrid(st_makepoint(%s,%s),4326)::geography,%s)::geometry,0) ",tuple(req.params['near']))
            else:
                event_bbox = ""

            if 'when' in req.params:
                # limit search with fixed time
                event_when = cur.mogrify("tstzrange(%s,%s,'[]')",(req.params['when'],req.params['when']))
            else:
                event_when = "'[now(),now()]'"

            if 'what' in req.params:
                # limit search based on "what"
                event_what = cur.mogrify(" AND events_what LIKE %s ",(req.params['what']+"%",))
            else:
                event_what = ""

            if 'type' in req.params:
                # limit search based on type (scheduled, forecast, unscheduled)
                event_type = cur.mogrify(" AND events_type = %s ",(req.params['type'],))
            else:
                event_type = ""

            # search recent active events
            cur.execute("""
SELECT '{"type":"Feature", "properties": '|| (events_tags::jsonb || jsonb_build_object('id',events_id,'createdate',createdate,'lastupdate',lastupdate))::text ||', "geometry":'|| st_asgeojson(st_centroid(geom)) ||' }' as feature
    FROM events
    JOIN geo ON (hash=events_geo) """ + event_bbox +"""
    WHERE events_when @> """+ event_when + event_what + event_type +"""
    ORDER BY createdate DESC
    LIMIT 50;
""")
            resp.body = '{"type": "FeatureCollection","features": ['+','.join([x[0] for x in cur.fetchall()])+']}'
            resp.status = falcon.HTTP_200
        else:
            # get single event geojson Feature by id
            cur.execute("""
SELECT format('{"type":"Feature", "properties": '|| (events_tags::jsonb || jsonb_build_object('id',events_id,'createdate',createdate,'lastupdate',lastupdate))::text ||', "geometry":'|| st_asgeojson(geom)) ||' }'
FROM events
JOIN geo ON (hash=events_geo)
WHERE events_id=%s;""", (id,))

            e = cur.fetchone()
            if e is not None:
                resp.body = e[0]
                resp.status = falcon.HTTP_200
            else:
                resp.status = falcon.HTTP_404
        db.close()

    def on_post(self, req, resp):
        standard_headers(resp)

        # get request body payload (geojson Feature)
        body = req.stream.read().decode('utf-8')
        j=json.loads(body)
        if "properties" not in j or "geometry" not in j:
            resp.body = "missing 'geometry' or 'properties' elements"
            resp.status = falcon.HTTP_400
        if "start" not in j['properties']:
            event_start = j['properties']['when']
        else:
            event_start = j['properties']['start']
        if "stop" not in j['properties']:
            event_stop = j['properties']['when']
        else:
            event_stop = j['properties']['stop']
        if event_start == event_stop:
            bounds = '[]'
        else:
            bounds = '[)'
        # connect to db and insert
        db = db_connect()
        cur = db.cursor()
        # get the geometry part
        geometry=json.dumps(j['geometry'])
        # insert into geo table if not existing
        cur.execute("""INSERT INTO geo (hash, geom) SELECT * FROM (SELECT md5(ewkt) as hash, st_setsrid(st_geomfromewkt(ewkt),4326) as geom FROM (SELECT st_asewkt(st_geomfromgeojson( %s )) as ewkt) as g) as i ON CONFLICT DO NOTHING RETURNING hash;""",(geometry,))
        # get its id (md5 hash)
        h = cur.fetchone()
        if h is None:
            cur.execute("""SELECT md5(st_asewkt(st_geomfromgeojson( %s )));""",(geometry,))
            h = cur.fetchone()
        cur.execute("""INSERT INTO events ( events_type, events_what, events_when, events_tags, events_geo) VALUES (%s, %s, tstzrange(%s,%s,%s) , %s, %s) RETURNING events_id;""",(j['properties']['type'],j['properties']['what'],event_start, event_stop, bounds, json.dumps(j['properties']),h[0]))
        # get newly created event id
        e = cur.fetchone()
        db.commit()
        cur.close()
        db.close()
        # send back to client
        resp.body = """{"id":"%s"}""" % (e[0])
        resp.status = falcon.HTTP_201

# falcon.API instances are callable WSGI apps
app = falcon.API()

# Resources are represented by long-lived class instances
events = EventsResource()
event = EventResource()
stats = StatsResource()

# things will handle all requests to the matching URL path
app.add_route('/events', events)
app.add_route('/event/{id}', event)  # handle single event requests
app.add_route('/event', event)  # handle single event requests
app.add_route('/stats', stats)
