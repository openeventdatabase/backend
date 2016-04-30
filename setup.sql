--
-- PostgreSQL database dump
--

-- Dumped from database version 9.5.2
-- Dumped by pg_dump version 9.5.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry, geography, and raster spatial types and functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


SET search_path = public, pg_catalog;

--
-- Name: wgs84_lat; Type: DOMAIN; Schema: public; Owner: -
--

CREATE DOMAIN wgs84_lat AS double precision
	CONSTRAINT wgs84_lat_check CHECK (((VALUE >= ('-90'::integer)::double precision) AND (VALUE <= (90)::double precision)));


--
-- Name: wgs84_lon; Type: DOMAIN; Schema: public; Owner: -
--

CREATE DOMAIN wgs84_lon AS double precision
	CONSTRAINT wgs84_lon_check CHECK (((VALUE >= ('-180'::integer)::double precision) AND (VALUE <= (180)::double precision)));


--
-- Name: events_lastupdate(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION events_lastupdate() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN NEW.lastupdate = now(); RETURN NEW; END; $$;


SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE events (
    events_what text,
    events_when timestamp with time zone,
    events_type text,
    events_tags json,
    events_id uuid DEFAULT uuid_generate_v4(),
    createdate timestamp without time zone DEFAULT now(),
    lastupdate timestamp without time zone,
    events_geo text
);


--
-- Name: geo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE geo (
    insee character varying(80),
    nom character varying(80),
    geom geometry(Geometry,4326),
    hash text
);


--
-- Name: geo_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY geo
    ADD CONSTRAINT geo_hash_key UNIQUE (hash);


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

CREATE INDEX events_idx_when ON events USING btree (events_when);


--
-- Name: geo_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_geom ON geo USING gist (geom);


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

