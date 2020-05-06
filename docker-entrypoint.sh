#!/usr/bin/dumb-init /bin/sh

set -e

# Note above that we run dumb-init as PID 1 in order to reap zombie processes
# as well as forward signals to all processes in its session. Normally, sh
# wouldn't do either of these functions so we'd leak zombies as well as do
# unclean termination of all our sub-processes.
# As of docker 1.13, using docker run --init achieves the same outcome.

echo "Waiting for flag that Kafka is up… ⏳"
until [ -f /data/kafka-is-up ]
do
    echo -e $(date) ": Waiting for flag that Kafka is up… ⏳"
    sleep 5
done

echo -e $(date) ": \o/ Got the flag that Kafka is up!"

exec "$@"