# Solax PV Monitor Client Container Definition

Contains the files to build the container that is used to run the Solax PV Monitor client program
that uses the Solax API and the Python *paho* module to feed data from Solax cloud into an mqtt
broker.

The container built with these files is availabel from github as `ff114084/python-paho` and is
referenced as such in the docker-compose manifest of the monitoring service. So there is no real
need to build this container. The files here are provided if there is a need to make changes.
