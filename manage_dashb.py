#!/usr/bin/env python3

# run with
# docker run -it --rm --name mdb -v "$PWD":/usr/src/myapp -w /usr/src/myapp python-paho python3 manage_dashb.py
#
# A little helper tool to support various languages in the dashboard.
# Allows to extract visible text label variables from a dashboad json file with their current text label
# settings and put this into a file in toml format.
# After modyfing such a toml label mapping file, i.e. translating the text labels, you can use this
# tool to automatically modify the dashboard json file to represent the desired language. You can
# then import it into Grafana to get a dashboard with the desired language support.
#
# Use the --help / -h option for usage information

from tempfile import mktemp
from json import load as json_load, dump as json_dump
from tomllib import load as toml_load
from argparse import ArgumentParser
from shutil import move

dashb_file = "dashboard.json"
map_file = "dashb_map.toml"


class LabelMap():
    # Class to handle the simple label map toml format
    # Provides a function to read a map via read_map() and create a label map from a JSON
    # dashboard file via get_map_from_dashboard()
    def __init__(self, inf=map_file, outf=map_file):
        self.inf = inf
        self.outf = outf

    def read_map(self):
        map = None
        with open(self.inf, "rb") as f:
            map = toml_load(f)
        return map

    def get_map_from_dashboard(self, dashboard):
        # Creates a map from a Grafana JSON dashboard. The function doesn't parse the complete
        # JSON file but focuses on variable definitions under 'templating'
        with open(self.outf, "a") as f:
            for rec in dashboard['templating']['list']:
                # Depending on the type of variable, there is either a 'label' attribute
                # containing the label test we are looking for or it is in a 'text' attribute
                # under the 'current' attribute
                if 'label' in rec:
                    txt = rec['label']
                elif 'text' in rec['current']:
                    txt = rec['current']['text']
                else:
                    print('Neither "label" nor "text" in templating record. Skipping ...')
                    continue
                # The 'name' attribute contains the name of the variable. So write this out in the
                # simple format
                # "<variable name>" = "<label test>"
                f.write(f"""\042{rec['name']}\042 = \042{txt}\042\n""")

class Dashboard():
    # Class to handle dashboard manipulations, in particular reading a dashbaord and writing it
    # while applying a remapping the labels of variables based on a label map
    def __init__(self, dashb_file=dashb_file):
        self.dashb_file = dashb_file

    def read_dashb(self):
        data = {}
        with open(self.dashb_file, "rb") as f:
            data = json_load(f)
        return data

    def write_dashb(self, map):
        dashboard = self.read_dashb()

        for rec in dashboard['templating']['list']:
            # Also here we need to handle the two types of variable which have the label either in
            # a 'label' attributed or under 'current/test', 'current/value', 'options[0]/text' and
            # 'options[0]/value'. In each we have to set our label text from the map
            nm = rec['name']
            if nm not in map:
                continue
            label = map[nm]
            if 'label' in rec:
                rec['label'] = label
            elif 'text' in rec['current']:
                rec['current']['text'] = label
                rec['current']['value'] = label
                rec['options'][0]['text'] = label
                rec['options'][0]['value'] = label
                rec['query'] = label
            else:
                print('Neither "label" nor "text" in templating record. Skipping ...')
                continue

        tempf = mktemp()
        with open(tempf, "w") as f:
            json_dump(dashboard, f, indent=4)

        move(tempf, self.dashb_file)




def get_args():
    # CLI arguments. Use the -h or --help option for usage

    parser = ArgumentParser(description="""
Allows to create Grafana dashboard variable label map files and use such files to modify dashboards, e.g. to change
the language of the labels.""", \
        epilog="Cannot create a map file and modify the dashboard in the same run. Execute twice with different options.")

    parser.add_argument("-dbi", "--dashb-in", help="Grafana dashboard file to use as input.", default=dashb_file)
    parser.add_argument("-dbo", "--dashb-out", \
        help="Grafana dashboard file to use as output. Gets overwritten if it exists.", default=dashb_file)
    parser.add_argument("-mapfi", "--map-file-in", help="Label map file.", default=map_file)
    parser.add_argument("-mapfo", "--map-file-out", \
        help="Label map output file. Gets overwritten if it exists.", default=map_file)
    parser.add_argument("-wd", "--write-dashb", help="Write dashboard file with mapped labels.", action="store_true")
    parser.add_argument("-rm", "--read-map", help="Read and create map file from dashboard.", action="store_true")

    args = parser.parse_args()

    if args.write_dashb and args.read_map:
        print("""
reating a map file from a dashboard and modifying that dashboard with the map file doesn't make sense. Quitting.""")
        exit(1)

    return args


    
def run():
    args = get_args()
    Map = LabelMap(inf=args.map_file_in, outf=args.map_file_out)

    if args.write_dashb:
        Dashb = Dashboard(dashb_file=args.dashb_out)
    else:
        Dashb = Dashboard(dashb_file=args.dashb_in)

    if args.read_map:
        Map.get_map_from_dashboard(Dashb.read_dashb())
        return

    if args.write_dashb:
        map = Map.read_map()
        Dashb.write_dashb(map)
        return

    print(" Need to specificy one of --write-dashb or --read-map. Quitting.")
    exit(1)

    return

if __name__ == '__main__':
    run()
