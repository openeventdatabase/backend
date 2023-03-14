# backend.py
# openeventdatabase

from datetime import datetime
import json
import os
import re
import subprocess

import falcon
import psycopg2
import psycopg2.extras
import geojson

def db_connect():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "oedb"),
        host=os.getenv("DB_HOST", ""),
        password=os.getenv("POSTGRES_PASSWORD", None),
        user=os.getenv("DB_USER", ""))


class EventEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def dumps(data):
    return json.dumps(data, cls=EventEncoder, sort_keys=True, ensure_ascii=False)


class HeaderMiddleware:

    def process_response(self, req, resp, resource, params):
        resp.set_header('X-Powered-By', 'OpenEventDatabase')
        resp.set_header('Access-Control-Allow-Origin', '*')
        resp.set_header('Access-Control-Allow-Headers', 'X-Requested-With')
        resp.set_header('Access-Control-Allow-Headers', 'Content-Type')
        resp.set_header('Access-Control-Allow-Methods','GET, POST, PUT, DELETE, OPTIONS')


class StatsResource(object):
    def on_get(self, req, resp):
        db = db_connect()
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # estimated row count, way faster then count(*)
        cur.execute("SELECT reltuples::bigint FROM pg_class r WHERE relname = 'events';")
        count = cur.fetchone()[0]
        # global info
        cur.execute("SELECT max(lastupdate) as last_updated, current_timestamp-pg_postmaster_start_time() from events;")
        pg_stats = cur.fetchone()
        last = pg_stats[0]
        pg_uptime = pg_stats[1]
        uptime = subprocess.check_output(["uptime","-p"]).decode('utf-8')[0:-1]
        # summary about last 10000 events (what, last, count, sources)
        cur.execute("SELECT row_to_json(stat) from (SELECT events_what as what, left(max(upper(events_when))::text,19) as last, count(*) as count, array_agg(distinct(regexp_replace(regexp_replace(events_tags ->> 'source','^(http://|https://)',''),'/.*',''))) as source from (select * from events order by lastupdate desc limit 10000) as last group by 1 order by 2 desc) as stat;")
        recent = cur.fetchall()
        cur.close()
        db.close()
        resp.body = dumps(dict(events_count=count, last_updated=last, uptime=uptime, db_uptime=pg_uptime, recent=recent))
        resp.status = falcon.HTTP_200


class BaseEvent:

    def row_to_feature(self, row, geom_only = False):
        # only return geometry and event id
        if geom_only:
          return {
            "type": "Feature",
            "geometry": json.loads(row['geometry']),
            "properties": { "id" : row['events_id'] }
          }

        properties = dict(row['events_tags'])
        properties.update({
            'createdate': row['createdate'],
            'lastupdate': row['lastupdate'],
            'lon': row['lon'],
            'lat': row['lat'],
            "id": row['events_id']
        })
        if 'secret' in properties: # hide secret in results
            del properties['secret']
        if "distance" in row:
            properties['distance'] = row['distance']
        return {
            "type": "Feature",
            "geometry": json.loads(row['geometry']),
            "properties": properties
        }

    def rows_to_collection(self, rows, geom_only = False):
        return {
            "type": "FeatureCollection",
            "features": [self.row_to_feature(r, geom_only) for r in rows],
            "count": len(rows)
        }


