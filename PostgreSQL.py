#!/usr/bin/env python

import re
import commands

PLUGIN_NAME = 'PostgreSQL with Replication'
CONFIG_PARAMS = [
    # ('config key', 'name', 'required'),
    ('postgres_database', 'PostgreSQLDatabase', True),
    ('postgres_user', 'PostgreSQLUser', True),
    ('postgres_pass', 'PostgreSQLPassword', False),
    ('postgres_host', 'PostgreSQLHost', True),
    ('postgres_port', 'PostgreSQLPort', False),
]
PLUGIN_STATS = [
    'postgresVersion',
    'postgresMaxConnections',
    'postgresCurrentConnections',
    'postgresConnectionsPercent',
    'postgresLocks',
    'postgresLogFile',
    'postgresConnectedSlaves',
    'postgresSlaveLag',
]

#===============================================================================
class PostgreSQL:
    #---------------------------------------------------------------------------
    def __init__(self, agent_config, checks_logger, raw_config):
        self.agent_config = agent_config
        self.checks_logger = checks_logger
        self.raw_config = raw_config

        # get config options
        if self.raw_config.get('PostgreSQL', False):
            for key, name, required in CONFIG_PARAMS:
                self.agent_config[name] = self.raw_config['PostgreSQL'].get(key, None)
        else:
            self.checks_logger.debug(
                '%s: Postgres config section missing ([PostgreSQL]' % PLUGIN_NAME
            )
                
        # reset plugin specific params
        for param in PLUGIN_STATS:
            setattr(self, param, None)

    #---------------------------------------------------------------------------
    def run(self):
        # make sure we have the necessary config params
        for key, name, required in CONFIG_PARAMS:
            if required and not self.agent_config.get(name, False):
                self.checks_logger.error(
                    '%s: config not complete (missing: %s) under PostgreSQL' % (
                        PLUGIN_NAME,
                        key
                    )
                )
                return False

        # plugin expects psycopg2 to be available
        try:
            import psycopg2
        except ImportError, e:
            self.checks_logger.error('%s: unable to import psycopg2' % PLUGIN_NAME)
            return False
        if not self.agent_config.get('PostgreSQLPort'):
            self.agent_config['PostgreSQLPort'] = 5432

        # connect
        try:
            db = psycopg2.connect(
                database=self.agent_config.get('PostgreSQLDatabase'),
                user=self.agent_config.get('PostgreSQLUser'),
                password=self.agent_config.get('PostgreSQLPassword'),
                port=self.agent_config.get('PostgreSQLPort'),
                host=self.agent_config.get('PostgreSQLHost')
            )
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: PostgreSQL connection error: %s' % (PLUGIN_NAME, e)
            )
            return False

        # get version
        if self.postgresVersion == None:
            try:
                cursor = db.cursor()
                cursor.execute('SELECT VERSION()')
                result = cursor.fetchone()
                self.postgresVersion = result[0].split(' ')[1]
            except psycopg2.OperationalError, e:
                self.checks_logger.error(
                    '%s: SQL query error when gettin version: %s' % (PLUGIN_NAME, e)
                )

        # get max connections
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT setting::INTEGER AS mc FROM pg_settings WHERE name = 'max_connections'"
            )
            self.postgresMaxConnections = cursor.fetchone()[0]
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: SQL query error when getting max connections: %s' % (PLUGIN_NAME, e)
            )
        try:
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(datid) FROM pg_database AS d LEFT JOIN pg_stat_activity AS s ON (s.datid = d.oid)")
            self.postgresCurrentConnections = cursor.fetchone()[0]
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: SQL query error when getting current connections: %s' % (PLUGIN_NAME, e)
            )

        if self.postgresMaxConnections and self.postgresCurrentConnections:
            self.postgresConnectionsPercent = (float(self.postgresCurrentConnections) / self.postgresMaxConnections) * 100

        # get locks
        try:
            self.postgresLocks = []
            cursor = db.cursor()
            cursor.execute("SELECT granted, mode, datname FROM pg_locks AS l JOIN pg_database d ON (d.oid = l.database)")
            for results in cursor.fetchall():
                self.postgresLocks.append(results)
        except psycopg2.OperationalError, e:
            self.checks_logger.error('%s: SQL query error when getting locks: %s' (PLUGIN_NAME, e))

        # get logfile info
        try:
            self.postgresLogFile = []
            cursor = db.cursor()
            cursor.execute("SELECT name, CASE WHEN length(setting)<1 THEN '?' ELSE setting END AS s FROM pg_settings WHERE name IN ('log_destination','log_directory','log_filename','redirect_stderr','syslog_facility') ORDER BY name;")
            for results in cursor.fetchall():
                self.postgresLogFile.append(results)
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: SQL query error when checking log file settings: %s' % (PLUGIN_NAME, e)
            )

        # get number of connected slaves, if we are a master
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT COUNT(pid) AS slave_count FROM pg_stat_replication;"
            )
            self.postgresConnectedSlaves = cursor.fetchone()[0]
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: SQL query error when getting connected slaves: %s' % (PLUGIN_NAME, e)
            )

        # get slave lag, if we are a slave
        try:
            cursor = db.cursor()
            # Used to be the following query
            # "SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))::INTEGER AS lag_seconds;"
            # but on servers that do not update regularly, the response can be misleading
            cursor.execute(
                """
                SELECT
                CASE WHEN pg_last_xlog_receive_location() = pg_last_xlog_replay_location()
                THEN 0
                ELSE EXTRACT (EPOCH FROM now() - pg_last_xact_replay_timestamp())::INTEGER
                END AS log_delay;
                """
            )
            self.postgresSlaveLag = cursor.fetchone()[0]
        except psycopg2.OperationalError, e:
            self.checks_logger.error(
                '%s: SQL query error when getting slave lag: %s' % (PLUGIN_NAME, e)
            )

        # return the stats
        stats = {}
        for param in PLUGIN_STATS:
            stats[param] = getattr(self, param, None)
        return stats

if __name__ == "__main__":
    # If you want to test this, update your config settings below
    import logging
    raw_config = {
        'PostgreSQL': {
            'postgres_database': 'template1',
            'postgres_user': 'postgres',
            'postgres_pass': '',
            'postgres_host': 'localhost',
            'postgres_port': '5432'
        }
    }
    postgres = PostgreSQL({}, logging.getLogger(''), raw_config)
    print postgres.run()
