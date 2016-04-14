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


SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE events (
    events_what text,
    events_where geometry,
    events_when timestamp with time zone,
    events_type text,
    events_tags json
);


--
-- Name: events_idx_what; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_what ON events USING spgist (events_what);


--
-- Name: events_idx_when; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_when ON events USING btree (events_when);


--
-- Name: events_idx_where; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_idx_where ON events USING gist (events_where);


--
-- Name: public; Type: ACL; Schema: -; Owner: -
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM postgres;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--

