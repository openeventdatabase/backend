# backend.py
# openeventdatabase

import json
import os

import falcon
import psycopg2
import psycopg2.extras


def db_connect():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "oedb"),
        host=os.getenv("DB_HOST", None),
        password=os.getenv("POSTGRES_PASSWORD", None),
        user=os.getenv("DB_USER", None))


class HeaderMiddleware:

    def process_response(self, req, resp, resource):
        resp.set_header('X-Powered-By', 'OpenEventDatabase')
        resp.set_header('Access-Control-Allow-Origin', '*')
        resp.set_header('Access-Control-Allow-Headers', 'X-Requested-With')


class StatsResource(object):
    def on_get(self, req, resp):
        db = db_connect()
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT count(*) as events_count, max(createdate) as last_created, max(lastupdate) as last_updated from events;")
        stat = cur.fetchone()
        cur.close()
        db.close()

        resp.body = json.dumps(dict(stat))
        resp.status = falcon.HTTP_200


class BaseEvent:

    def row_to_feature(self, row):
        properties = dict(row['events_tags'])
        properties.update({
            'createdate': str(row['createdate']),
            'last_updated': str(row['lastupdate'])
        })
        return {
            "type": "Feature",
            "geometry": json.loads(row['geometry']),
            "id": row['events_id'],
            "properties": properties
        }


class EventsResource(BaseEvent):

    def on_get(self, req, resp):
        db = db_connect()
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT events_id, events_tags, createdate, lastupdate, st_asgeojson(geom) as geometry FROM events JOIN geo ON (hash=events_geo)")
        resp.body = json.dumps({
            "type": "FeatureCollection",
            "features": [self.row_to_feature(r) for r in cur.fetchall()]
        })
        resp.status = falcon.HTTP_200


