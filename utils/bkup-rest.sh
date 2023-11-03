#!/bin/sh

# Little tool to store a backup of our monitoring bucket from influxdb containers and to restore
# them if needed. 
#
# Mostly intended to be used when upgrading the monitoring stack.
#
# See the last line for usage information

BKUP_BASE=/root
BKUP_DIR=${2:-backup_$(date '+%Y-%m-%d_%H-%M')}
BKUP_PATH=${BKUP_BASE}/${BKUP_DIR}

TOKEN=$(grep TOKEN .env | cut -d = -f 2)
BUCKET=$(grep BUCKET .env | cut -d = -f 2)
ORG=$(grep ORG .env | cut -d = -f 2)

get_container_id() {
    docker ps | grep influx | cut -f 1 -d " "
}

back_up_influx() {
    # Backup our bucket and copy the backup from the container to our local disk
    CONT=$(get_container_id)
    docker exec -it $CONT influx backup --bucket $BUCKET $BKUP_PATH -t $TOKEN
    if [ $? = 0 ]; then
        echo "Backup created in ${BKUP_PATH}."
        docker cp ${CONT}:${BKUP_PATH} .
        if [ $? = 0 ]; then
            echo "Copied backup to ${BKUP_DIR} in $(pwd)."
        fi
    fi
}


restore_influx() {
    # Remove our monitoring bucket from influx in the container (so we can restore previous
    # contents), copy the backup files into the container and then restore data
    CONT=$(get_container_id)
    ORG_ID=$(docker exec -it $CONT influx org list | grep $ORG | cut -f 1)
    docker exec -it $CONT influx bucket delete -n $BUCKET -o $ORG
    docker cp $BKUP_DIR ${CONT}:${BKUP_BASE}
    docker exec -it $CONT influx restore --bucket $BUCKET $BKUP_PATH
    if [ $? = 0 ]; then
        echo "Restored backup."
    fi
}

if [ "$1" = "backup" ]; then
    back_up_influx && exit 0
    exit 1
fi


if [ "$1" = "restore" ]; then
    restore_influx && exit 0
    exit 1
fi

echo "Usage: $0 { backup | restore } [ backup_dir ]"
