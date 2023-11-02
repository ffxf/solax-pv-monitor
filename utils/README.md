# Solax PV Monitor Dashboard Management Utility

Simple utility to manipulate Solax PV Montiro dashboards if they are modified from within Grafana
and then exported. Assumes that exporting is donw as a JSON file and with "export externally"
turned on.

The utility allows to do the following things:

* Extract the variables defining text labels (e.g., panel titles) into a toml formatted file.
  Changing the text definitions in such a file can then be used to create different language
  mappings for dashboards
* Use such a map to modify the variable text definitions in JSON dashboard file and write the
  modified content into a new file
* Fix the InfluxDB datasource uid definitions in the dashboard JSON file to comply with what the
  Solax PV Monitor framework expects

Invoke directly with Python 3.9 or higher installed or use

```bash 
docker run -it --rm --name mdb -v "$PWD":/usr/src/myapp -w /usr/src/myapp python-paho python3 manage_dashb.py
```

Supply the `-h` or `--help` option to see usage information.
