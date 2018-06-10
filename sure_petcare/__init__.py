#!/usr/bin/python3
"""
Access the sure petcare access information
"""

import json
import requests
from datetime import datetime, timedelta
import sure_petcare.utils as utils
from .utils import mk_enum

DIRECTION ={0:'Looked through',1:'Entered House',2:'Left House'}
INOUT_STATUS = {1 : 'Inside', 2 : 'Outside'}

# The following event types are known, eg EVT.CURFEW.
EVT = mk_enum( 'EVT',
               {'MOVE': 0,
                'MOVE_UID': 7, # movement of unknown animal
                'LOCK_ST': 6,
                'USR_IFO': 12,
                'USR_NEW': 17,
                'CURFEW': 20,
                } )

LK_MOD = mk_enum( 'LK_MOD',
                  {'UNLOCKED': 0,
                   'LOCKED_IN': 1,
                   'LOCKED_OUT': 2,
                   'LOCKED_ALL': 3,
                   'CURFEW': 4,
                   } )

PROD_ID = mk_enum( 'PROD_ID',
                   {'ROUTER': 1,
                    'FLAP': 3,
                    } )


# REST API endpoints (no trailing slash)
_URL_AUTH = 'https://app.api.surehub.io/api/auth/login'
_URL_HOUSEHOLD = 'https://app.api.surehub.io/api/household'
_URL_DEV = 'https://app.api.surehub.io/api/device'
_URL_TIMELINE = 'https://app.api.surehub.io/api/timeline'

API_USER_AGENT = 'Mozilla/5.0 (Linux; Android 7.0; SM-G930F Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/64.0.3282.137 Mobile Safari/537.36'


