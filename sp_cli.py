#!/usr/bin/env python3

import argparse
import os
import sys

import sure_petcare


def main(argv):
    description = """\
Sure Petcare Connect CLI

--- *WARNING* ---
    
This is not officially sanctioned software and may or may not violate the terms
of service.  Use this software and the API at your own risk!  Since the API on
which this is based is also unofficial and reverse engineered, there is no
guarantee that Sure won't change the API in a way to break this software.

*ON NO ACCOUNT* bother Sure customer support with questions about either this
tool or the API.  As excellent Sure's support team are, they don't know
anything about it and can't help you.  If you have a problem, file an Issue on
Github with the fork you got this from.

This CLI is supposed to be an EXAMPLE of how to use the API, not a substitute
for writing your own client to do the minimal amount of work.
    
-----------------

As with Sure's REST API, this API is under development and is not any more
guaranteed to maintain interface compatibility going forward.

Because use of this tool involves storing your account username and password in
cleartext, you might want to create a view-only user and add it to your
household.

General instructions:

    * First use: %(prog)s --update -e <email_address> -p <password>

    * Subsequently: %(prog)s --update

After update, you can use any of the following switches to query the status of
your pets, flap or household.  Note that --update is mutually exclusive with any
other option (other than --email or --pass)."""

    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-e", "--email", help="account email address")
    parser.add_argument("-p", "--pass", dest="pw", help="account password")
    parser.add_argument(
        "--update",
        action="store_true",
        help="update cache from Sure servers.  Mutually exclusive with commands/queries.",
    )
    parser.add_argument("-c", "--cache-file", help="Cache file to use if not default")
    parser.add_argument(
        "cmd", nargs="*", help="One of " + ", ".join(sorted(CMDS.keys()))
    )
    args = parser.parse_args()

    if args.update and args.cmd:
        exit("--update and commands/queries are mutually exclusive")

    if not args.update and not args.cmd:
        parser.print_help()
        exit()

    debug = os.environ.get("SPDEBUG") is not None
    sp = sure_petcare.SurePetFlap(
        email_address=args.email,
        password=args.pw,
        cache_file=args.cache_file,
        debug=debug,
    )

    if args.update:
        # Either update and write the cache, or...
        with sp:
            sp.update()
    else:
        # ... execute queries on cached data
        if args.cmd[0] in CMDS:
            CMDS[args.cmd[0]](sp, args)
        else:
            exit("Unknown command: %s" % (args.cmd[0],))


CMDS = {}


def cmd(f):
    if f.__name__.startswith("cmd_"):
        fn = f.__name__[4:]
        CMDS[fn] = f
    else:
        raise ValueError("bad use of @cmd decorator: %s" % (f.__name__,))
    return f


@cmd
def cmd_ls_house(sp, args):
    """
    List households
    """
    for hid, hdata in sp.households.items():
        default_flag = (hid == sp.default_household) and "(active)" or ""
        print("%s\t%s %s" % (hid, hdata["name"], default_flag))


@cmd
def cmd_ls_pets(sp, args):
    """
    For each pet in household, show location (inside, outside, unknown)
    """
    for pid, pdata in sp.pets.items():
        print("%s (%s) is %s" % (pdata["name"], pid, sp.get_current_status(pid)))


@cmd
def cmd_ls_flaps(sp, args):
    """
    For each pet in household, show location (inside, outside, unknown)
    """
    for flap_id, name in sp.household["flaps"].items():
        bat = sp.get_battery(flap_id=flap_id)
        lck = sp.lock_mode(flap_id)
        print("%s (%s) at %05.3fV is %s" % (name, flap_id, bat, lck))


@cmd
def cmd_pet_tl(sp, args):
    """
    For each pet in household, show location (inside, outside, unknown)
    """
    try:
        name = args.cmd[1]
    except IndexError:
        exit("need pet name (enclose in quotes if necessary)")

    sp.print_timeline(name=name)


@cmd
def cmd_set_hid(sp, args):
    """
    Set default household ID
    """
    try:
        hid = int(args.cmd[1])
    except (ValueError, IndexError):
        exit("need valid household ID")

    if hid in sp.households:
        with sp:
            sp.default_household = hid
            if sp.update_required:
                sp.update()
    else:
        exit("Household ID %s not known" % (hid,))


if __name__ == "__main__":
    main(sys.argv)
