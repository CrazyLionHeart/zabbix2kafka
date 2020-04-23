#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the MIT license.

from os import getenv
import json
import logging
import sys

from datetime import datetime

from kafka import KafkaProducer, KafkaConsumer, TopicPartition
from kafka.errors import KafkaError

from pyzabbix.api import ZabbixAPI

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client


kafka_endpoint = getenv("KAFKA_BROKERS")
kafka_topic = getenv("KAFKA_TOPIC")
client_id = getenv("HOSTNAME")
zabbix_host = getenv("ZBX_HOST")
zabbix_login = getenv("ZBX_USER")
zabbix_passwd = getenv("ZBX_PASSWD")


def config_logging():
    """Logger configurator

    Set up logging format and output

    Returns:
        logging: Configured logger
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s] %(funcName)s:%(lineno)d | %(message)s")

    if root_logger.getEffectiveLevel() == logging.DEBUG:
        http_client.HTTPConnection.debuglevel = 1
    else:
        http_client.HTTPConnection.debuglevel = 0

    zabbix_handler = logging.StreamHandler(sys.stdout)
    zabbix_handler.setFormatter(formatter)
    root_logger.addHandler(zabbix_handler)
    return root_logger

def to_timestamp(time, multiper=None):
    if multiper:
        return datetime.fromtimestamp(time/multiper)
    else:
        return datetime.fromtimestamp(time)

def get_latest_timestamp(kafka_topic):
    latest_timestamp = to_timestamp(0)

    consumer = KafkaConsumer(kafka_topic,
                             api_version=(1, 0, 0),
                             value_deserializer=lambda m: json.loads(
                                 m.decode('utf-8')),
                             bootstrap_servers=bootstrap_servers)

    topic_partition = TopicPartition(topic=kafka_topic, partition=0)
    end_offset = consumer.end_offsets([topic_partition])[topic_partition]

    if end_offset > 0:
        # partition  assigned after poll, and we could seek
        consumer.poll(5, 1)
        consumer.seek(topic_partition, end_offset - 1)
        message = consumer.poll(10000, 500)
        msgs = message[topic_partition]

        if len(msgs) > 0:
            record = msgs[-1]
            latest_timestamp = to_timestamp(record.timestamp, 1000.0)
    return latest_timestamp


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


if __name__ == "__main__":

    log = config_logging()

    if kafka_endpoint:
        bootstrap_servers = kafka_endpoint.split(',')
        producer = KafkaProducer(bootstrap_servers=bootstrap_servers,
                                 client_id=client_id,
                                 retries=-1,
                                 acks=1,
                                 api_version=(1, 0, 0),
                                 compression_type='lz4',
                                 value_serializer=lambda m: json.dumps(
                                     m).encode('utf-8')
                                 )
    else:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    if not kafka_topic:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    # Block for 'synchronous' sends
    try:
        zapi = ZabbixAPI(url="%s/api_jsonrpc.php" % zabbix_host,
                         user=zabbix_login, password=zabbix_passwd)
        log.info("Zabbix API version: " + str(zapi.api_version()))

        latest_timestamp = get_latest_timestamp(kafka_topic)

        log.info("Latest timestamp from kafka: %s" % latest_timestamp)

        # Get all monitored hosts
        hosts = zapi.host.get(monitored_hosts=1, output='extend')

        hosts_chunked = chunks(hosts, 10)

        items = []

        for hosts_chunk in hosts_chunked:
            h_ids = list(h['hostid'] for h in hosts_chunk)
            output = ["itemid", "hostid", "lastvalue", "lastclock", "name",
                      "value_type", "key_"]

            zbx_filter = {
                          # "value_type": [0, 3],
                          # "key_": download_items_keys,
                          # "name": download_items_names
                          }

            items += zapi.item.get({"hostids": h_ids, "monitored": True,
                                    "output": output, "filter": zbx_filter})

        # send only updated metric values
        filtered_items = filter(lambda item:
                                to_timestamp(int(item['lastclock'])) >= latest_timestamp,
                                items
                                )
        sended = 0
        for item in filtered_items:
            log.debug(item)
            producer.send(kafka_topic, item)
            sended += 1

        # # block until all async messages are sent
        producer.flush()

        log.info("Pushed %s metrics" % sended)

    except KafkaError:
        # Decide what to do if produce request failed...
        log.exception()
        pass
