#!/bin/bash

for f in grafana/provisioning/dashboards/*.json; do
    docker run -it --rm --name mdb -v "$PWD":/usr/src/myapp -w /usr/src/myapp python-paho python3 utils/manage_dashb.py -dbi $f -dbo $f -qf
done    
