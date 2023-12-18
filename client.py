#!/usr/bin/env python3

# Solax PV system monitoring client.
# Reads from the Solax API (to use, log into solaxcloud,com and go to 'Service' ('Dienst' in German) 
# and get your API token from there and configure it in the client env file, default .client_env).

# Pushes stats to an mqtt broker (the idea is to get the stats injected into a tig-stack, i.e.
# from the mqtt borker to telegraf to influxdb and then to grafana for dashboarding)
#
# To test, run with
# docker run -it --rm --name cl -v "$PWD":/usr/src/myapp -v "$PWD":/solar -e CLIENT_TEST=1 -w /usr/src/myapp python-paho python3 client.py

from random import randint
from requests import get as req_get, exceptions as req_exceptions
from time import sleep
from datetime import datetime
from pprint import pprint
from json import load as json_load, dump as json_dump
from shutil import move
from tempfile import mktemp
from tomllib import load as toml_load
from os import getenv
from os import remove as file_remove
from os.path import isfile
from paho.mqtt import client as mqtt_client
from math import ceil

# Generate a Client ID with the publish prefix to register with the mqtt broker
client_id = f'publish-{randint(0, 1000)}'

# Settings file
env_file = ".client-env"
# File for mapping inverter serial no's and power lines to names, e.g. <inverter_sn> and 'powerdc1' to 'south'
inverter_line_file = ".inverter_line_map"

# File indicating that a checkpoint for 'to_grid_midnight' data should be done. If file exists a
# checkpoint will be done and the file will get removed again.
# This will typically be done before you shutown the client to have the previous data upon restart
ckpt_file = "do_client_ckpt"

# Get the map of inverter lines to metric names from file. The files has the syntax
#     <inverter_sn>:<line>:<metric name>
# e.g.
#     SYABCDEFG:powerdc1:south
# with each line in the file corresponding to an inverter line.
#
# Returns a dict of the form:
#     { '<inverter_sn>/<line>' : <metric name>, ... }
def parse_inverter_line_file(inverter_line_file):
    map = {}
    with open(inverter_line_file) as myfile:
        for line in myfile:
            inverter, power_line, name = tuple(line[:-1].split(":"))
            map[inverter + '/' + power_line] = name

    return map

# REST get request. Used to query the Solax API
def make_get_request(url, params=None, headers=None):
    try:
        response = req_get(url, params=params, headers=headers)
        response.raise_for_status()  # Raises an exception if the request was not successful (status code >= 400)

        # Assuming the response contains JSON data, we will parse it into a dictionary
        response_json = response.json()

        return response_json

    except req_exceptions.RequestException as e:
        print("Error making the POST request:", e)
        return None

# Class for backing up state of the metrics collection. Allows to shutdown the collection while
# maintaining reasonable values for daily metrics that get reset over midnight. Such metrics are
# the only state we need to preserve in the metrics collection. Other state is managed by the
# Solax API.
class Backup:
    def __init__(self, fname='backup.json'):
        self.fname = fname

    def save_backup(self, data):
        temp_filename = mktemp()

        try:
            with open(temp_filename, 'w') as temp_file:
                json_dump(data, temp_file)

            move(temp_filename, self.fname)
            # print(f"Data saved to '{self.fname}'")
        except Exception as e:
            print(f"Error while saving data: {str(e)}")

    def load_backup(self):
        try:
            with open(self.fname, 'r') as file:
                loaded_data = json_load(file)
            return loaded_data
        except FileNotFoundError:
            print(f"File '{self.fname}' not found. Returning an empty dictionary.")
            return {}

# Class to push metrics to the mqtt broker. Tested to work with mosquitto.
class Mqtt:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.client = None

    def connect_mqtt(self):
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print("Connected to MQTT Broker!")
            else:
                print("Failed to connect, return code %d\n", rc)

        self.client = mqtt_client.Client(client_id)
        # client.username_pw_set(username, password)
        self.client.on_connect = on_connect
        self.client.connect(self.host,self.port)

    def publish(self, topic, metric, value):
        msg = f"telegraf_message {metric}={value}"
        result = self.client.publish(topic, msg)
        # result: [0, 1]
        status = result[0]
        if status == 0:
            # print(f"Sent `{msg}` to topic `{topic}`")
            pass
        else:
            print(f"Failed to send message to topic {topic}")

