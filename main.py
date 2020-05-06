#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the MIT license.

from os import getenv, unsetenv
import json
import logging
import sys
import threading
from datetime import datetime
import pytz


from kafka import KafkaProducer, KafkaConsumer, TopicPartition
from kafka.errors import KafkaError

from pyzabbix.api import ZabbixAPI

import ssl

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client


def read_env(var, default=None):
    result = getenv(var, default)
    log.debug("Cleaning env %s", var)
    unsetenv(var)
    return result

class NullHandler(logging.Handler):
    def emit(self, record):
        pass


def config_logging():
    """Logger configurator

    Set up logging format and output

    Returns:
        logging: Configured logger
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s] %(name)s %(filename)s:%(funcName)s:%(lineno)d | %(message)s")

    # Enable debug HTTP request/response
    if root_logger.getEffectiveLevel() == logging.DEBUG:
        http_client.HTTPConnection.debuglevel = 1
    else:
        http_client.HTTPConnection.debuglevel = 0

    zabbix_handler = logging.StreamHandler(sys.stdout)
    zabbix_handler.setFormatter(formatter)
    root_logger.addHandler(zabbix_handler)
    return root_logger


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def transfer_data():

    def get_latest_timestamp(kafka_topic):
        latest_timestamp = 0

        topic_partition = TopicPartition(
            topic=kafka_topic,
            partition=0,
        )
        end_offset = consumer.end_offsets([topic_partition])[topic_partition]

        if end_offset > 0:
            # partition  assigned after poll, and we could seek
            consumer.poll(5, 1)
            consumer.seek(topic_partition, end_offset - 1)
            message = consumer.poll(10000, 500)
            msgs = message[topic_partition]

            if len(msgs) > 0:
                record = msgs[-1]
                latest_timestamp = record.timestamp/1000.0
        return latest_timestamp

    try:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            retries=-1,
            acks=1,
            request_timeout_ms=600000,
            api_version=(1, 0, 0),
            compression_type='lz4',
            security_protocol=security_protocol,
            ssl_context=ssl_context,
            ssl_check_hostname=ssl_check_hostname,
            ssl_cafile=ssl_cafile,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
            ssl_password=ssl_password,
            value_serializer=lambda m: json.dumps(
                m).encode('utf-8')
        )

        consumer = KafkaConsumer(
            kafka_topic,
            api_version=(1, 0, 0),
            value_deserializer=lambda m: json.loads(
                m.decode('utf-8')),
            session_timeout_ms=600000,
            security_protocol=security_protocol,
            ssl_context=ssl_context,
            ssl_check_hostname=ssl_check_hostname,
            ssl_cafile=ssl_cafile,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
            ssl_password=ssl_password,
            bootstrap_servers=bootstrap_servers)

        zapi = ZabbixAPI(
            url="%s/api_jsonrpc.php" % zabbix_host,
            user=zabbix_login,
            password=zabbix_passwd,
        )
        log.info("Zabbix API version: " + str(zapi.api_version()))

        latest_timestamp = get_latest_timestamp(kafka_topic)

        tz = pytz.timezone( 'Europe/Moscow' )

        log.info("Latest timestamp from kafka: %s" % datetime.fromtimestamp(latest_timestamp, tz=tz))

        # Get all monitored hosts
        hosts = zapi.host.get(
            monitored_hosts=1,
            selectGroups="extend",
            output=[
                "hostid",
                "groups",
                "name"]
        )

        hosts_chunked = chunks(hosts, 10)

        sended = 0

        for hosts_chunk in hosts_chunked:
            h_ids = list(h['hostid'] for h in hosts_chunk)

            items = zapi.item.get({
                "hostids": h_ids,
                "monitored": True,
                "output": [
                    "itemid",
                    "hostid",
                    "name",
                ],
            })

            items_chunked = chunks(items, 10)

            for items_chunk in items_chunked:

                i_ids = list(i['itemid'] for i in items_chunk)

                current_history = zapi.history.get(
                    history=0,
                    time_from=int(latest_timestamp),
                    # time_till=int(latest_timestamp + 60),
                    hostids=h_ids,
                    itemids=i_ids,
                    sortfield="clock",
                    sortorder="DESC",
                    output=["itemid", "value", "clock"]
                )

                log.debug(current_history)

                for h_item in current_history:
                    host_id = [h['hostid'] for h in items_chunk
                               if h['itemid'] == h_item['itemid']][-1]


                    groups_list = [h['groups'] for h in hosts_chunk
                                   if h['hostid'] == host_id]

                    groups = [g['name'] for g in groups_list[0]]

                    host_name = [h['name'] for h in hosts_chunk
                                 if h['hostid'] == host_id][-1]

                    item_name = [h['name'] for h in items_chunk
                                 if h['itemid'] == h_item['itemid']][-1]

                    result = {
                        "host_id": host_id,
                        "item_id": h_item['itemid'],
                        "value": h_item['value'],
                        "clock": h_item['clock'],
                        "metric_name": item_name,
                        "group": groups,
                        "host_name": host_name,
                        "zabbix_host": zabbix_host,
                        "zabbix_name": zabbix_name
                    }

                    log.debug(result)
                    producer.send(kafka_topic, result)
                    sended += 1

        log.info("Pushed %s metrics" % sended)
        log.info("Last item time: %s" % datetime.fromtimestamp(int(result['clock']), tz=tz))

    except KafkaError as ex:
        # Decide what to do if produce request failed...
        log.exception(ex)
    except Exception as ex:
        # Do not break the loop
        log.exception(ex)


if __name__ == "__main__":

    log = config_logging()

    kafka_endpoint = read_env("KAFKA_BROKERS")
    kafka_topic = read_env("KAFKA_TOPIC")
    client_id = read_env("HOSTNAME")
    zabbix_host = read_env("ZBX_HOST")
    zabbix_name = read_env("ZBX_LABEL")
    zabbix_login = read_env("ZBX_USER")
    zabbix_passwd = read_env("ZBX_PASSWD")
    WAIT_TIME_SECONDS = int(read_env("WAIT_TIME_SECONDS", 60))
    security_protocol=read_env("KAFKA_PROTOCOL", "PLAINTEXT")
    ssl_check_hostname=read_env("KAFKA_CHECK_HOSTNAME", False),
    ssl_cafile=read_env("KAFKA_SSL_CA")
    ssl_certfile=read_env("KAFKA_SSL_CERT")
    ssl_keyfile=read_env("KAFKA_SSL_KEY")
    ssl_password=read_env("KAFKA_SSL_PASSWD")
    ssl_context=ssl._create_unverified_context()

    if kafka_endpoint:
        bootstrap_servers = kafka_endpoint.split(',')
    else:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    if not kafka_topic:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    if not zabbix_name:
        raise Exception("Set ZBX_LABEL for Zabbix server identify")

    ticker = threading.Event()
    while not ticker.wait(WAIT_TIME_SECONDS):
        transfer_data()