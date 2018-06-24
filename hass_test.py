#!/usr/bin/env python3

# "Unit test" for Home Assistent component.  Doesn't actually test anything,
# just instantiates the component and then prints what will be passed along
# to Home Assistant.
#
# ** IMPORTANT **
#
# If the following parameters are not changed, it will use the default cache
# file which *MUST* be initialised with credentials.  If this has not been
# created by other means, either modify `user` and `pw` as appropriate OR
# create a cache file using the CLI tool:
#
#       sp-cli.py -e user@domain.com -p SECRET --update
#
# If using a non-default cache file:
#
#       sp-cli.py -c /path/to/cache-file -e user@domain.com -p SECRET --update

user = None
pw = None
cache_file = None

import home_assistant.sure_petflap as Dut

from pprint import pprint
import json

dut = Dut.SurePetConnect( user, pw, debug = True, cache_file = cache_file )


print( '--- state (decoded JSON):' )
pprint( json.loads( dut.state ) )

print( '\n--- state attributes:' )
pprint( dut.state_attributes )
