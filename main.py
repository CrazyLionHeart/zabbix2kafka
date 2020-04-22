#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the MIT license.

from os import getenv
import json
import logging
import sys

from kafka import KafkaProducer, KafkaConsumer
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

    root_logger.setFormatter(formatter)

    if root_logger.getEffectiveLevel() == logging.DEBUG:
        http_client.HTTPConnection.debuglevel = 1
    else:
        http_client.HTTPConnection.debuglevel = 0

    zabbix_handler = logging.StreamHandler(sys.stdout)
    root_logger.addHandler(zabbix_handler)
    return root_logger


if __name__ == "__main__":

    log = config_logging()


    if kafka_endpoint:
        bootstrap_servers = kafka_endpoint.split(',')
        producer = KafkaProducer(bootstrap_servers=bootstrap_servers,
                                 client_id=client_id,
                                 retries=-1,
                                 acks=1,
                                 compression_type='lz4',
                                 value_serializer=lambda m: json.dumps(m).encode('utf-8')
                                 )
    else:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    if not kafka_topic:
        raise Exception(
            "Kafka brokers does not set KAFKA_BROKERS: %s" % kafka_endpoint)

    # Block for 'synchronous' sends
    try:
        zapi = ZabbixAPI(url="%s/api_jsonrpc.php" % zabbix_host, user=zabbix_login, password=zabbix_passwd)
        log.info("Zabbix API version: " + str(zapi.api_version()))

        producer.send(kafka_topic, {'key': 'value'})

        # block until all async messages are sent
        producer.flush()


        consumer = KafkaConsumer(kafka_topic,
                         group_id='my-group-1',
                         auto_offset_reset='earliest', 
                         enable_auto_commit=True,
                         consumer_timeout_ms=1000,
                         value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                         bootstrap_servers=bootstrap_servers)
        for message in consumer:
            # message value and key are raw bytes -- decode if necessary!
            # e.g., for unicode: `message.value.decode('utf-8')`
            log.info("%s:%d:%d: key=%s value=%s" % (message.topic, message.partition,
                                                  message.offset, message.key,
                                                  message.value))



    except KafkaError:
        # Decide what to do if produce request failed...
        log.exception()
        pass
