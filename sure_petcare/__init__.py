#!/usr/bin/python3
"""
Access the sure petcare access information
"""

import logging
import json
import requests
from datetime import datetime, timedelta
import os

DIRECTION ={0:'Looked through',1:'Entered House',2:'Left House'}
INOUT_STATUS = {1 : 'Inside', 2 : 'Outside'}

# REST API endpoints (no trailing slash)
URL_AUTH = 'https://app.api.surehub.io/api/auth/login'
URL_HOUSEHOLD = 'https://app.api.surehub.io/api/household'
URL_DEV = 'https://app.api.surehub.io/api/device'
URL_TIMELINE = 'https://app.api.surehub.io/api/timeline'

API_USER_AGENT = 'Mozilla/5.0 (Linux; Android 7.0; SM-G930F Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/64.0.3282.137 Mobile Safari/537.36'

class SurePetFlap(object):
    """Class to take care of cummunication with SurePet's products"""

    def __init__(self, email_address=None, password=None, device_id=None):
        if email_address ==None or password==None or device_id==None:
            raise ValueError('Please provide, email, password and device id')
        self.debug=True
        self.tcache={} # transient object cache
        self.pets={}
        self.s = requests.session()
        self.email_address = email_address
        self.password = password
        self.device_id = device_id
        self.update()


    #
    # All network-active API calls
    #

    def update(self):
        self.update_authtoken()
        self.update_household_id()
        self.get_device_ids()
        self.get_pet_info()
        self.update_pet_status()
        self.flap_status = self.get_flap_status()
        self.router_status = self.get_router_status()
        self.household = self.get_housedata()
        self.curfew_status = [ i for i in self.household['data'] if i['type'] == 20 ]
        self.curfew_lock_info=self.curfew_lock_infocalc()

    def update_authtoken(self):
        """Get authentication token from servers"""
        data = {"email_address": self.email_address,
                "password": self.password,
                "device_id": self.device_id,
                }
        headers=self.create_header()
        response = self.s.post(URL_AUTH, headers=headers, json=data)
        response_data = response.json()
        self.AuthToken = response_data['data']['token']

    def update_household_id(self):
        params = (
            ('with[]', ['household', 'pet', 'users', 'timezone']),
        )
        headers=self.create_header()
        response_household = self.s.get(URL_HOUSEHOLD, headers=headers, params=params)
        response_household = response_household.json()
        self.HouseholdID = str(response_household['data'][0]['id'])

    def get_device_ids(self):
        params = (
            ('with[]', 'children'),
        )
        url = '%s/%s/device' % (URL_HOUSEHOLD, self.HouseholdID,)
        response_children = self.get_data(url, params)
        for device in response_children['data']:
            if device['product_id'] == 3: # Catflap
                self.catflap_id = device['id']
            elif device['product_id'] == 1: # Router
                self.router_id = device['id']

    def get_pet_info(self):
        params = (
            ('with[]', ['photo', 'tag']),
        )
        url = '%s/%s/pet' % (URL_HOUSEHOLD, self.HouseholdID,)
        response_pets = self.get_data(url, params)
        for pet in response_pets['data']:
            pet_id = pet['id']
            self.pets[pet_id]={}
            self.pets[pet_id]['tag_id']=pet['tag_id']
            self.pets[pet_id]['name']=pet['name']
            self.pets[pet_id]['household']=pet['household_id']
            if 'photo' in pet:
                self.pets[pet_id]['photo']=pet['photo']['location']
            else:
                self.pets[pet_id]['photo']=None

    def get_flap_status(self):
        url = '%s/%s/status' % (URL_DEV, self.catflap_id,)
        response = self.get_data(url)
        return response

    def get_router_status(self):
        url = '%s/%s/status' % (URL_DEV, self.router_id,)
        response = self.get_data(url)
        return response

    def get_housedata(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        url = '%s/household/%s' % (URL_TIMELINE, self.HouseholdID,)
        response_housedata = self.get_data(url, params)
        return response_housedata

    def update_pet_status(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        petdata={}
        for pet_id in self.pets:
            url = '%s/pet/%s/%s' % (URL_TIMELINE, pet_id, self.HouseholdID,)
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
                self.debug_print('Refreshing data')
        if headers is None:
            self.tcache[url]={}
            headers = self.create_header()
        response = self.s.get(url, headers=headers, params=params)
        if response.status_code == 304:
            #print('Got a 304')
            return self.tcache[url]['LastData']
        self.tcache[url]['LastData'] = response.json()
        self.tcache[url]['ETag'] = response.headers['ETag'][1:-1]
        self.tcache[url]['ts'] = datetime.now()
        return self.tcache[url]['LastData']


    #
    # Introspection: return parsed and transformed data
    #

    def print_timeline(self, petid, entry_type=None):
        """Print timeline for a particular pet, specify entry_type to only get one direction"""
        petdata = self.petstatus[petid]
        for movement in petdata['data']:
            if movement['type'] in [20, 6, 12]:
                #type 20 == curfew
                #type 12 == User info/chage
                #type 6 == Lock status change

                # XXX Why exclude manual entries?  They affect status as
                #     reflected by the website, so surely this API should
                #     also.
                continue
            try:
                if entry_type is not None:
                    if movement['movements'][0]['tag_id'] == petid:
                        if movement['movements'][0]['direction'] == entry_type:
                            print(movement['movements'][0]['created_at'], DIRECTION[movement['movements'][0]['direction']])
                else:
                    if movement['movements'][0]['tag_id'] == petid:
                        print(movement['movements'][0]['created_at'], DIRECTION[movement['movements'][0]['direction']])
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
            if self.curfew_lock_info:
                return 'Locked with curfew'
            else:
                return 'Unlocked with curfew'

    def find_id(self, name):
        for petid in pets:
            if self.pets[petid]['name'] == name:
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
                if movement['type'] in [20, 6, 12]:
                    #type 20 == curfew
                    #type 7 == Cat entry
                    #type 6 == Manual change of entry

                    # XXX Why exclude manual entries?  They affect status as
                    #     reflected by the website, so surely this API should
                    #     also.
                    continue
                if movement['movements'][0]['direction'] != 0:
                    return STATUS_INOUT[movement['movements'][0]['direction']]
            return 'Unknown'

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

        if self.AuthToken is not None:
            headers['Authorization']='Bearer ' + self.AuthToken
        if ETag is not None:
            headers['If-None-Match'] = ETag
        return headers

    def debug_print(self, string):
        if self.debug:
            print(string)


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
    return str(mac_dec[-10:])
