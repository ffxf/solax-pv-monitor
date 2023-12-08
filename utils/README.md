# Solax PV Monitor Utilities

## Dashboard Management Utility

### Description

Simple utility to manipulate Solax PV Monitor dashboards if they are modified from within Grafana
and then exported. Assumes that exporting is done as a JSON file and with "export externally"
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

### Typical Workflow

The typical workflow is as follows

1. Export a modified dashboard from Grafana using the "Export for sharing externally" option and save it to file
2. Extract a mapping file for the variables used in the dashboard. Use the `-dbi`, `-mapfo` and `-cm` option for this
3. Modify the mapping file as needed, e.g., translate the text labels into another languate
4. Create a new dashboard file using the mapping file. Use the `-dbi`, `-dbo`, `-mapfi`, and `-wd` for this
5. Fix the datasource definitions in the dashboard file that just got created. There is an issue preventing files to get provisioned directly if not doing this. Use the `-dbi`, `-dbo`, and `-fd` options for it

If you not intended to do text label translations or other changes then you can skip steps 2 - 4.

It is possible to use the same name for dashbaord file input and output name (options `-dbi` and
`-dbo`), thus overwritting the file.

## Set Query Frequency Script

This script sets the value for the `QueryFrequency` variable in the dashboards configuration files
(the JSON files in `grafana/provisioning/dashboards`). **It should only be used during initial
installation and if the `QUERY_FREQUENCY` parameter in the `.client_env` file has been modified.** 

The query frequency, i.e. the rate at which Solax monitoring data is reported to the Influx
database, should always be the same and it has to be in sync with some of the query calaculations
in the dashboards. Changing it later would render "old" metrics having been collected with the previous frequency and new metrics with the changed one. The calculations for the previous
metric reports will then be wrong if the dashboards got updated too or they will be wrong for newer
reports if dashbaords didn't get updated.

If changing the frequency, then just run the script as follows:

```bash
utilities/set_query_freq.sh
```

The script will use the [Dashboard Management Utility](#user-content-dasboard-management-utility), i.e. the
script `utilities/manage_dashb.py` with it's `--query-freq` (`-qf`) option. It will loop through
any dashbaord files in `grafana/provisioning/dashboards` and change each of them using what has
been configured for `QUERY_FREQUENCY` in `.client_env` (so be sure to set this to the correct
value before you run the script).

## Backup and Restore Script

### Description

The `bkup-rest.sh` bash script allows to backup monitoring bucket data from the influxdb container and restore it later. The main intention is to support upgrades of the stack.

Just run `./bkup-rest.sh` to see usage information.

### Workflow

The suggested worflow to upgrade the stack with the help of this script is as follows:

1. Run `./bkup-rest.sh backup`. It will print where it has stored the backup
2. Shutdown monitoring stack with `docker-compose down -v` (or without the `-v`, potentially, if you have made changes to users, keys, etc in influxdb or grafana, or you have added more buckets)
3. Update the stack, e.g. do a `git pull`
4. Startup the stack via `docker-compose up -d`
5. Restore data from the backup via `./bkup-rest.sh restore <backup_dir>` with `<backup_dir>` being what has been printed in step #1
