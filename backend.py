# backend.py
# openeventdatabase

import falcon
import psycopg2
import uuid

class StatsResource(object):
    def on_get(self, req, resp):
        db = psycopg2.connect("dbname=oedb")
        cur = db.cursor()
        cur.execute("SELECT count(*) from events;")
        stat = cur.fetchone()
        count_events = stat[0]
        cur.close()
        db.close()

        resp.body = """{"events_count":%s}""" % (count_events)
        resp.set_header('X-Powered-By', 'OpenEventDatabase')
        resp.set_header('Access-Control-Allow-Origin', '*')
        resp.set_header('Access-Control-Allow-Headers', 'X-Requested-With')
        resp.status = falcon.HTTP_200

# falcon.API instances are callable WSGI apps
app = falcon.API()

# Resources are represented by long-lived class instances
stats = StatsResource()

# things will handle all requests to the matching URL path
app.add_route('/stats', stats)