class EventResource(BaseEvent):
    def maybe_insert_geometry(self, geometry, cur):
        # insert into geo table if not existing
        cur.execute("""INSERT INTO geo (hash, geom, geom_center) SELECT *, st_centroid(geom) FROM (SELECT md5(ewkt) as hash, st_setsrid(st_geomfromewkt(ewkt),4326) as geom FROM (SELECT st_asewkt(st_geomfromgeojson( %s )) as ewkt) as g) as i ON CONFLICT DO NOTHING RETURNING hash;""", (geometry,))
        # get its id (md5 hash)
        h = cur.fetchone()
        if h is None:
            cur.execute("""SELECT md5(st_asewkt(st_geomfromgeojson( %s )));""", (geometry,))
            h = cur.fetchone()
        return h

    def on_get(self, req, resp, id=None):
        db = db_connect()
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if id is None:
            # get query search parameters

            if 'bbox' in req.params:
                # limit search with bbox (E,S,W,N)
                event_bbox = cur.mogrify(" AND geom && ST_SetSRID(ST_MakeBox2D(ST_Point(%s,%s),ST_Point(%s,%s)),4326) ",tuple(req.params['bbox'])).decode("utf-8")
                event_dist = ""
            elif 'near' in req.params:
                # Limit search with location+distance
                # (long, lat, distance in meters)
                if len(req.params['near']) < 3:
                    dist = 1
                else:
                    dist = req.params['near'][2]
                event_bbox = cur.mogrify(" AND ST_Intersects(geom, ST_Buffer(st_setsrid(st_makepoint(%s,%s),4326)::geography,%s)::geometry) ",(req.params['near'][0], req.params['near'][1], dist)).decode("utf-8")
                event_dist = cur.mogrify(", 'distance', ST_Length(ST_ShortestLine(geom, st_setsrid(st_makepoint(%s,%s),4326))::geography) ",(req.params['near'][0], req.params['near'][1])).decode("utf-8")
            else:
                event_bbox = ""
                event_dist = ""

            if 'when' in req.params:
                # limit search with fixed time
                event_when = cur.mogrify("tstzrange(%s,%s,'[]')", (req.params['when'], req.params['when'])).decode("utf-8")
            elif 'start' in req.params and 'stop' in req.params:
                # limit search with fixed time (start to stop)
                event_when = cur.mogrify("tstzrange(%s,%s,'[]')", (req.params['start'], req.params['stop'])).decode("utf-8")
            elif 'start' in req.params and 'stop' not in req.params:
                # limit search with fixed time (start to now)
                event_when = cur.mogrify("tstzrange(%s,now(),'[]')", (req.params['start'],)).decode("utf-8")
            elif 'start' not in req.params and 'stop' in req.params:
                # limit search with fixed time (now to stop)
                event_when = cur.mogrify("tstzrange(now(),%s,'[]')", (req.params['stop'],)).decode("utf-8")
            else:
                event_when = """tstzrange(now(),now(),'[]')"""

            if 'what' in req.params:
                # limit search based on "what"
                event_what = cur.mogrify(" AND events_what LIKE %s ", (req.params['what']+"%",)).decode("utf-8")
            else:
                event_what = ""

            if 'type' in req.params:
                # limit search based on type (scheduled, forecast, unscheduled)
                event_type = cur.mogrify(" AND events_type = %s ", (req.params['type'],)).decode("utf-8")
            else:
                event_type = ""

            event_geom = "geom_center"
            if 'geom' in req.params:
                if req.params['geom'] == 'full':
                    event_geom = "geom"

            # Search recent active events.
            cur.execute("""
SELECT '{"type":"Feature", "properties": '|| (events_tags::jsonb || jsonb_build_object('id',events_id,'createdate',createdate,'lastupdate',lastupdate """+event_dist+"""))::text ||', "geometry":'|| st_asgeojson("""+event_geom+""") ||' }' as feature
    FROM events
    JOIN geo ON (hash=events_geo) """ + event_bbox +"""
    WHERE events_when && """+ event_when + event_what + event_type +"""
    ORDER BY createdate DESC
    LIMIT 200;
""")
            resp.body = """{"type":"FeatureCollection", "features": [
"""+""",
""".join([x[0] for x in cur.fetchall()])+"""
]}"""
            resp.status = falcon.HTTP_200
        else:
            # Get single event geojson Feature by id.
            cur.execute("SELECT events_id, events_tags, createdate, lastupdate, st_asgeojson(geom) as geometry FROM events JOIN geo ON (hash=events_geo) WHERE events_id=%s", [id])

            e = cur.fetchone()
            if e is not None:
                resp.body = json.dumps(self.row_to_feature(e))
                resp.status = falcon.HTTP_200
            else:
                resp.status = falcon.HTTP_404
        db.close()

    def insert_or_update(self, req, resp, id, query):

        # get request body payload (geojson Feature)
        body = req.stream.read().decode('utf-8')
        j = json.loads(body)
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
        h = self.maybe_insert_geometry(geometry,cur)
        params = (j['properties']['type'], j['properties']['what'], event_start, event_stop, bounds, json.dumps(j['properties']), h[0])
        if id:
            params = params + (id,)
        cur.execute(query, params)
        # get newly created event id
        e = cur.fetchone()
        db.commit()
        cur.close()
        db.close()
        # send back to client
        resp.body = """{"id":"%s"}""" % (e[0])
        resp.status = falcon.HTTP_201

    def on_post(self, req, resp):
        self.insert_or_update(req, resp, None, """INSERT INTO events ( events_type, events_what, events_when, events_tags, events_geo) VALUES (%s, %s, tstzrange(%s,%s,%s) , %s, %s) RETURNING events_id;""")

    def on_put(self, req, resp, id):
        self.insert_or_update(req, resp, id, """UPDATE events SET ( events_type, events_what, events_when, events_tags, events_geo) = (%s, %s, tstzrange(%s,%s,%s) , %s, %s) WHERE events_id = %s RETURNING events_id;""")

    def on_delete(self, req, resp, id):
        db = db_connect()
        cur = db.cursor()
        cur.execute("""DELETE FROM events WHERE events_id = %s;""", (id,));
        db.commit()
        cur.close()
        db.close()
        if cur.rowcount:
            resp.status = falcon.HTTP_204
        else:
            resp.status = falcon.HTTP_404

# Falcon.API instances are callable WSGI apps.
app = falcon.API(middleware=[HeaderMiddleware()])

# Resources are represented by long-lived class instances
events = EventsResource()
event = EventResource()
stats = StatsResource()

# things will handle all requests to the matching URL path
app.add_route('/events', events)
app.add_route('/event/{id}', event)  # handle single event requests
app.add_route('/event', event)  # handle single event requests
app.add_route('/stats', stats)
