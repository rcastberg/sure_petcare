# sure_petcare
Python library for accessing sure connect petflap

General instructions:
    * First use you need to generate the cache and authorization, e.g.:
	sp_cli.py --update -e <email_address> -p <password>
    * Subsequently: sp_cli.py --update

#Issues : 
Device id generation is currently taken from the mac address, we should proably find out how sure do it in their app.
Currently we update everything, possibly no point if we are only interested in one animal.

#Home assistant:
Moved to https://github.com/rcastberg/Sure_HomeAssistant
