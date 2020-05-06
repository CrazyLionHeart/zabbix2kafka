#!/bin/bash

cleanup() {
    echo "Cleaning up..."
    rm -f /data/kafka-is-up
    exit
}

trap cleanup INT TERM HUP

# Launch Kafka
/etc/confluent/docker/run &
pid=$!

# Wait for Kafka to start and then create a file to 
# indicate that it's listening
echo "Waiting for Kafka to start listening on 9092 ⏳"
nc -vz localhost 9092
is_up=$?
while [ $is_up -ne 0 ] ; do 
    echo -e $(date) $(nc -z localhost 9092)
    nc -vz localhost 9092
    is_up=$?
    sleep 5 
done

echo "Kakfa is now listening! :-)"
touch /data/kafka-is-up
wait $pid