# Class to act a metrics data container and for printing and publishing the metrics
class Stats:
    # Initializing the list of stats we currently collect
    def __init__(self):
        self.sol_pwr = 0.0          # Current total PV yield (compiled from inverter line yields)
        self.yield_total = 0.0      # Total PV yield since system went live
        self.yield_today = 0.0      # Daily PV yield
        self.to_grid = 0.0          # If >0 current power feed to grid, if <0 power taken from grid
        self.to_grid_today = 0.0    # Total power fed to grid today
        self.to_grid_total = 0.0    # Total power fed to grid since system went live
        self.from_grid = 0.0        # Supposedly power from grid but doesn't seem to work
                                    # (self.to_grid if < 0 gives us this instead)
        self.bat_soc = 0            # Current battery state of charge
        self.ac_power = 0.0         # Current AC power delivered by inverters aggregated
        self.to_bat = 0.0           # Current power feed to batteries
        self.to_house = 0.0         # Current power feed to house
        self.to_wallbox = 0.0       # Current power feed to wallbox (doesn't work at this point)

    def show(self):
        pprint(self.__dict__,sort_dicts=True)

    # We publish all class variables
    # Params:
    #   :f:     function used for publishing
    def publish(self, f):
        for k,v in self.__dict__.items():
            f(k, v)

