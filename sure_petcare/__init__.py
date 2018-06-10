#!/usr/bin/python3
"""
Access the sure petcare access information
"""

import collections
import json
import requests
from datetime import datetime, timedelta
import os

DIRECTION ={0:'Looked through',1:'Entered House',2:'Left House'}
INOUT_STATUS = {1 : 'Inside', 2 : 'Outside'}

# The following event types are known, eg EVT.CURFEW.
EVT = (('MOVE', 0),
       ('LOCK_ST', 6),
       ('USR_IFO', 12),
       ('USR_NEW', 17),
       ('CURFEW', 20),
       )
y = [x[1] for x in EVT]
EVT = collections.namedtuple( 'EVT', [x[0] for x in EVT] )
EVT = EVT( *y )


# REST API endpoints (no trailing slash)
URL_AUTH = 'https://app.api.surehub.io/api/auth/login'
URL_HOUSEHOLD = 'https://app.api.surehub.io/api/household'
URL_DEV = 'https://app.api.surehub.io/api/device'
URL_TIMELINE = 'https://app.api.surehub.io/api/timeline'

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
            self.device_id = gen_device_id()
        else:
            self.device_id = device_id
        # The persistent object cache is for data that rarely or never change.
        # If at all possible, this *should* be preserved and passed to future
        # instances of this class.
        if pcache is None:
            self.pcache = {'AuthToken': None,
                           'HouseholdID': None,
                           'router_id': None,
                           'flap_id': None,
                           'pets': None,
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

    def update(self):
        self.update_authtoken()
        self.update_household_id()
        self.get_device_ids()
        self.get_pet_info()
        self.update_pet_status()
        self.flap_status = self.get_flap_status()
        #self.router_status = self.get_router_status()
        # XXX For now, router status contains little of interest and isn't worth
        #     the API call.
        self.household = self.get_housedata()
        self.curfew_status = [ i for i in self.household['data'] if i['type'] == 20 ]
        self.curfew_lock_info=self.curfew_lock_infocalc()

    def _log_req( self, r, *args, **kwargs ):
        """Debugging aid: print network requests"""
        print( 'requests: %s %s -> %s' % (r.request.method, r.request.url, r.status_code,) )

    def update_authtoken(self, force = False):
        """Get authentication token from servers"""
        if self.pcache['AuthToken'] is not None and not force:
            return
        data = {"email_address": self.email_address,
                "password": self.password,
                "device_id": self.device_id,
                }
        headers=self.create_header()
        response = self.s.post(URL_AUTH, headers=headers, json=data)
        if response.status_code == 401:
            raise SPAPIAuthError()
        response_data = response.json()
        self.pcache['AuthToken'] = response_data['data']['token']

    def update_household_id(self, force = False):
        if self.pcache['HouseholdID'] is not None and not force:
            return
        params = (
            ('with[]', ['household', 'pet', 'users', 'timezone']),
        )
        headers=self.create_header()
        response_household = self.api_get(URL_HOUSEHOLD, headers=headers, params=params)
        response_household = response_household.json()
        self.pcache['HouseholdID'] = response_household['data'][0]['id']

    def get_device_ids(self, force = False):
        if self.pcache['router_id'] is not None and self.pcache['flap_id'] is not None and not force:
            return
        params = (
            ('with[]', 'children'),
        )
        url = '%s/%s/device' % (URL_HOUSEHOLD, self.pcache['HouseholdID'],)
        response_children = self.get_data(url, params)
        for device in response_children['data']:
            if device['product_id'] == 3: # Catflap
                self.pcache['flap_id'] = device['id']
            elif device['product_id'] == 1: # Router
                self.pcache['router_id'] = device['id']

    def get_pet_info(self, force = False):
        if self.pcache['pets'] is not None and not force:
            return
        params = (
            ('with[]', ['photo', 'tag']),
        )
        url = '%s/%s/pet' % (URL_HOUSEHOLD, self.pcache['HouseholdID'],)
        response_pets = self.get_data(url, params)
        self.pcache['pets'] = {}
        for pet in response_pets['data']:
            pet_id = pet['id']
            self.pcache['pets'][pet_id] = {
                'tag_id': pet['tag_id'],
                'name': pet['name'],
                'household': pet['household_id'],
                }
            if 'photo' in pet:
                self.pcache['pets'][pet_id]['photo']=pet['photo']['location']
            else:
                self.pcache['pets'][pet_id]['photo']=None

    def get_flap_status(self):
        url = '%s/%s/status' % (URL_DEV, self.pcache['flap_id'],)
        response = self.get_data(url)
        return response

    def get_router_status(self):
        url = '%s/%s/status' % (URL_DEV, self.pcache['router_id'],)
        response = self.get_data(url)
        return response

    def get_housedata(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        url = '%s/household/%s' % (URL_TIMELINE, self.pcache['HouseholdID'],)
        response_housedata = self.get_data(url, params)
        return response_housedata

    def update_pet_status(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        petdata={}
        for pet_id in self.pcache['pets']:
            url = '%s/pet/%s/%s' % (URL_TIMELINE, pet_id, self.pcache['HouseholdID'],)
            response = self.get_data(url, params=params)
            petdata[pet_id] = response
        self.petstatus=petdata

    def get_data(self, url, params=None, refresh_interval=3600):
        headers = None
        if url in self.tcache:
            time_since_last =  datetime.now() - self.tcache[url]['ts']
            if time_since_last.total_seconds() < refresh_interval: #Refresh every hour at least
                headers = self.create_header(ETag=self.tcache[url]['ETag'])
            else:
                self.debug_print('Using cached data for %s' % (url,))
        if headers is None:
            self.tcache[url]={}
            headers = self.create_header()
        response = self.api_get(url, headers=headers, params=params)
        if response.status_code in [304, 500, 502, 503,]:
            # Used cached data in event of (respectively), not modified, server
            # error, server overload and gateway timeout
            #print('Got a 304')
            return self.tcache[url]['LastData']
        self.tcache[url]['LastData'] = response.json()
        self.tcache[url]['ETag'] = response.headers['ETag'][1:-1]
        self.tcache[url]['ts'] = datetime.now()
        return self.tcache[url]['LastData']

    def create_header(self, ETag=None):
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

    def api_get( self, url, *args, **kwargs ):
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

    def debug_print(self, string):
        if self.debug:
            print(string)


class SurePetFlapMixin( object ):
    """A mixin that implements introspection of data collected by
    SurePetFlapNetwork.
    """

    def print_timeline(self, petid, entry_type=None):
        """Print timeline for a particular pet, specify entry_type to only get one direction"""
        try:
            tag_id = self.pcache['pets'][petid]['tag_id']
            pet_name = self.pcache['pets'][petid]['name']
        except KeyError as e:
            raise SPAPIUnknownPet( str(e) )
        petdata = self.petstatus[petid]

        for movement in petdata['data']:
            if movement['type'] in [EVT.LOCK_ST, EVT.USR_IFO, EVT.USR_NEW, EVT.CURFEW]:
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

    def curfew_lock_infocalc(self):
        if len(self.curfew_status) > 0:
            return json.loads(self.curfew_status[0]['data'])['locked']
        else:
            return 'Unknown' #new accounts might not be populated with the relevent information

    def locked(self):
        lock = self.flap_status['data']['locking']['mode']
        if lock == 0:
            return False
        if lock in [1, 2, 3]:
            return True
        if lock == 4:
            if self.curfew_lock_info:
                return True
            else:
                return False

    def lock_mode(self):
        lock = self.flap_status['data']['locking']['mode']
        if lock == 0:
            return 'Unlocked'
        elif lock == 1:
            return 'Keep pets in'
        elif lock == 2:
            return 'Keep pets out'
        elif lock == 3:
            return 'Locked'
        elif lock == 4:
            #We are in curfew mode, check log to see if in locked or unlocked.
            if self.curfew_lock_info == 'Unknown':
                return 'Curfew enabled but state unknown'
            elif self.curfew_lock_info:
                return 'Locked with curfew'
            else:
                return 'Unlocked with curfew'

    def find_id(self, name):
        for petid in self.pcache['pets']:
            if self.pcache['pets'][petid]['name'] == name:
                return petid

    def get_current_status(self, petid=None, name=None):
        if petid is None and name is None:
            raise ValueError('Please define petid or name')
        if petid is None:
            petid = self.find_id(name)
        petid=int(petid)
        if not int(petid) in self.petstatus:
            return 'Unknown'
        else:
            #Get last update
            for movement in self.petstatus[petid]['data']:
                if movement['type'] in [EVT.LOCK_ST, EVT.USR_IFO, EVT.USR_NEW, EVT.CURFEW]:
                    continue
                if movement['movements'][0]['direction'] != 0:
                    return INOUT_STATUS[movement['movements'][0]['direction']]
            return 'Unknown'


class SurePetFlap(SurePetFlapMixin, SurePetFlapNetwork):
    """Class to take care of network communication with SurePet's products.

    See docstring for parent classes on how to use.
    """
    pass


class SPAPIException( Exception ):
    pass


class SPAPIAuthError( SPAPIException ):
    pass


class SPAPIUnknownPet( SPAPIException ):
    pass


def getmac():
    mac = None
    folders = os.listdir('/sys/class/net/')
    for interface in folders:
        if interface == 'lo':
            continue
        try:
            mac = open('/sys/class/net/'+interface+'/address').readline()
            # XXX What happens when multiple interfaces are found?  Might
            #     be better to break here to stop at the first MAC which,
            #     on most/many systems, will be the first wired Ethernet
            #     interface.
            # break
        except Exception as e:
            return None
    if mac is not None:
        return mac.strip() #trim new line


def gen_device_id():
    mac_dec = int( getmac().replace( ':', '').replace( '-', '' ), 16 )
    # Use low order bits because upper two octets are low entropy
    return str(mac_dec)[-10:]
