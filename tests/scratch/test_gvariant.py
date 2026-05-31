import sys
def print_to_stderr(msg):
    sys.stderr.write(msg + '\n')

try:
    # Need to run a small command line to test GLib variants
    print_to_stderr("Test executed")
except Exception as e:
    print_to_stderr(str(e))