# Class to query the Solax rest API, do any metrics data manipulation and trigger publishing the
# data to the mqtt broker
class Solax:
    def __init__(self, env, mqtt, test):
        # Params:
        #   :env:   The parsed contents of the client environment file
        #   :mqtt:  The mqtt broker to talk to
        #   :test:  Using the app in test mode (True) or not

        # The 'settings' section in the client env file
        self.settings = env['settings']
        # The 'inverter_types' section in the lient env file
        self.inverter_types = env['inverter_types']
        # The 'inverter_codes' section in the lient env file
        self.inverter_codes = env['inverter_codes']
        # The 'inverter_sns' section in the lient env file
        self.inverter_sns = env['inverter_sns']
        # The map between inverter lines and metric names
        self.inverter_map = parse_inverter_line_file(inverter_line_file)
        self.mqtt = mqtt
        self.test = test

        # Settings needed for midnight rollover of daily metrics and back-ups done to prevent
        # loosing state on those metrics
        self.to_grid_midnight = 0.0
        self.midnight_update_done = False
        self.bkup = Backup(self.settings['BACKUP_FILE'])

        # Used to store info per inverter as returned from API
        self.inverters = {}

    # Main loop over inverters doing all metrics manipulations and publishing of metrics in each run
    def loop_over_inverters(self):

        # Default API request attributes
        headers = {'Content-Type': 'application/json'}
        params = None

        while True:
            # Reset metrics for this run
            self.stats = Stats()

            # Iterate over inverter serial numbers, get metric data from each and parse the data
            for sn_name, sn in self.inverter_sns.items():
                params = {'tokenId': self.settings['TOKEN'], 'sn': sn}
                result_dict = make_get_request(self.settings['URL'], params=params, headers=headers)

                if result_dict is not None:
                    if self.test:
                        print(result_dict)
                    if 'result' in result_dict and \
                        'inverterType' in result_dict['result'] and 'inverterStatus' in result_dict['result']:
                        # Parse and compile data and store metric values in self.stats
                        self.parse_api_data(result_dict['result'], sn)
                else:
                    print("GET request failed.")

            # Power to grid today is not something delivered by the API. The function tries to
            # compile it
            self.set_to_grid_today()

            # Trying to compile power delivered to wallbox. Doesn't work the way it is done here,
            # unfortunately. The Solax app has this information and seems to get it from the
            # wallbox directly but there doesn't seem to be an API for that
            self.stats.to_house = self.stats.ac_power - self.stats.to_grid
            self.stats.to_wallbox = self.stats.sol_pwr - self.stats.to_bat - self.stats.to_house
            if self.stats.to_wallbox < 0.0:
                self.stats.to_wallbox = 0.0

            if self.test:
                self.stats.show()
            else:
                # Publish the metrics data to the mqtt broker
                self.stats.publish(lambda k, v: self.mqtt.publish(self.settings['TOPIC'], k, v))

            sleep(self.settings['QUERY_FREQUENCY'])

    # Parses the data we get from the Solax API, compiles some derived matrics and stores the data
    # in self.stats
    #
    # Parameters
    #   :res:   the results from an API query for a given inverter
    #   :sn:    the inverter serial number
    def parse_api_data(self, res, sn):
        # The inverter types and their status
        self.inverters[sn] = {
            'type': self.inverter_types[str(res['inverterType'])],
            'status': self.inverter_codes[str(res['inverterStatus'])]
        }

        # The below metrics are delivered directly through the API but only per inverter. So need
        # to sum them up over consequtive call of this function
        self.stats.yield_total += float(res['yieldtotal'])
        self.stats.yield_today += float(res['yieldtoday'])
        self.stats.to_grid_total += float(res['feedinenergy'])
        self.stats.to_grid += float(res['feedinpower'])
        self.stats.from_grid += float(res['consumeenergy'])
        self.stats.ac_power += float(res['acpower'])
        to_bat = res['batPower']
        if to_bat is not None:
            self.stats.to_bat += float(to_bat)
        bat = res['soc']
        if bat is not None:
            self.stats.bat_soc += bat

        # The current PV yield is a bit more complicated because each inverter can have multiple
        # lines connecting it to different PV panel areas. So need to aggregate all this but we
        # also want to retain the power delivered per line so we can report on that separately
        lines = [ k for k in res.keys() if k.startswith('powerdc')]
        for line in lines:
            p = res[line]
            if p is not None:
                # Aggregate line yield into total PV power metric
                self.stats.sol_pwr += float(p)

                # Determine metric name map for inverter line and publish the metric under that
                # name seperately
                k = sn + '/' + line
                if k in self.inverter_map:
                    if self.test:
                        print(self.inverter_map[k] + ' :', p)
                    else:
                        self.mqtt.publish(self.settings['TOPIC'], self.inverter_map[k], p)
                else:
                    print(f'{k} not found in inverter map {self.inverter_map}')

    # Determine a daily grid feed metric which is not part of the data delivered via the Solax API
    def set_to_grid_today(self):
        # We need to roll over at midnight while we aren't sure when we run exactly. The time the
        # main loop sleeps is configurable and we might be off by an arbitrary amound of seconds
        # from full minutes

        now = datetime.now()
        today = now.isocalendar()

        # list with the first few minutes (after midnight) during which we check whether to
        # initialize the daily grid yield metric. check_period contains a list such as [0, 1] or
        # [0, 1, 2] enumberating the minutes after midnight during which we run this check. This
        # is computed from the main look sleep time, i.e. the query frequency
        check_period = list(range(ceil(self.settings['QUERY_FREQUENCY']/60)+1))

        if now.hour == 0 and now.minute in check_period and not self.midnight_update_done:
            # We are within the check period and the update hasn't been done yet ==>
            # Set a midnight metric to the current grid delivery total and store a back-up if it
            # in case metrics collection gets restarted at some point. We'll use the midnight
            # metric to compute the daily delivery later
            self.to_grid_midnight = self.stats.to_grid_total
            persisted_data = { 'to_grid_midnight' : self.to_grid_midnight, 'date': today }
            self.bkup.save_backup(persisted_data)
            self.midnight_update_done = True
            print('Persisted data at midnight:', persisted_data)

        if self.to_grid_midnight == 0.0 or (self.stats.to_grid_total - self.to_grid_midnight) > self.stats.yield_today:
            # Trying to do something reasonable in failure cases. self.to_grid_midnight should
            # only be 0 when we (re)start metrics collection and what we have fed to the grid today
            # (self.stats.to_grid_total - self.to_grid_midnight)) should never be more than what
            # we have as PV yield today.

            # In such a case try to load data from backup first
            persisted_data = self.bkup.load_backup()
            if 'date' in persisted_data and today != tuple(persisted_data['date']):
                # Didn't backup today yet, so 'to_grid_midnight' in backup would not be valid for
                # today
                persisted_data = {}
            if 'to_grid_midnight' in persisted_data and \
               (self.stats.to_grid_total - persisted_data['to_grid_midnight']) <= self.stats.yield_today:
                # Seems we've got OK data from the backup so let's use it
                self.to_grid_midnight = persisted_data['to_grid_midnight']
                print('to_grid_midnight set because its 0 and we got it from the backup:', self.to_grid_midnight)
            else:
                # we either have no persisted data or to_grid_midnight is obviously wrong, so set
                # it such that to_grid_today will result in the maximum possible, which is the PV
                # yield today
                self.to_grid_midnight = self.stats.to_grid_total - self.stats.yield_today
                persisted_data = { 'to_grid_midnight' : self.to_grid_midnight, 'date': today }
                self.bkup.save_backup(persisted_data)
                print('Resetting persisted data because it doesnt seem correct:', persisted_data)

        # Now we can set the 'to_grid_today' metric
        self.stats.to_grid_today = min(self.stats.to_grid_total - self.to_grid_midnight, self.stats.yield_today)

        # The period (i.e. the minutes) after the check period
        after_check = [check_period[-1]+i+1 for i in check_period]
        # Reset self.midnight_update_done
        if now.hour == 0 and now.minute in after_check and self.midnight_update_done:
            self.midnight_update_done = False
        
        if isfile(ckpt_file):
            persisted_data = { 'to_grid_midnight' : self.to_grid_midnight, 'date': today }
            self.bkup.save_backup(persisted_data)
            print('Data checkpointed on demand:', persisted_data)
            try:
                file_remove(ckpt_file)
            except:
                pass

        
# Main function
def run():
    if getenv("CLIENT_TEST") == '1':
        test = True
    else:
        test = False

    # Read .client_env file (contains sections for settings and inverter definitions)
    with open(env_file, "rb") as f:
        env = toml_load(f)

    # Initialize mqtt connection
    if test:
        mqtt = None
    else:
        mqtt = Mqtt(env['settings']['BROKER_HOST'], env['settings']['BROKER_PORT'])
        mqtt.connect_mqtt()
        mqtt.client.loop_start()

    # Collect and publish metrics in a loop
    solax = Solax(env, mqtt, test)
    solax.loop_over_inverters()

    if not test:
        mqtt.client.loop_stop()


if __name__ == '__main__':
    run()