class SurePetFlapNetwork(object):
    """Class to take care of network communication with SurePet's products.

    Unless you want to parse data from Sure directly, instantiate SurePetFlap()
    rather than this class directly.  The constructor arguments are the same as
    below.
    """

    def __init__(self, email_address=None, password=None, device_id=None, pcache=None, tcache=None, debug=False):
        """`email_address` and `password` are self explanatory and are the only
        mandatory arguments.

        `device_id` is the ID of *this* client.  If none supplied, a plausible,
        unique-ish default is supplied.

        pcache and tcache are the persistent and transient object data caches
        preserved from a previous instance with which to initialise this
        instance.  While both are optional, you *should* always preserve the
        persistent cache if you can, and also the transient cache if your
        process itself is not long-lived.
        """
        if email_address is None or password is None:
            raise ValueError('Please provide, email, password and device id')
        self.debug=debug
        self.s = requests.session()
        if debug:
            self.s.hooks['response'].append( self._log_req )
        self.email_address = email_address
        self.password = password
        if device_id is None:
            self.device_id = utils.gen_device_id()
        else:
            self.device_id = device_id
        # The persistent object cache is for data that rarely or never change.
        # If at all possible, this *should* be preserved and passed to future
        # instances of this class.
        if pcache is None:
            self.pcache = {'AuthToken': None,
                           'households': None,
                           'default_household': None,
                           }
        else:
            self.pcache = pcache
        # The transient object cache is for data that change over the short
        # term.  You should preserve this, too, if your process is not
        # long-lived.
        if tcache is None:
            self.tcache = {}
        else:
            self.tcache = tcache
        self.flap_status = {} # indexed by household
        self.router_status = {} # indexed by household
        self.pet_status = {} # indexed by household
        self.house_timeline = {} # indexed by household
        self.curfew_lock_info = {} # indexed by household

    @property
    def default_household( self ):
        """
        Get the default house ID from the persistent cache.
        """
        return self.pcache['default_household']
    @default_household.setter
    def default_household( self, id ):
        """
        Set the default household in the persistent cache.
        """
        self.pcache['default_household'] = id

    def get_default_router( self, hid ):
        """
        Set the default router ID in the persistent cache.
        """
        return self.pcache['households'][hid]['default_router']
    def set_default_router( self, hid, rid ):
        """
        Get the default router ID from the persistent cache.
        """
        self.pcache['households'][hid]['default_router'] = rid

    def get_default_flap( self, hid ):
        """
        Get the default flap ID from the persistent cache.
        """
        return self.pcache['households'][hid]['default_flap']
    def set_default_flap( self, hid, fid ):
        """
        Set the default flap ID in the persistent cache.
        """
        self.pcache['households'][hid]['default_flap'] = fid

    def get_households( self ):
        """
        Return dict of households which include name and timezone information
        suitable for use with pytz.
        """
        return self.pcache['households']

    def get_pets( self, hid = None ):
        """
        Return dict of pets.
        """
        hid = hid or self.default_household
        return self.pcache['households'][hid]['pets']

    def update(self):
        """
        Update everything.  MUST be invoked immediately after instance creation.
        """
        self.update_authtoken()
        self.update_households()
        self.update_device_ids()
        self.update_pet_info()
        self.update_pet_status()
        self.update_flap_status()
        #self.update_router_status()
        # XXX For now, router status contains little of interest and isn't worth
        #     the API call.
        self.update_house_timeline()

    def update_authtoken(self, force = False):
        """
        Update persistent cache with authentication token if missing.
        Use `force = True` when the token expires (the API generally does this
        automatically).
        """
        if self.pcache['AuthToken'] is not None and not force:
            return
        data = {"email_address": self.email_address,
                "password": self.password,
                "device_id": self.device_id,
                }
        headers=self._create_header()
        response = self.s.post(_URL_AUTH, headers=headers, json=data)
        if response.status_code == 401:
            raise SPAPIAuthError()
        response_data = response.json()
        self.pcache['AuthToken'] = response_data['data']['token']

    def update_households(self, force = False):
        """
        Update persistent cache with info about the household(s) associated with
        the account.
        """
        if self.pcache['households'] is not None and not force:
            return
        params = ( # XXX Could we merge update_households() with update_pet_info()?
            ('with[]', ['household', 'timezone',],), #'pet',
        )
        headers=self._create_header()
        response_household = self._api_get(_URL_HOUSEHOLD, headers=headers, params=params)
        response_household = response_household.json()
        self.pcache['households'] = {
            x['id']: {'name': x['name'],
                      'olson_tz': x['timezone']['timezone'],
                      'utc_offset':  x['timezone']['utc_offset'],
                      'default_router': None,
                      'default_flap': None,
                      } for x in response_household['data']
            }
        self.default_household = response_household['data'][0]['id']

    def update_device_ids(self, force = False):
        """
        Update persistent cache with list of router and flap IDs for each
        household.  The default router and flap are the first ones found.
        """
        household = self.pcache['households'][self.default_household]
        if (household['default_router'] is not None and
            household['default_flap'] is not None and not force):
            return
        params = (
            ('with[]', 'children'),
        )
        for hid in self.pcache['households']:
            routers = self.pcache['households'][hid]['routers'] = []
            flaps = self.pcache['households'][hid]['flaps'] = []
            url = '%s/%s/device' % (_URL_HOUSEHOLD, hid,)
            response_children = self._get_data(url, params)
            for device in response_children['data']:
                if device['product_id'] == PROD_ID.FLAP: # Catflap
                    flaps.append( device['id'] )
                elif device['product_id'] == PROD_ID.ROUTER: # Router
                    routers.append( device['id'] )
            self.pcache['households'][hid]['default_flap'] = flaps[0]
            self.pcache['households'][hid]['default_router'] = routers[0]

    def update_pet_info(self, force = False):
        """
        Update persistent cache pet information.
        """
        if self.pcache['households'].get('pets') is not None and not force:
            return
        params = (
            ('with[]', ['photo', 'tag']),
        )
        for hid in self.pcache['households']:
            url = '%s/%s/pet' % (_URL_HOUSEHOLD, hid,)
            response_pets = self._get_data(url, params)
            self.pcache['households'][hid]['pets'] = {
                x['id']: {'name': x['name'],
                          'tag_id': x['tag_id'],
                          'photo': x.get('photo', {}).get('location')
                          } for x in response_pets['data']
                }

    def update_flap_status(self, hid = None):
        """
        Update flap status (via transient cache, default all).

        To minimise API traffic, please specify a household ID if you can.
        """
        hids = hid and [hid] or self.pcache['households'].keys()
        for hid in hids:
            household = self.pcache['households'][hid]
            for fid in household['flaps']:
                url = '%s/%s/status' % (_URL_DEV, fid,)
                response = self._get_data(url)
                self.flap_status.setdefault( hid, {} )[fid] = response['data']

    def update_router_status(self, hid = None):
        """
        Update router status.  Don't call unless you really need to because
        there's not much of interest here.  Defaults to all.

        To minimise API traffic, please specify a household ID if you can.
        """
        hids = hid and [hid] or self.pcache['households'].keys()
        for hid in hids:
            household = self.pcache['households'][hid]
            for rid in household['routers']:
                url = '%s/%s/status' % (_URL_DEV, rid,)
                response = self._get_data(url)
                self.router_status.setdefault( hid, {} )[rid] = response['data']

    def update_house_timeline(self, hid = None):
        """
        Update household event timeline (via transient cache) and curfew lock
        status.  Defaults to all.

        To minimise API traffic, please specify a household ID if you can.
        """
        hids = hid and [hid] or self.pcache['households'].keys()
        for hid in hids:
            params = (
                ('type', '0,3,6,7,12,13,14,17,19,20'),
            )
            url = '%s/household/%s' % (_URL_TIMELINE, hid,)
            response = self._get_data(url, params)
            htl = self.house_timeline[hid] = response['data']
            curfew_events = [x for x in htl if x['type'] == EVT.CURFEW]
            if curfew_events:
                # Serialised JSON within a serialised JSON structure?!  Weird.
                self.curfew_lock_info[hid] = json.loads(curfew_events[0]['data'])['locked']
            else:
                # new accounts might not be populated with the relevent information
                self.curfew_lock_info[hid] = None

    def update_pet_status(self, hid = None):
        """
        Update pet status via transient cache.  Defaults to all households.

        To minimise API traffic, please specify a household ID if you can.
        """
        hids = hid and [hid] or self.pcache['households'].keys()
        for hid in hids:
            household = self.pcache['households'][hid]
            params = (
                ('type', '0,3,6,7,12,13,14,17,19,20'),
            )
            petdata={}
            for pid in household['pets']:
                url = '%s/pet/%s/%s' % (_URL_TIMELINE, pid, hid,)
                response = self._get_data(url, params=params)
                petdata[pid] = response['data']
            self.pet_status[hid] = petdata

    def _get_data(self, url, params=None, refresh_interval=3600):
        headers = None
        if url in self.tcache:
            time_since_last =  datetime.now() - self.tcache[url]['ts']
            if time_since_last.total_seconds() < refresh_interval:
                # Use cached data but check freshness with ETag
                headers = self._create_header(ETag=self.tcache[url]['ETag'])
            else:
                # Ignore cached data and force refresh
                self._debug_print('Forcing refresh of data for %s' % (url,))
        else:
            self.tcache[url]={}
        if headers is None:
            headers = self._create_header()
        response = self._api_get(url, headers=headers, params=params)
        if response.status_code in [304, 500, 502, 503,]:
            # Used cached data in event of (respectively), not modified, server
            # error, server overload and gateway timeout
            #print('Got a 304')
            return self.tcache[url]['LastData']
        self.tcache[url]['LastData'] = response.json()
        self.tcache[url]['ETag'] = response.headers['ETag'][1:-1]
        self.tcache[url]['ts'] = datetime.now()
        return self.tcache[url]['LastData']

    def _create_header(self, ETag=None):
        headers={
            'Connection': 'keep-alive',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://surepetcare.io',
            'User-Agent': API_USER_AGENT,
            'Referer': 'https://surepetcare.io/',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en-GB;q=0.9',
            'X-Requested-With': 'com.sureflap.surepetcare',
        }

        if self.pcache['AuthToken'] is not None:
            headers['Authorization']='Bearer ' + self.pcache['AuthToken']
        if ETag is not None:
            headers['If-None-Match'] = ETag
        return headers

    def _api_get( self, url, *args, **kwargs ):
        r = self.s.get( url, *args, **kwargs )
        if r.status_code == 401:
            # Retry once
            self.update_authtoken( force = True )
            if 'headers' in kwargs and 'Authorization' in kwargs['headers']:
                kwargs['headers']['Authorization']='Bearer ' + self.pcache['AuthToken']
                r = self.s.get( url, *args, **kwargs )
            else:
                raise SPAPIException( 'Auth required but not present in header' )
        return r

    def _debug_print(self, string):
        if self.debug:
            print(string)

    def _log_req( self, r, *args, **kwargs ):
        """
        Debugging aid: print network requests
        """
        print( 'requests: %s %s -> %s' % (r.request.method, r.request.url, r.status_code,) )


