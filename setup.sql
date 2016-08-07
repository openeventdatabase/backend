--
-- PostgreSQL database dump
--

-- Dumped from database version 9.5.3
-- Dumped by pg_dump version 9.5.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE events (
    events_id uuid DEFAULT uuid_generate_v4(),
    createdate timestamp without time zone DEFAULT now(),
    lastupdate timestamp without time zone,
    events_type text,
    events_what text,
    events_when tstzrange,
    events_geo text,
    events_tags jsonb
);


--
-- Name: geo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE geo (
    geom geometry(Geometry,4326),
    geom_center geometry(Point,4326),
    hash text,
    idx geometry
);


--
-- Name: geo_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY geo
    ADD CONSTRAINT geo_hash_key UNIQUE (hash);


--
-- Name: events_idx_antidup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX events_idx_antidup ON events USING btree (events_geo, events_what, events_when);


--
-- Name: events_idx_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX events_idx_id ON events USING btree (events_id);


--
-- Name: events_idx_lastupdate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_lastupdate ON events USING btree (lastupdate);


--
-- Name: events_idx_what; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_what ON events USING spgist (events_what);


--
-- Name: events_idx_when; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_when ON events USING spgist (events_when);


--
-- Name: geo_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_geom ON geo USING gist (geom);


--
-- Name: geo_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_idx ON geo USING gist (idx);


--
-- Name: events_lastupdate_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER events_lastupdate_trigger BEFORE INSERT OR UPDATE ON events FOR EACH ROW EXECUTE PROCEDURE events_lastupdate();


--
-- Name: geo_pk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY events
    ADD CONSTRAINT geo_pk FOREIGN KEY (events_geo) REFERENCES geo(hash);


--
-- PostgreSQL database dump complete
--