class EventResource(BaseEvent):
    def maybe_insert_geometry(self, geometry, cur):
        # insert into geo table if not existing
        cur.execute("""INSERT INTO geo
                            SELECT geom, md5(st_astext(geom)) as hash, st_centroid(geom) as geom_center FROM
                                    (SELECT st_setsrid(st_geomfromgeojson( %s ),4326) as geom) as g
                                WHERE ST_IsValid(geom)
                        ON CONFLICT DO NOTHING RETURNING hash;""",
                    (geometry,))
        # get its id (md5 hash)
        h = cur.fetchone()
        if h is None:
            cur.execute("""SELECT md5(st_asewkt(geom)),
                            ST_IsValid(geom),
                            ST_IsValidReason(geom) from (SELECT st_geomfromgeojson( %s ) as geom) as g ;""", (geometry,))
            h = cur.fetchone()
        return h


    def relative_time(self, when, cur):
        when = when.upper().replace(' ','+')
        event_start = cur.mogrify("%s",(when,)).decode("utf-8")
        event_stop  = cur.mogrify("%s",(when,)).decode("utf-8")

        if when == 'NOW':
            event_start = "now()"
            event_stop  = "now()"
        if when == 'TODAY':
            event_start = "CURRENT_DATE"
            event_stop  = "CURRENT_DATE + INTERVAL '1 DAY'"
        if when == 'TOMORROW':
            event_start = "CURRENT_DATE + INTERVAL '1 DAY'"
            event_stop  = "CURRENT_DATE + INTERVAL '2 DAY'"
        if when == 'YESTERDAY':
            event_start = "CURRENT_DATE - INTERVAL '1 DAY'"
            event_stop  = "CURRENT_DATE"
        m = re.match('(LAST|NEXT)(YEAR|MONTH|WEEK|DAY|HOUR|MINUTE)',when)
        if m is not None:
            when = m.group(1)+'1'+m.group(2)+'S'
        m = re.match('(LAST|NEXT)([0-9]*)(YEAR|MONTH|WEEK|MINUTE|HOUR|DAY)S',when)
        if m is not None:
            if m.group(1) == 'LAST':
                event_start = "now() - INTERVAL '%s %s'" % m.group(2,3)
                event_stop  = "now()"
            else:
                event_start = "now()"
                event_stop  = "now() + INTERVAL '%s %s'" % m.group(2,3)

        return event_start, event_stop


    def on_get(self, req, resp, id=None, geom=None):
        db = db_connect()
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if id is None:
            event_sort = "createdate DESC"
            # get query search parameters
            if geom is not None:
                # convert our geojson geom to WKT
                geoj = json.dumps(geom)
                # buffer around geom ?
                if 'buffer' in req.params:
                  buffer = float(req.params['buffer'])
                elif geom['type'] == 'Linestring':
                  buffer = 1000 # 1km buffer by default around Linestrings
                else:
                  buffer = 0
                if buffer == 0:
                  event_bbox = cur.mogrify(" AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)) ",(geoj,)).decode("utf-8")
                else:
                  event_bbox = cur.mogrify(" AND ST_Intersects(geom, ST_Buffer(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)::geography, %s)::geometry) ",(geoj, buffer)).decode("utf-8")
                event_dist = cur.mogrify("ST_Length(ST_ShortestLine(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))::geography)::integer as distance, ",(geoj,)).decode("utf-8")
                event_sort = cur.mogrify("ST_Length(ST_ShortestLine(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))::geography)::integer, ", (geoj,)).decode("utf-8")+event_sort
            elif 'bbox' in req.params:
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
                event_bbox = cur.mogrify(" AND ST_Intersects(geom, ST_Buffer(st_setsrid(st_makepoint(%s,%s),4326)::geography,%s)::geometry) ", (req.params['near'][0], req.params['near'][1], dist)).decode("utf-8")
                event_dist = cur.mogrify("ST_Length(ST_ShortestLine(geom, st_setsrid(st_makepoint(%s,%s),4326))::geography)::integer as distance,", (req.params['near'][0], req.params['near'][1])).decode("utf-8")
                event_sort = cur.mogrify("ST_Length(ST_ShortestLine(geom, st_setsrid(st_makepoint(%s,%s),4326))::geography)::integer, ", (req.params['near'][0], req.params['near'][1])).decode("utf-8")+event_sort
            elif 'polyline' in req.params:
                # use encoded polyline as search geometry
                if 'buffer' in req.params:
                    buffer = float(req.params['buffer'])
                else:
                    buffer = 1000
                if 'polyline_precision' in req.params:
                    precision = int(req.params['polyline_precision'])
                else:
                    precision = 5
                # ST_Scale is a workaround to postgis bug not taking precision into account in ST_LineFromEncodedPolyline
                event_bbox = cur.mogrify(" AND ST_Intersects(geom, ST_Buffer(ST_Scale(ST_LineFromEncodedPolyline(%s),1/10^(%s-5),1/10^(%s-5))::geography, %s)::geometry) ",(req.params['polyline'], precision, precision, buffer)).decode("utf-8")
                event_dist = cur.mogrify("ST_Length(ST_ShortestLine(geom, ST_Scale(ST_LineFromEncodedPolyline(%s),1/10^(%s-5),1/10^(%s-5)))::geography)::integer as distance, ",(req.params['polyline'], precision, precision)).decode("utf-8")
            elif 'where:osm' in req.params:
                event_bbox = cur.mogrify(" AND events_tags ? 'where:osm' AND events_tags->>'where:osm'=%s ", (req.params['where:osm'],)).decode("utf-8")
                event_dist = ""
            elif 'where:wikidata' in req.params:
                event_bbox = cur.mogrify(" AND events_tags ? 'where:wikidata' AND events_tags->>'where:wikidata'=%s ", (req.params['where:wikidata'],)).decode("utf-8")
                event_dist = ""
            else:
                event_bbox = ""
                event_dist = ""

            if 'when' in req.params:
                # limit search with fixed time
                when = req.params['when'].upper()
                event_when = "tstzrange(%s,%s,'[]')" % (self.relative_time(when,cur))
            elif 'start' in req.params and 'stop' in req.params:
                # limit search with fixed time (start to stop)
                event_start, unused = self.relative_time(req.params['start'],cur)
                unused, event_stop = self.relative_time(req.params['stop'],cur)
                event_when = "tstzrange(%s,%s,'[]')" % (event_start, event_stop)
            elif 'start' in req.params and 'stop' not in req.params:
                # limit search with fixed time (start to now)
                event_start, unused = self.relative_time(req.params['start'],cur)
                event_when = "tstzrange(%s,now(),'[]')" % event_start
            elif 'start' not in req.params and 'stop' in req.params:
                # limit search with fixed time (now to stop)
                unused, event_stop = self.relative_time(req.params['stop'],cur)
                event_when = "tstzrange(now(),%s,'[]')" % event_stop
            else:
                event_when = "tstzrange(now(),now(),'[]')"

            if 'what' in req.params:
                # limit search based on "what"
                event_what = cur.mogrify(" AND events_what LIKE %s AND events_what LIKE %s ", (req.params['what'][:4]+"%",req.params['what']+"%")).decode("utf-8")
            else:
                event_what = ""

            if 'type' in req.params:
                # limit search based on type (scheduled, forecast, unscheduled)
                event_type = cur.mogrify(" AND events_type = %s ", (req.params['type'],)).decode("utf-8")
            else:
                event_type = ""

            if 'limit' in req.params:
                limit = cur.mogrify("LIMIT %s", (req.params['limit'],)).decode("utf-8")
            else:
                limit = "LIMIT 200"

            event_geom = "geom_center"
            geom_only = False
            if 'geom' in req.params:
                if req.params['geom'] == 'full':
                    event_geom = "geom"
                elif req.params['geom'] == 'only':
                    geom_only = True
                else:
                    event_geom = cur.mogrify("ST_SnapToGrid(geom,%s)",(req.params['geom'],)).decode("utf-8")

            # Search recent active events.
            sql = """SELECT events_id, events_tags, createdate, lastupdate, {event_dist} st_asgeojson({event_geom}) as geometry, st_x(geom_center) as lon, st_y(geom_center) as lat
                        FROM events JOIN geo ON (hash=events_geo)
                        WHERE events_when && {event_when} {event_what} {event_type} {event_bbox}
                        ORDER BY {event_sort} {limit}"""
            # No user generated content here, so format is safe.
            sql = sql.format(event_dist=event_dist, event_geom=event_geom,
                             event_bbox=event_bbox, event_what=event_what,
                             event_when=event_when, event_type=event_type,
                             event_sort=event_sort, limit=limit)
            #print(sql)
            cur.execute(sql)
            resp.body = dumps(self.rows_to_collection(cur.fetchall(), geom_only))
            resp.status = falcon.HTTP_200
        else:
            # Get single event geojson Feature by id.
            cur.execute("SELECT events_id, events_tags, createdate, lastupdate, st_asgeojson(geom) as geometry, st_x(geom_center) as lon, st_y(geom_center) as lat FROM events JOIN geo ON (hash=events_geo) WHERE events_id=%s", [id])

            e = cur.fetchone()
            if e is not None:
                resp.body = dumps(self.row_to_feature(e))
                resp.status = falcon.HTTP_200
            else:
                resp.status = falcon.HTTP_404
        db.close()

    def insert_or_update(self, req, resp, id, query):

        # get request body payload (geojson Feature)
        try:
            body = req.stream.read().decode('utf-8')
            j = json.loads(body)
        except:
            resp.body = 'invalid json or bad encoding'
            resp.status = falcon.HTTP_400
            return

        resp.body = ''
        if "properties" not in j:
            resp.body = resp.body + "missing 'properties' elements\n"
            j['properties'] = dict()
        if "geometry" not in j:
            resp.body = resp.body + "missing 'geometry' elements\n"
            j['geometry'] = None
        if "when" not in j['properties'] and ("start" not in j['properties'] or "stop" not in j['properties']) :
            resp.body = resp.body + "missing 'when' or 'start/stop' in properties\n"
            j['properties']['when'] = None
        if "type" not in j['properties']:
            resp.body = resp.body + "missing 'type' of event in properties\n"
            j['properties']['type'] = None
        if "what" not in j['properties']:
            resp.body = resp.body + "missing 'what' in properties\n"
            j['properties']['what'] = None
        if "type" in j and j['type'] != 'Feature':
            resp.body = resp.body + 'geojson must be "type":"Feature" only\n'
        if id is None and resp.body != '':
            resp.status = falcon.HTTP_400
            resp.set_header('Content-type', 'text/plain')
            return

        if 'when' in j['properties']:
            event_when = j['properties']['when']
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

        # 'secret' based authentication
        if 'secret' in j['properties']:
            secret = cur.mogrify(" AND (events_tags->>'secret' = %s OR events_tags->>'secret' IS NULL) ",(j['properties']['secret'],)).decode("utf-8")
        elif 'secret' in req.params:
            secret = cur.mogrify(" AND (events_tags->>'secret' = %s OR events_tags->>'secret' IS NULL) ",(req.params['secret'],)).decode("utf-8")
        else:
            secret = " AND events_tags->>'secret' IS NULL "

        # get the geometry part
        if j['geometry'] is not None:
            geometry=dumps(j['geometry'])
            h = self.maybe_insert_geometry(geometry,cur)
            if len(h)>1 and h[1] is False:
                resp.body = "invalid geometry: %s\n" % h[2]
                resp.status = falcon.HTTP_400
                resp.set_header('Content-type', 'text/plain')
                return
        else:
            h = [None]
        params = (j['properties']['type'], j['properties']['what'], event_start, event_stop, bounds, dumps(j['properties']), h[0])
        if id:
            params = params + (id,)
        e = None
        rows = None
        try:
            sql = cur.mogrify(query,params)
            cur.execute(query.format(secret=secret), params)
            rows = cur.rowcount
            # get newly created event id
            e = cur.fetchone()
            db.commit()
        except psycopg2.Error as err:
            print(err, sql, err.pgerror)
            db.rollback()
            pass

        # send back to client
        if e is None:
          if id is None:
              cur.execute("""SELECT events_id FROM events WHERE events_what=%s
                      AND events_when=tstzrange(%s,%s,%s) AND events_geo=%s;""",
                      (j['properties']['what'], event_start, event_stop, bounds, h[0]))
          else:
              if rows==0:
                  if 'secret' in req.params or 'secret' in j['properties']:
                      resp.status = '403 Unauthorized, secret does not match'
                  else:
                      resp.status = '403 Unauthorized, secret required'
                  return
              else:
                  cur.execute("""END; WITH s AS (SELECT * FROM events WHERE events_id = %s) SELECT e.events_id FROM events e, s WHERE e.events_what=coalesce(%s, s.events_what)
                      AND e.events_when=tstzrange(coalesce(%s, lower(s.events_when)),coalesce(%s,upper(s.events_when)),%s) AND e.events_geo=coalesce(%s, s.events_geo);""",
                      (id, j['properties']['what'], event_start, event_stop, bounds, h[0]))
          dupe = cur.fetchone()
          resp.body = """{"duplicate":"%s"}""" % (dupe[0])
          resp.status = '409 Conflict with event %s' % dupe[0]
        else:
          resp.body = """{"id":"%s"}""" % (e[0])
          if id is None:
              resp.status = falcon.HTTP_201
          else:
              resp.status = falcon.HTTP_200

        cur.close()
        db.close()

    def on_post(self, req, resp):
        self.insert_or_update(req, resp, None, """INSERT INTO events ( events_type, events_what, events_when, events_tags, events_geo) VALUES (%s, %s, tstzrange(%s,%s,%s) , %s, %s) ON CONFLICT DO NOTHING RETURNING events_id;""")

    def on_put(self, req, resp, id):
        # PUT is acting like PATCH
        event.on_patch(req, resp, id)

    def on_patch(self, req, resp, id):
        # coalesce are used to PATCH the data (new value may be NULL to keep the old one)
        self.insert_or_update(req, resp, id, """UPDATE events SET ( events_type, events_what, events_when, events_tags, events_geo) = (coalesce(%s, events_type), coalesce(%s, events_what), tstzrange(coalesce(%s, lower(events_when)),coalesce(%s, upper(events_when)),%s) , events_tags::jsonb || (%s::jsonb -'secret') , coalesce(%s, events_geo))
                              WHERE events_id = %s {secret} RETURNING events_id;""")

    def on_delete(self, req, resp, id):
        db = db_connect()
        cur = db.cursor()
        cur.execute("""INSERT INTO events_deleted SELECT events_id, createdate, lastupdate, events_type, events_what, events_when, events_geo, events_tags FROM events WHERE events_id = %s """, (id,));
        rows_insert = cur.rowcount

        # 'secret' based authentication, must be null or same as during POST
        if 'secret' in req.params:
            cur.execute("""DELETE FROM events WHERE events_id = %s AND (events_tags->>'secret' = %s OR events_tags->>'secret' IS NULL)""", (id,req.params['secret']));
        else:
            cur.execute("""DELETE FROM events WHERE events_id = %s AND events_tags->>'secret' IS NULL;""",(id,))
        if cur.rowcount==1:
            resp.status = "204 event deleted"
            db.commit()
        elif rows_insert==1: # INSERT ok but DELETE fails due to missing secret...
            resp.status = "403 Unauthorized, secret needed to delete this event"
            db.rollback()
        else:
            resp.status = "404 event not found"
        cur.close()
        db.close()


class EventSearch(BaseEvent):

    def on_post(self, req, resp):
        # body should contain a geojson Feature
        body = req.stream.read().decode('utf-8')
        j = json.loads(body)
        # pass the query with the geometry to event.on_get
        event.on_get(req, resp, None, j['geometry'])


# Falcon.API instances are callable WSGI apps.
app = falcon.API(middleware=[HeaderMiddleware()])

# Resources are represented by long-lived class instances
event = EventResource()
stats = StatsResource()
event_search = EventSearch()

# things will handle all requests to the matching URL path
app.add_route('/event/{id}', event)  # handle single event requests
app.add_route('/event', event)  # handle single event requests
app.add_route('/stats', stats)
app.add_route('/event/search', event_search)