class SurePetFlapMixin( object ):
    """
    A mixin that implements introspection of data collected by SurePetFlapNetwork.
    """

    def print_timeline(self, pet_id, entry_type = None, household_id = None):
        """
        Print timeline for a particular pet, specify entry_type to only get one
        direction.  Default household is used if not specified.
        """
        household_id = household_id or self.default_household
        household = self.pcache['households'][household_id]
        try:
            tag_id = household['pets'][pet_id]['tag_id']
            pet_name = household['pets'][pet_id]['name']
        except KeyError as e:
            raise SPAPIUnknownPet( str(e) )
        petdata = self.pet_status[household_id][pet_id]

        for movement in petdata:
            if movement['type'] in [EVT.MOVE_UID, EVT.LOCK_ST, EVT.USR_IFO, EVT.USR_NEW, EVT.CURFEW]:
                continue
            try:
                if entry_type is not None:
                    if movement['movements'][0]['tag_id'] == tag_id:
                        if movement['movements'][0]['direction'] == entry_type:
                            print(movement['movements'][0]['created_at'], pet_name, DIRECTION[movement['movements'][0]['direction']])
                else:
                    if movement['movements'][0]['tag_id'] == tag_id:
                        print(movement['movements'][0]['created_at'], pet_name, DIRECTION[movement['movements'][0]['direction']])
            except Exception as e:
                print(e)

    def locked(self, flap_id = None, household_id = None):
        """
        Return whether door is locked or not.  Default household and flap used
        if not specified.
        """
        household_id = household_id or self.default_household
        household = self.pcache['households'][household_id]
        if flap_id is None:
            flap_id = household['default_flap']
        lock = self.flap_status[household_id][flap_id]['locking']['mode']
        if lock == LK_MOD.UNLOCKED:
            return False
        if lock in [LK_MOD.LOCKED_IN, LK_MOD.LOCKED_OUT, LK_MOD.LOCKED_ALL,]:
            return True
        if lock == LK_MOD.CURFEW:
            if self.curfew_lock_info[household_id]:
                return True
            else:
                return False

    def lock_mode(self, flap_id = None, household_id = None):
        """
        Returns a string describing the flap lock mode.  Default household and
        flap used if not specified.
        """
        household_id = household_id or self.default_household
        household = self.pcache['households'][household_id]
        if flap_id is None:
            flap_id = household['default_flap']
        lock = self.flap_status[household_id][flap_id]['locking']['mode']
        if lock == LK_MOD.UNLOCKED:
            return 'Unlocked'
        elif lock == LK_MOD.LOCKED_IN:
            return 'Keep pets in'
        elif lock == LK_MOD.LOCKED_OUT:
            return 'Keep pets out'
        elif lock == LK_MOD.LOCKED_ALL:
            return 'Locked'
        elif lock == LK_MOD.CURFEW:
            #We are in curfew mode, check log to see if in locked or unlocked.
            if self.curfew_lock_info[household_id] is None:
                return 'Curfew enabled but state unknown'
            elif self.curfew_lock_info[household_id]:
                return 'Locked with curfew'
            else:
                return 'Unlocked with curfew'

    def find_id(self, name, household_id = None):
        """
        Returns the numeric ID (not the tag ID) of the pet by name.  Match is
        case insensitive and the first pet found with that name is returned.
        Default household used if not specified.
        """
        household_id = household_id or self.default_household
        for petid, petdata in self.pcache['households'][household_id]['pets'].items():
            if petdata['name'].lower() == name.lower():
                return petid

    def get_current_status(self, petid=None, name=None, household_id = None):
        """
        Returns a string describing the last known movement of the pet.

        Note that because sometimes the chip reader fails to read the pet
        (especially if they exit too quickly), this function can indicate that
        they're inside when in fact they're outside.  The same limitation
        presumably applies to the official website and app.
        """
        household_id = household_id or self.default_household
        if petid is None and name is None:
            raise ValueError('Please define petid or name')
        if petid is None:
            petid = self.find_id(name)
        petid=int(petid)
        if not int(petid) in self.pet_status[household_id]:
            return 'Unknown'
        else:
            #Get last update
            for movement in self.pet_status[household_id][petid]:
                if movement['type'] in [EVT.MOVE_UID, EVT.LOCK_ST, EVT.USR_IFO, EVT.USR_NEW, EVT.CURFEW]:
                    continue
                if movement['movements'][0]['direction'] != 0:
                    return INOUT_STATUS[movement['movements'][0]['direction']]
            return 'Unknown'


class SurePetFlap(SurePetFlapMixin, SurePetFlapNetwork):
    """Class to take care of network communication with SurePet's products.

    See docstring for parent classes on how to use.  In particular, **please**
    do preserve pcache and tcache between instantiations in order to minimise
    wasted requests to Sure's servers.

    Attributes pcache and tcache are guaranteed to be pickleable but not
    guaranteed to be serialisable as JSON.  How you store and retrieve these
    is up to you.
    """
    pass


class SPAPIException( Exception ):
    pass


class SPAPIAuthError( SPAPIException ):
    pass


class SPAPIUnknownPet( SPAPIException ):
    pass
